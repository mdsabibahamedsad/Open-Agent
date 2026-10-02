"""MP25: distributed scheduler (§16-18) + autoscaler (§19-20).

The scheduler is horizontally scalable: instances compete for a
``scheduler tick`` lease; only the holder enqueues due jobs. Schedule
deduplication uses (schedule_id, scheduled_at, execution_key) so
multiple replicas, restarts, clock drift and retries cannot duplicate
work. Delayed jobs persist in the DB (never in-memory timers alone).
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

# ------------------------------------------------------------ dedup keys ---
from openagent.cloud.errors import LeaseConflict


def dedup_key(schedule_id: str, scheduled_at: datetime) -> str:
    """Stable execution key for a scheduled fire time (§17)."""
    moment = scheduled_at
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    digest = hashlib.sha256(
        f"{schedule_id}:{moment.isoformat()}".encode("utf-8")).hexdigest()[:24]
    return f"sch_{digest}"


def is_misfire(scheduled_at: datetime, now: datetime, grace_seconds: int) -> bool:
    return (now - scheduled_at).total_seconds() > max(0, grace_seconds)


# -------------------------------------------------------------- autoscaler ---
@dataclass
class AutoscaleInput:
    queue: str
    queue_depth: int
    oldest_age_seconds: float
    worker_count: int
    avg_utilization: float  # 0..1
    min_workers: int = 1
    max_workers: int = 20
    scale_up_step: int = 2
    scale_down_step: int = 1
    cooldown_remaining_seconds: float = 0.0
    global_max_workers: int = 100
    region_max_workers: int = 100
    org_at_quota: bool = False


@dataclass
class AutoscaleDecision:
    desired_workers: int
    action: str  # "scale_up" | "scale_down" | "hold"
    reason: str


def decide_autoscale(inp: AutoscaleInput) -> AutoscaleDecision:
    """Queue-depth + age + utilization driven autoscaler with safety caps."""
    # Hard safety rails first (§20): never exceed configured maxima, never
    # scale a tenant that already hit quota.
    ceiling = min(inp.max_workers, inp.global_max_workers, inp.region_max_workers)
    floor = max(0, min(inp.min_workers, ceiling))

    if inp.cooldown_remaining_seconds > 0:
        return AutoscaleDecision(desired_workers=max(floor, min(inp.worker_count, ceiling)),
                                 action="hold", reason="cooldown active")

    pressure = inp.queue_depth > 0 and (inp.queue_depth > inp.worker_count * 4
                                        or inp.oldest_age_seconds > 60
                                        or inp.avg_utilization > 0.75)
    idle = (inp.queue_depth == 0 and inp.avg_utilization < 0.2) or inp.org_at_quota

    if pressure and inp.worker_count < ceiling:
        desired = min(ceiling, inp.worker_count + max(1, inp.scale_up_step))
        return AutoscaleDecision(desired_workers=desired, action="scale_up",
                                 reason=f"queue pressure depth={inp.queue_depth} "
                                        f"age={inp.oldest_age_seconds:.0f}s "
                                        f"util={inp.avg_utilization:.2f}")
    if idle and inp.worker_count > floor:
        desired = max(floor, inp.worker_count - max(1, inp.scale_down_step))
        if desired == inp.worker_count:
            return AutoscaleDecision(desired_workers=desired, action="hold",
                                     reason="at floor")
        return AutoscaleDecision(desired_workers=desired, action="scale_down",
                                 reason="queue idle, scaling down")
    return AutoscaleDecision(desired_workers=max(floor, min(inp.worker_count, ceiling)),
                             action="hold", reason="within target band")


# ------------------------------------------------------- tick coordination ---
SCHEDULER_TICK_RESOURCE = "cloud-scheduler-tick"


async def try_acquire_tick(lease_backend, owner_id: str,
                           ttl_seconds: int = 60) -> Optional[Any]:
    """Single-holder scheduler tick. Returns the lease or None."""
    try:
        return await lease_backend.acquire(SCHEDULER_TICK_RESOURCE, owner_id, ttl_seconds)
    except LeaseConflict:
        return None
    except Exception:
        return None


def new_schedule_id() -> str:
    return f"sch_{uuid.uuid4().hex[:16]}"
