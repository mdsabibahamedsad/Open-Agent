"""MP25: cloud usage metering (§38), quota checks (§40), cost protection
(§41), platform health (§54), incident mode (§78-79), retention/GC (§73-75).

Billing is never duplicated: usage funnels into the existing MP24
commerce usage meters (``usage_meters``/``usage_records``). This module
holds the cloud-side pure logic — meter-name mapping, quota evaluation,
health aggregation, GC/orphan classification — while ``service.py``
performs the DB writes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from openagent.cloud.types import IncidentMode

# Cloud execution signals -> MP24 commerce meter names (§38).
CLOUD_METER_MAP = {
    "worker_seconds": "worker_seconds",
    "cpu_seconds": "cpu_seconds",
    "memory_seconds": "memory_seconds",
    "sandbox_seconds": "sandbox_seconds",
    "browser_seconds": "browser_seconds",
    "storage_bytes": "storage_bytes",
    "storage_gb_hours": "storage_gb_hours",
    "network_bytes": "network_bytes",
    "execution_count": "execution_count",
    "agent_steps": "agent_steps",
    "model_tokens": "model_tokens",
    "tool_calls": "tool_calls",
}

QUOTA_DIMENSIONS = (
    "concurrent_executions", "monthly_executions", "worker_minutes",
    "storage_bytes", "bandwidth_bytes", "agent_steps", "browser_minutes",
    "sandbox_minutes", "model_tokens", "api_calls",
)


def meter_name(signal: str) -> str:
    return CLOUD_METER_MAP.get(signal, signal)


def to_usage_records(*, organization_id: str, execution_id: str,
                     usage: dict[str, float],
                     dedup_prefix: str = "cloud") -> list[dict[str, Any]]:
    """Map execution usage signals to commerce usage-record dicts."""
    records = []
    for signal, quantity in (usage or {}).items():
        try:
            qty = float(quantity)
        except (TypeError, ValueError):
            continue
        if qty <= 0:
            continue
        records.append({"meter": meter_name(signal), "quantity": qty,
                        "organization_id": organization_id,
                        "dedup_key": f"{dedup_prefix}:{execution_id}:{signal}"})
    return records


# ----------------------------------------------------------------- quotas ---
@dataclass
class QuotaCheck:
    dimension: str
    limit: Optional[float]  # None = unlimited
    used: float
    requested: float = 1.0

    def evaluate(self) -> tuple[bool, str, float]:
        if self.requested < 0:
            return False, "requested quantity must be >= 0", 0.0
        if self.limit is None:
            return True, "unlimited quota", float("inf")
        remaining = float(self.limit) - float(self.used)
        if remaining >= float(self.requested):
            return True, "within quota", remaining - float(self.requested)
        return False, f"{self.dimension} quota exceeded", remaining


def evaluate_quotas(checks: list[QuotaCheck]) -> tuple[bool, str, dict[str, float]]:
    remaining: dict[str, float] = {}
    for check in checks:
        allowed, reason, left = check.evaluate()
        remaining[check.dimension] = left
        if not allowed:
            return False, reason, remaining
    return True, "within quota", remaining


# ---------------------------------------------------------- cost protection ---
@dataclass
class ExecutionBudget:
    max_seconds: int = 3600
    max_cpu_millicores: int = 4000
    max_memory_mb: int = 16384
    max_storage_bytes: int = 10737418240  # 10 GiB
    max_browser_sessions: int = 2
    max_sandbox_sessions: int = 4


def check_budget(*, cpu_millicores: int, memory_mb: int,
                 timeout_seconds: int, budget: ExecutionBudget,
                 needs_browser: bool = False) -> tuple[bool, str]:
    if timeout_seconds > budget.max_seconds:
        return False, f"timeout exceeds {budget.max_seconds}s"
    if cpu_millicores > budget.max_cpu_millicores:
        return False, f"cpu exceeds {budget.max_cpu_millicores}m"
    if memory_mb > budget.max_memory_mb:
        return False, f"memory exceeds {budget.max_memory_mb}MiB"
    if needs_browser and budget.max_browser_sessions <= 0:
        return False, "browser sessions not allowed by budget"
    return True, "within budget"


# ------------------------------------------------------------------ health ---
HEALTHY = "HEALTHY"
DEGRADED = "DEGRADED"
UNAVAILABLE = "UNAVAILABLE"
UNKNOWN = "UNKNOWN"

HEALTH_COMPONENTS = ("api", "database", "queue", "workers", "scheduler",
                     "object_storage", "sandbox", "browser",
                     "model_providers", "connectors")


def aggregate_health(components: dict[str, str]) -> str:
    states = [components.get(c, UNKNOWN) for c in HEALTH_COMPONENTS]
    if any(s == UNAVAILABLE for s in states):
        return DEGRADED if components.get("api") == HEALTHY else UNAVAILABLE
    if any(s == DEGRADED for s in states):
        return DEGRADED
    if all(s == HEALTHY for s in states):
        return HEALTHY
    return UNKNOWN


# ---------------------------------------------------------------- incident ---
INCIDENT_POLICY = {
    IncidentMode.NORMAL: {"accept_new": True, "reason": "normal operation"},
    IncidentMode.DEGRADED: {"accept_new": True, "reason": "degraded: reduced capacity"},
    IncidentMode.MAINTENANCE: {"accept_new": False, "reason": "maintenance: new executions paused"},
    IncidentMode.EMERGENCY: {"accept_new": False, "reason": "emergency: new executions stopped"},
}


def incident_allows_submit(mode: str) -> tuple[bool, str]:
    policy = INCIDENT_POLICY.get(str(mode or IncidentMode.NORMAL).upper(),
                                 INCIDENT_POLICY[IncidentMode.NORMAL])
    return bool(policy["accept_new"]), str(policy["reason"])


# ------------------------------------------------------------ retention/GC ---
RETENTION_KEYS = ("execution_events", "logs", "artifacts", "heartbeats",
                  "scheduler_records", "temp_files")


def retention_cutoff(retention_seconds: int,
                     now: Optional[datetime] = None) -> Optional[datetime]:
    from datetime import timedelta
    if retention_seconds <= 0:
        return None
    moment = now or datetime.now(timezone.utc)
    return moment - timedelta(seconds=retention_seconds)


@dataclass
class OrphanReport:
    kind: str
    resource_id: str
    detail: str = ""
    action: str = "detect"  # detect -> quarantine/reconcile -> cleanup


def detect_orphans(*, execution_ids: set[str], worker_claims: dict[str, str],
                   artifact_execution_ids: dict[str, str],
                   sandbox_tasks: dict[str, str],
                   live_tasks: set[str],
                   worker_last_seen: dict[str, datetime],
                   heartbeat_ttl_seconds: int,
                   queue_execution_ids: set[str],
                   now: Optional[datetime] = None) -> list[OrphanReport]:
    """Classify orphans (§75). Never deletes — callers quarantine first."""
    from datetime import timedelta
    moment = now or datetime.now(timezone.utc)
    reports: list[OrphanReport] = []
    for execution_id, worker_id in worker_claims.items():
        if execution_id not in execution_ids and execution_id not in queue_execution_ids:
            reports.append(OrphanReport(kind="execution_without_worker",
                                        resource_id=execution_id,
                                        detail=f"claimed by {worker_id}"))
    for artifact_id, execution_id in artifact_execution_ids.items():
        if execution_id not in execution_ids:
            reports.append(OrphanReport(kind="artifact_without_execution",
                                        resource_id=artifact_id,
                                        detail=f"execution {execution_id} missing"))
    for sandbox_id, task_id in sandbox_tasks.items():
        if task_id not in live_tasks:
            reports.append(OrphanReport(kind="sandbox_without_task",
                                        resource_id=sandbox_id,
                                        detail=f"task {task_id} not live"))
    for worker_id, last_seen in worker_last_seen.items():
        if (moment - last_seen) > timedelta(seconds=heartbeat_ttl_seconds * 2):
            reports.append(OrphanReport(kind="worker_without_heartbeat",
                                        resource_id=worker_id))
    for execution_id in queue_execution_ids:
        if execution_id not in execution_ids:
            reports.append(OrphanReport(kind="queue_message_without_execution",
                                        resource_id=execution_id))
    return reports
