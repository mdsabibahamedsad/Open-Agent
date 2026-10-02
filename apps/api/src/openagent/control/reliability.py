"""MP26: reliability — unified health (§25-26), alerting (§27-29),
incidents (§30-32), maintenance (§33), status (§34-35), deployments +
rollback (§36-38), reconciliation + controllers (§94-95), operation
locks (§96). Pure logic; persistence lives in db/models/control.py.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

from openagent.control.types import (
    AlertSeverity, AlertStatus, DeploymentStatus, HealthState,
    IncidentStatus, ReleaseState, aggregate_health,
    is_valid_incident_transition, public_status_for,
)

HEALTH_COMPONENTS = ("api", "database", "redis", "queue", "workers",
                     "scheduler", "sandbox", "browser", "storage",
                     "model_providers", "connectors", "mcp")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ------------------------------------------------------------- health (§25) ---
@dataclass
class HealthCheck:
    component: str
    kind: str  # liveness|readiness|dependency|operational
    state: str
    latency_ms: float = 0.0
    detail: str = ""
    checked_at: datetime = field(default_factory=_utcnow)

    def validate(self) -> tuple[bool, str]:
        if self.component not in HEALTH_COMPONENTS:
            return False, f"unknown component {self.component}"
        if self.kind not in ("liveness", "readiness", "dependency", "operational"):
            return False, f"unknown check kind {self.kind}"
        if self.state not in HealthState.ALL:
            return False, f"unknown state {self.state}"
        return True, "ok"


def summarize_health(checks: list[HealthCheck]) -> dict[str, Any]:
    """Aggregate per-component worst state; overall worst wins.

    Liveness failures dominate (process unhealthy); expensive dependency
    checks never gate liveness — callers separate kinds (§26).
    """
    by_component: dict[str, str] = {}
    for check in checks:
        prev = by_component.get(check.component, HealthState.HEALTHY)
        rank = HealthState.RANK
        by_component[check.component] = (
            check.state if rank.get(check.state, 1) >= rank.get(prev, 0) else prev)
    for component in HEALTH_COMPONENTS:
        by_component.setdefault(component, HealthState.UNKNOWN)
    overall = aggregate_health(list(by_component.values()))
    return {"status": overall, "components": by_component,
            "public": public_status_for(overall),
            "checked_at": _utcnow().isoformat()}


# ------------------------------------------------------------ alerts (§27-28) ---
ALERT_CONDITIONS = ("queue_overload", "worker_failure", "region_degradation",
                    "database_latency", "storage_failure",
                    "execution_failure_spike", "api_error_spike",
                    "auth_attack_spike", "quota_abuse",
                    "unusual_resource_consumption")


@dataclass
class AlertRule:
    rule_id: str
    metric: str
    condition: str  # gt|lt|eq — never arbitrary code (§82)
    threshold: float
    duration_seconds: int = 300
    severity: str = AlertSeverity.WARNING
    destinations: list[str] = field(default_factory=list)

    def validate(self) -> tuple[bool, str]:
        if self.condition == "queue_overload" or True:
            pass
        if self.condition not in ("gt", "lt", "eq"):
            return False, "condition must be gt|lt|eq (no code execution)"
        if self.severity not in AlertSeverity.ALL:
            return False, f"unknown severity {self.severity}"
        if self.threshold < 0:
            return False, "threshold must be >= 0"
        if self.duration_seconds < 0:
            return False, "duration must be >= 0"
        return True, "ok"

    def fires(self, value: float) -> bool:
        if self.condition == "gt":
            return value > self.threshold
        if self.condition == "lt":
            return value < self.threshold
        return value == self.threshold


@dataclass
class Alert:
    alert_id: str = field(default_factory=lambda: f"alr_{uuid.uuid4().hex[:12]}")
    rule_id: str = ""
    severity: str = AlertSeverity.WARNING
    source: str = ""
    condition: str = ""
    threshold: float = 0.0
    observed: float = 0.0
    status: str = AlertStatus.FIRING
    created_at: datetime = field(default_factory=_utcnow)
    resolved_at: Optional[datetime] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def dedup_key(self) -> str:
        raw = f"{self.rule_id}:{self.source}:{self.condition}"
        return hashlib.sha256(raw.encode()).hexdigest()[:24]


class AlertEngine:
    """Evaluates rules over metric snapshots; dedups + flaps safely."""

    def __init__(self) -> None:
        self._open: dict[str, Alert] = {}

    def evaluate(self, rule: AlertRule, value: float,
                 source: str = "") -> Optional[Alert]:
        key_source = f"{rule.rule_id}:{source}"
        if rule.fires(value):
            if key_source in self._open:
                return None  # already firing: no duplicate
            alert = Alert(rule_id=rule.rule_id, severity=rule.severity,
                          source=source, condition=rule.condition,
                          threshold=rule.threshold, observed=value)
            self._open[key_source] = alert
            return alert
        # Condition cleared: auto-resolve the open alert.
        existing = self._open.pop(key_source, None)
        if existing is not None:
            existing.status = AlertStatus.RESOLVED
            existing.resolved_at = _utcnow()
        return None

    def acknowledge(self, alert_id: str) -> Optional[Alert]:
        for alert in self._open.values():
            if alert.alert_id == alert_id:
                alert.status = AlertStatus.ACKNOWLEDGED
                return alert
        return None

    def open_alerts(self) -> list[Alert]:
        return list(self._open.values())


# ------------------------------------------------------ notifier (§29) ---
class Notifier:
    """Provider-neutral notification interface. Destinations: email,
    webhook, Slack, Discord, PagerDuty, generic incident systems. Real
    delivery reuses the Connector framework (no duplicated auth)."""

    async def send(self, alert: Alert, destination: str) -> tuple[bool, str]:
        raise NotImplementedError


class LogNotifier(Notifier):
    """Always-available fallback: records notifications locally so an
    alerting outage never breaks execution (§100.15)."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send(self, alert: Alert, destination: str) -> tuple[bool, str]:
        self.sent.append({"alert_id": alert.alert_id, "severity": alert.severity,
                         "destination": destination,
                         "at": _utcnow().isoformat()})
        return True, "recorded"


