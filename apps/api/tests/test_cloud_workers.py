"""MP25 unit: worker registry lifecycle, heartbeats, draining."""

from datetime import datetime, timedelta, timezone

import pytest

from openagent.cloud.errors import InvalidWorkerTransition, WorkerNotFound
from openagent.cloud.workers import WorkerRecord, WorkerRegistry


def _record(worker_id="worker-1"):
    return WorkerRecord(worker_id=worker_id, service_identity=f"svc:{worker_id}",
                        region_id="local-1", pool_id="default",
                        capabilities=["exec"], version="0.1.0")


def test_register_requires_capabilities():
    registry = WorkerRegistry()
    with pytest.raises(ValueError):
        registry.register(WorkerRecord(worker_id="w", service_identity="svc:w",
                                       region_id="r", pool_id="p", capabilities=[]))


def test_register_starts_worker():
    registry = WorkerRegistry()
    record = registry.register(_record())
    assert record.state == "STARTING"
    registry.heartbeat("worker-1", active_count=0, cpu_used=0, memory_used=0,
                       state="READY")
    assert registry.get("worker-1").state == "READY"


def test_heartbeat_expiry_marks_unhealthy():
    registry = WorkerRegistry(heartbeat_ttl_seconds=30)
    registry.register(_record())
    record = registry.get("worker-1")
    record.state = "READY"
    record.last_heartbeat_at = datetime.now(timezone.utc) - timedelta(seconds=120)
    affected = registry.sweep_stale_heartbeats()
    assert affected == ["worker-1"]
    assert registry.get("worker-1").state == "UNHEALTHY"


def test_drain_flow():
    registry = WorkerRegistry()
    registry.register(_record())
    registry.heartbeat("worker-1", active_count=0, cpu_used=0, memory_used=0, state="READY")
    registry.drain("worker-1")
    assert registry.get("worker-1").state == "DRAINING"
    # Draining workers are not schedulable.
    assert registry.schedulable_adverts() == []
    registry.transition("worker-1", "OFFLINE")
    assert registry.get("worker-1").state == "OFFLINE"


def test_unknown_worker_rejected():
    registry = WorkerRegistry()
    with pytest.raises(WorkerNotFound):
        registry.get("ghost")


def test_invalid_transition_rejected():
    registry = WorkerRegistry()
    registry.register(_record())
    with pytest.raises(InvalidWorkerTransition):
        registry.transition("worker-1", "BUSY")  # REGISTERING->BUSY skips STARTING
