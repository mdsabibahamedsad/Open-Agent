"""MP25 integration: dispatcher (idempotency, quotas, incident gate) +
tenant isolation + worker ownership + usage staging. Uses fakes only."""

import pytest

from openagent.cloud.config import CloudSettings
from openagent.cloud.dispatcher import DispatchContext
from openagent.cloud.errors import (
    IncidentBlocked, InvalidExecutionTransition, QuotaExceeded,
)
from openagent.cloud.events import EventStore
from openagent.cloud.ops import QuotaCheck, detect_orphans
from openagent.cloud.placement import Region, RegionRegistry
from openagent.cloud.queues import InMemoryQueueProvider
from openagent.cloud.runtime import ExecutionRequest
from openagent.cloud.service import CloudRuntimeService, reset_cloud_service


def _service(**overrides) -> CloudRuntimeService:
    reset_cloud_service()
    settings = CloudSettings(OPENAGENT_CLOUD_ENABLED=True,
                             OPENAGENT_RUNTIME_MODE="cloud",
                             **overrides)
    return CloudRuntimeService(
        settings=settings,
        queue_provider=InMemoryQueueProvider(),
        regions=RegionRegistry([Region(id="local-1", name="local-1")]))


def _request(org="org-1", **overrides):
    base = dict(organization_id=org, execution_class="workflow")
    base.update(overrides)
    return ExecutionRequest(**base)


@pytest.mark.asyncio
async def test_submit_returns_queued_handle():
    service = _service()
    handle = await service.submit(_request())
    assert handle.status == "QUEUED"
    assert handle.queue == "workflow.default"


@pytest.mark.asyncio
async def test_idempotent_submit_returns_same_execution():
    service = _service()
    first = await service.submit(_request(), DispatchContext(organization_id="org-1"))
    req = _request()
    req.idempotency_key = "key-123"
    one = await service.dispatcher.dispatch(req, DispatchContext(organization_id="org-1"))
    two = await service.dispatcher.dispatch(req, DispatchContext(organization_id="org-1"))
    assert one.execution_id == two.execution_id


@pytest.mark.asyncio
async def test_cross_tenant_access_denied():
    service = _service()
    handle = await service.submit(_request(org="org-A"))
    with pytest.raises(PermissionError):
        await service.dispatcher.describe(handle.execution_id, "org-B")
    with pytest.raises(PermissionError):
        await service.dispatcher.cancel(handle.execution_id, "org-B")


@pytest.mark.asyncio
async def test_worker_cannot_move_unowned_execution():
    service = _service()
    handle = await service.submit(_request())
    # Claim by worker-1 (ownership recorded on first transition).
    await service.dispatcher.transition(handle.execution_id, "org-1",
                                        "DISPATCHING", worker_id="worker-1")
    with pytest.raises(InvalidExecutionTransition):
        await service.dispatcher.transition(handle.execution_id, "org-1",
                                            "STARTING", worker_id="worker-2")


@pytest.mark.asyncio
async def test_quota_enforcement_blocks_submit():
    service = _service()
    ctx = DispatchContext(
        organization_id="org-1",
        quotas=[QuotaCheck(dimension="concurrent_executions", limit=0,
                           used=0, requested=1)])
    with pytest.raises(QuotaExceeded):
        await service.dispatcher.dispatch(_request(), ctx)


@pytest.mark.asyncio
async def test_incident_mode_blocks_new_executions():
    service = _service(CLOUD_INCIDENT_MODE="EMERGENCY")
    with pytest.raises(IncidentBlocked):
        await service.submit(_request())


@pytest.mark.asyncio
async def test_cancel_and_retry_lifecycle():
    service = _service()
    handle = await service.submit(_request())
    cancelled = await service.dispatcher.cancel(handle.execution_id, "org-1")
    assert cancelled.status == "CANCELLED"
    # Terminal CANCELLED cannot retry.
    with pytest.raises(ValueError):
        await service.dispatcher.retry(handle.execution_id, "org-1")


@pytest.mark.asyncio
async def test_event_stream_redacts_secrets():
    service = _service()
    handle = await service.submit(_request())
    assert isinstance(service.events, EventStore)
    await service.events.append(handle.execution_id, "agent.message",
                                {"text": "key sk-live-SECRETVALUE123456",
                                 "api_key": "should-not-leak"})
    events = await service.events.list(handle.execution_id)
    payload = events[-1].to_dict()["payload"]
    assert "should-not-leak" not in str(payload)
    assert "[REDACTED]" in str(payload)
    assert "SECRETVALUE" not in str(payload)


def test_usage_records_map_to_commerce_meters():
    service = _service()
    records = service.usage_records(organization_id="org-1",
                                    execution_id="cexe_1",
                                    usage={"worker_seconds": 12.5,
                                           "bogus": -3, "execution_count": 1})
    meters = {r["meter"] for r in records}
    assert "worker_seconds" in meters and "execution_count" in meters
    assert all(r["dedup_key"].startswith("cloud:cexe_1:") for r in records)


def test_orphan_detection_classifies_without_deleting():
    reports = detect_orphans(
        execution_ids={"cexe_live"},
        worker_claims={"cexe_ghost": "worker-1"},
        artifact_execution_ids={"art_1": "cexe_gone"},
        sandbox_tasks={"sbx_1": "task-gone"},
        live_tasks={"task-live"},
        worker_last_seen={},
        heartbeat_ttl_seconds=90,
        queue_execution_ids={"cexe_queued_ghost"})
    kinds = {r.kind for r in reports}
    assert "execution_without_worker" in kinds
    assert "artifact_without_execution" in kinds
    assert "sandbox_without_task" in kinds
    assert "queue_message_without_execution" in kinds
    assert all(r.action == "detect" for r in reports)