# ---------------------------------------------------------- incidents (§30) ---
@dataclass
class IncidentEvent:
    at: datetime
    actor: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {"at": self.at.isoformat(), "actor": self.actor,
                "message": self.message}


@dataclass
class Incident:
    incident_id: str = field(default_factory=lambda: f"inc_{uuid.uuid4().hex[:12]}")
    title: str = ""
    severity: str = AlertSeverity.ERROR
    status: str = IncidentStatus.DETECTED
    affected_services: list[str] = field(default_factory=list)
    affected_regions: list[str] = field(default_factory=list)
    responders: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    resolution: str = ""
    postmortem_ref: str = ""
    created_at: datetime = field(default_factory=_utcnow)
    timeline: list[IncidentEvent] = field(default_factory=list)

    def append(self, actor: str, message: str,
               at: Optional[datetime] = None) -> IncidentEvent:
        """Timeline is append-only (immutable history, §32)."""
        event = IncidentEvent(at=at or _utcnow(), actor=actor, message=message)
        self.timeline.append(event)
        return event

    def transition(self, to_status: str, actor: str,
                   note: str = "") -> tuple[bool, str]:
        if not is_valid_incident_transition(self.status, to_status):
            return False, f"{self.status} -> {to_status} not allowed"
        self.status = to_status
        self.append(actor, f"status -> {to_status}" + (f": {note}" if note else ""))
        return True, "ok"


@dataclass
class MaintenanceWindow:
    window_id: str = field(default_factory=lambda: f"mnt_{uuid.uuid4().hex[:12]}")
    starts_at: datetime = field(default_factory=_utcnow)
    ends_at: datetime = field(default_factory=_utcnow)
    affected: list[str] = field(default_factory=list)
    expected_behavior: str = ""
    active: bool = True

    def is_active(self, now: Optional[datetime] = None) -> bool:
        moment = now or _utcnow()
        return bool(self.active and self.starts_at <= moment <= self.ends_at)


# ------------------------------------------------------- deployments (§36-38) ---
@dataclass
class Deployment:
    deployment_id: str = field(default_factory=lambda: f"dpl_{uuid.uuid4().hex[:12]}")
    service: str = ""  # api|frontend|worker|scheduler|control-plane
    version: str = ""
    commit: str = ""
    build: str = ""
    environment: str = "production"
    deployer: str = ""
    status: str = DeploymentStatus.PENDING
    deployed_at: Optional[datetime] = None

    def validate(self) -> tuple[bool, str]:
        if self.service not in ("api", "frontend", "worker", "scheduler", "control-plane"):
            return False, f"unknown service {self.service}"
        if not self.version:
            return False, "version is required"
        if self.environment not in ("development", "staging", "production"):
            return False, f"unknown environment {self.environment}"
        return True, "ok"


