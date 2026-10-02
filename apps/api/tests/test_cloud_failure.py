"""MP25 failure injection: worker crash, duplicate delivery, lease
expiry, queue crash (depth loss), region outage, partial execution."""

import pytest

from openagent.cloud.config import CloudSettings
from openagent.cloud.dispatcher import DispatchContext
from openagent.cloud.placement import Region, RegionRegistry
from openagent.cloud.queues import InMemoryQueueProvider
from openagent.cloud.runtime import ExecutionRequest
from openagent.cloud.service import CloudRuntimeService, reset_cloud_service
from openagent.cloud.types import ExecutionState


def _service(queues=None, regions=None) -> CloudRuntimeService:
    reset_cloud_service()
    return CloudRuntimeService(
        settings=CloudSettings(OPENAGENT_CLOUD_ENABLED=True,
                               OPENAGENT_RUNTIME_MODE="cloud"),
        queue_provider=queues or InMemoryQueueProvider(),
        regions=regions or RegionRegistry(
            [Region(id="local-1", name="local-1")]))


@pytest.mark.asyncio
async def test_worker_crash_recovers_via_visibility_expiry():
    queues = InMemoryQueueProvider()
    service = _service(queues=queues)
    handle = await service.submit(ExecutionRequest(organization_id="org-1"))
    claimed = await queues.claim(handle.queue, "worker-A", visibility_seconds=0)
    assert claimed is not None  # worker A crashes before ack
    recovered = await queues.claim(handle.queue, "worker-B", visibility_seconds=60)
    assert recovered is not None
    assert recovered.execution_id == handle.execution_id
    await queues.ack(handle.queue, recovered.message_id, "worker-B")


@pytest.mark.asyncio
async def test_duplicate_transition_delivery_is_idempotent():
    service = _service()
    handle = await service.submit(ExecutionRequest(organization_id="org-1"))
    await service.dispatcher.transition(handle.execution_id, "org-1",
                                        "DISPATCHING", worker_id="w-1")
    # Redelivered DISPATCHING (same state) is accepted, not an error.
    view = await service.dispatcher.transition(handle.execution_id, "org-1",
                                               "DISPATCHING", worker_id="w-1")
    assert view.status == ExecutionState.DISPATCHING


@pytest.mark.asyncio
async def test_expired_lease_allows_takeover():
    from openagent.cloud.leases import InMemoryLeaseBackend
    backend = InMemoryLeaseBackend()
    lease = await backend.acquire("execution:cexe_x", "worker-old", 1)
    record = await backend.get("execution:cexe_x")
    assert record is not None
    from datetime import datetime, timezone
    record.expires_at = datetime.now(timezone.utc)  # crash: never renewed
    takeover = await backend.acquire("execution:cexe_x", "worker-new", 300)
    assert takeover.owner_id == "worker-new"


@pytest.mark.asyncio
async def test_region_outage_fails_over_within_residency():
    from openagent.cloud.placement import (
        ExecutionPlacementEngine, PlacementRequest, WorkerAdvert)
    registry = RegionRegistry([
        Region(id="eu-1", name="EU", capabilities=["exec"],
               residency_tags=["EU"], cost_weight=1.0),
        Region(id="eu-2", name="EU2", capabilities=["exec"],
               residency_tags=["EU"], cost_weight=1.5),
    ])
    registry.set_status("eu-1", "OFFLINE")  # outage
    engine = ExecutionPlacementEngine(registry)
    decision = engine.place(
        PlacementRequest(organization_id="org-1", execution_class="workflow",
                         residency="EU_ONLY", region_hint="eu-1"),
        [WorkerAdvert(worker_id="w2", region_id="eu-2", pool_id="default",
                      capabilities=["exec"])])
    assert decision.region_id == "eu-2"
    assert decision.failover_from == "eu-1"


@pytest.mark.asyncio
async def test_partial_execution_can_retry_from_failed():
    service = _service()
    handle = await service.submit(ExecutionRequest(organization_id="org-1"))
    d = service.dispatcher
    await d.transition(handle.execution_id, "org-1", "DISPATCHING", worker_id="w-1")
    await d.transition(handle.execution_id, "org-1", "STARTING", worker_id="w-1")
    await d.transition(handle.execution_id, "org-1", "RUNNING", worker_id="w-1")
    await d.transition(handle.execution_id, "org-1", "FAILED", worker_id="w-1")
    retried = await d.retry(handle.execution_id, "org-1")
    assert retried.status == ExecutionState.QUEUED
