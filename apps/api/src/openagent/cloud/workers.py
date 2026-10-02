"""MP25: worker registry — lifecycle, heartbeat, capacity (§10-11, §44).

Registration advertises id/region/pool/capabilities/resources; heartbeats
refresh liveness; expiry marks workers UNHEALTHY so outstanding work
becomes recoverable. Pure-python core (DB persistence layered in the
service) keeps the lifecycle unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from openagent.cloud.errors import InvalidWorkerTransition, WorkerNotFound
from openagent.cloud.placement import WorkerAdvert
from openagent.cloud.types import WorkerState, is_valid_worker_transition


@dataclass
class WorkerRecord:
    worker_id: str
    service_identity: str
    region_id: str
    pool_id: str
    capabilities: list[str] = field(default_factory=list)
    labels: dict[str, str] = field(default_factory=dict)
    state: str = WorkerState.REGISTERING
    version: str = "0.1.0"
    max_concurrency: int = 4
    active_count: int = 0
    cpu_millicores_total: int = 2000
    cpu_millicores_used: int = 0
    memory_mb_total: int = 4096
    memory_mb_used: int = 0
    supports_gpu: bool = False
    tenant_restriction: str = ""
    last_heartbeat_at: Optional[datetime] = None
    registered_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    drained_at: Optional[datetime] = None

    def advert(self) -> WorkerAdvert:
        return WorkerAdvert(
            worker_id=self.worker_id, region_id=self.region_id,
            pool_id=self.pool_id, capabilities=list(self.capabilities),
            max_concurrency=self.max_concurrency, active_count=self.active_count,
            cpu_millicores_total=self.cpu_millicores_total,
            cpu_millicores_used=self.cpu_millicores_used,
            memory_mb_total=self.memory_mb_total,
            memory_mb_used=self.memory_mb_used,
            supports_gpu=self.supports_gpu, version=self.version,
            draining=self.state == WorkerState.DRAINING)

    def heartbeat_stale(self, ttl_seconds: int,
                        now: Optional[datetime] = None) -> bool:
        if self.last_heartbeat_at is None:
            return True
        moment = now or datetime.now(timezone.utc)
        return (moment - self.last_heartbeat_at).total_seconds() > ttl_seconds


class WorkerRegistry:
    def __init__(self, heartbeat_ttl_seconds: int = 90) -> None:
        self.heartbeat_ttl_seconds = heartbeat_ttl_seconds
        self._workers: dict[str, WorkerRecord] = {}

    # ---------------------------------------------------------- lifecycle ---
    def register(self, record: WorkerRecord) -> WorkerRecord:
        if not record.worker_id or not record.region_id or not record.pool_id:
            raise ValueError("worker_id/region_id/pool_id are required")
        if not record.capabilities:
            raise ValueError("workers must advertise at least one capability")
        if record.max_concurrency <= 0:
            raise ValueError("max_concurrency must be > 0")
        record.state = WorkerState.STARTING
        record.last_heartbeat_at = datetime.now(timezone.utc)
        self._workers[record.worker_id] = record
        return record

    def get(self, worker_id: str) -> WorkerRecord:
        record = self._workers.get(worker_id)
        if record is None:
            raise WorkerNotFound(f"unknown worker {worker_id}")
        return record

    def transition(self, worker_id: str, to_state: str) -> WorkerRecord:
        record = self.get(worker_id)
        if not is_valid_worker_transition(record.state, to_state):
            raise InvalidWorkerTransition(f"{record.state} -> {to_state} not allowed")
        record.state = to_state
        if to_state == WorkerState.DRAINING:
            record.drained_at = datetime.now(timezone.utc)
        return record

    def heartbeat(self, worker_id: str, *, active_count: int,
                  cpu_used: int, memory_used: int,
                  state: str = "") -> WorkerRecord:
        record = self.get(worker_id)
        record.last_heartbeat_at = datetime.now(timezone.utc)
        record.active_count = max(0, int(active_count))
        record.cpu_millicores_used = max(0, int(cpu_used))
        record.memory_mb_used = max(0, int(memory_used))
        if state:
            if not is_valid_worker_transition(record.state, state):
                raise InvalidWorkerTransition(f"{record.state} -> {state} not allowed")
            record.state = state
        elif record.state in (WorkerState.STARTING, WorkerState.UNHEALTHY):
            record.state = WorkerState.READY if record.active_count == 0 else WorkerState.BUSY
        elif record.state == WorkerState.READY and record.active_count > 0:
            record.state = WorkerState.BUSY
        elif record.state == WorkerState.BUSY and record.active_count == 0:
            record.state = WorkerState.READY
        return record

    def sweep_stale_heartbeats(self, now: Optional[datetime] = None) -> list[str]:
        """Mark heartbeat-expired workers UNHEALTHY; returns affected ids."""
        moment = now or datetime.now(timezone.utc)
        affected = []
        for record in self._workers.values():
            if record.state in (WorkerState.OFFLINE, WorkerState.TERMINATED,
                                WorkerState.DRAINING):
                continue
            if record.heartbeat_stale(self.heartbeat_ttl_seconds, moment):
                if is_valid_worker_transition(record.state, WorkerState.UNHEALTHY):
                    record.state = WorkerState.UNHEALTHY
                    affected.append(record.worker_id)
        return affected

    def drain(self, worker_id: str) -> WorkerRecord:
        """Graceful drain: stop accepting new work (§44)."""
        return self.transition(worker_id, WorkerState.DRAINING)

    def offline(self, worker_id: str) -> WorkerRecord:
        record = self.get(worker_id)
        for target in (WorkerState.DRAINING, WorkerState.OFFLINE):
            if is_valid_worker_transition(record.state, target):
                record.state = target
        if record.state != WorkerState.OFFLINE:
            # Force path for crash cleanup (registry-level, audited by callers).
            record.state = WorkerState.OFFLINE
        return record

    # ------------------------------------------------------------ queries ---
    def list(self, *, region_id: str = "", pool_id: str = "",
             state: str = "") -> list[WorkerRecord]:
        records = list(self._workers.values())
        if region_id:
            records = [r for r in records if r.region_id == region_id]
        if pool_id:
            records = [r for r in records if r.pool_id == pool_id]
        if state:
            records = [r for r in records if r.state == state]
        return sorted(records, key=lambda r: r.worker_id)

    def schedulable_adverts(self) -> list[WorkerAdvert]:
        return [r.advert() for r in self._workers.values()
                if r.state in (WorkerState.READY, WorkerState.BUSY)]

    def utilization(self) -> dict[str, Any]:
        total = len(self._workers)
        busy = sum(1 for r in self._workers.values() if r.state == WorkerState.BUSY)
        ready = sum(1 for r in self._workers.values() if r.state == WorkerState.READY)
        return {"workers": total, "busy": busy, "ready": ready,
                "utilization": (busy / total) if total else 0.0}