@dataclass
class Release:
    release_id: str = field(default_factory=lambda: f"rel_{uuid.uuid4().hex[:12]}")
    environment: str = "staging"
    version: str = ""
    state: str = ReleaseState.CREATED
    deployments: list[str] = field(default_factory=list)


def rollback_plan(*, current_version: str, target_version: str,
                  migrations_since: list[str],
                  destructive_migrations: list[str]) -> dict[str, Any]:
    """Controlled rollback pre-checks (§38). Never auto-rollback."""
    if not target_version:
        return {"allowed": False, "reason": "target version required"}
    if current_version == target_version:
        return {"allowed": False, "reason": "already at target version"}
    blockers = [m for m in migrations_since if m in destructive_migrations]
    if blockers:
        return {"allowed": False,
                "reason": f"destructive migrations block rollback: {blockers}",
                "requires": "manual migration compatibility review"}
    return {"allowed": True, "reason": "safe to roll back",
            "steps": ["verify target artifact", "drain affected workers",
                      "deploy target version", "verify health",
                      "audit rollback"]}


# ------------------------------------------------- reconciliation (§93-95) ---
@dataclass
class ReconDiff:
    key: str
    desired: Any
    observed: Any
    action: str  # create|update|delete|noop


def reconcile(desired: dict[str, Any],
              observed: dict[str, Any]) -> list[ReconDiff]:
    diffs: list[ReconDiff] = []
    for key, want in desired.items():
        got = observed.get(key, None)
        if got is None:
            diffs.append(ReconDiff(key, want, None, "create"))
        elif got != want:
            diffs.append(ReconDiff(key, want, got, "update"))
        else:
            diffs.append(ReconDiff(key, want, got, "noop"))
    for key, got in observed.items():
        if key not in desired:
            diffs.append(ReconDiff(key, None, got, "delete"))
    return diffs


class Controller:
    """Idempotent controller base (worker pool, region, flags, deploys)."""

    name = "base"

    def desired(self) -> dict[str, Any]:
        raise NotImplementedError

    def observed(self) -> dict[str, Any]:
        raise NotImplementedError

    def apply(self, diff: ReconDiff) -> tuple[bool, str]:
        raise NotImplementedError

    def run_once(self) -> dict[str, Any]:
        diffs = reconcile(self.desired(), self.observed())
        applied, failed = 0, []
        for diff in diffs:
            if diff.action == "noop":
                continue
            try:
                ok, _ = self.apply(diff)
                if ok:
                    applied += 1
                else:
                    failed.append(diff.key)
            except Exception as exc:
                failed.append(f"{diff.key}:{exc}")
        return {"controller": self.name, "applied": applied,
                "failed": failed, "verified": not failed}


class MemoryController(Controller):
    """In-memory controller for tests and self-hosted singletons."""

    def __init__(self, name: str, want: dict[str, Any]) -> None:
        self.name = name
        self._want = dict(want)
        self._have: dict[str, Any] = {}
        self.applied: list[str] = []

    def desired(self) -> dict[str, Any]:
        return dict(self._want)

    def observed(self) -> dict[str, Any]:
        return dict(self._have)

    def apply(self, diff: ReconDiff) -> tuple[bool, str]:
        if diff.action == "delete":
            self._have.pop(diff.key, None)
        else:
            self._have[diff.key] = diff.desired
        self.applied.append(diff.key)
        return True, "applied"


# ------------------------------------------------------- op locks (§96) ---
class OperationLock:
    """Concurrency protection for dangerous actions (e.g. two admins
    draining the same region). Backed by an async lease-style backend."""

    def __init__(self) -> None:
        self._held: dict[str, tuple[str, datetime]] = {}

    def acquire(self, resource: str, owner: str,
                ttl_seconds: int = 300) -> tuple[bool, str]:
        now = _utcnow()
        holder = self._held.get(resource)
        if holder is not None:
            holder_owner, expires = holder
            if holder_owner != owner and expires > now:
                return False, f"locked by {holder_owner}"
        self._held[resource] = (owner, now + timedelta(seconds=max(1, ttl_seconds)))
        return True, "acquired"

    def release(self, resource: str, owner: str) -> None:
        holder = self._held.get(resource)
        if holder is not None and holder[0] == owner:
            del self._held[resource]

    def dry_run_drain(self, resource: str, impacted: dict[str, Any]) -> dict[str, Any]:
        """Impact preview without applying changes (§99)."""
        holder = self._held.get(resource)
        return {"resource": resource,
                "locked": holder is not None and holder[1] > _utcnow(),
                "locked_by": holder[0] if holder else "",
                "would_impact": impacted,
                "applied": False}
