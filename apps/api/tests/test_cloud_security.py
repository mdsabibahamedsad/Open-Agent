"""MP25 security: tenant isolation, worker identity, artifact auth,
quota bypass resistance, region-policy bypass resistance."""

import pytest

from openagent.cloud.artifacts import (
    sign_download_token, verify_download_token,
)
from openagent.cloud.dispatcher import DispatchContext
from openagent.cloud.errors import EntitlementDenied, QuotaExceeded
from openagent.cloud.ops import QuotaCheck
from openagent.cloud.placement import Region, RegionRegistry
from openagent.cloud.queues import InMemoryQueueProvider
from openagent.cloud.runtime import ExecutionRequest
from openagent.cloud.config import CloudSettings
from openagent.cloud.service import CloudRuntimeService, reset_cloud_service


def _service() -> CloudRuntimeService:
    reset_cloud_service()
    return CloudRuntimeService(
        settings=CloudSettings(OPENAGENT_CLOUD_ENABLED=True,
                               OPENAGENT_RUNTIME_MODE="cloud"),
        queue_provider=InMemoryQueueProvider(),
        regions=RegionRegistry([Region(id="local-1", name="local-1")]))


@pytest.mark.asyncio
async def test_org_a_cannot_touch_org_b_execution_or_artifact():
    service = _service()
    handle = await service.submit(ExecutionRequest(organization_id="org-A"))
    with pytest.raises(PermissionError):
        await service.dispatcher.describe(handle.execution_id, "org-B")
    # Signed artifact URLs are tenant-bound too.
    token = sign_download_token(artifact_id="art_1", organization_id="org-A",
                                secret="s", expires_at=__import__(
                                    "openagent.cloud.artifacts",
                                    fromlist=["default_expiry"]).default_expiry(3600))
    assert verify_download_token(token, artifact_id="art_1",
                                 organization_id="org-A", secret="s")
    assert not verify_download_token(token, artifact_id="art_1",
                                     organization_id="org-B", secret="s")


@pytest.mark.asyncio
async def test_suspended_entitlement_denies_execution():
    service = _service()
    ctx = DispatchContext(
        organization_id="org-1",
        entitlements=[{"status": "SUSPENDED", "features": ["cloud.execute"]}])
    with pytest.raises(EntitlementDenied):
        await service.dispatcher.dispatch(
            ExecutionRequest(organization_id="org-1"), ctx)


@pytest.mark.asyncio
async def test_quota_cannot_be_bypassed_with_priority():
    service = _service()
    ctx = DispatchContext(
        organization_id="org-1",
        quotas=[QuotaCheck(dimension="monthly_executions", limit=1,
                           used=1, requested=1)],
        plan_allows_high=True, plan_allows_critical=True)
    with pytest.raises(QuotaExceeded):
        await service.dispatcher.dispatch(
            ExecutionRequest(organization_id="org-1", priority="CRITICAL"), ctx)


@pytest.mark.asyncio
async def test_region_policy_bypass_rejected():
    from openagent.cloud.errors import PlacementFailed
    from openagent.cloud.placement import (
        ExecutionPlacementEngine, PlacementRequest, WorkerAdvert)
    registry = RegionRegistry([Region(id="eu-1", name="EU",
                                        capabilities=["exec"],
                                        residency_tags=["EU"])])
    engine = ExecutionPlacementEngine(registry)
    with pytest.raises(PlacementFailed):
        engine.place(
            PlacementRequest(organization_id="org-1",
                             execution_class="workflow",
                             residency="EU_ONLY"),
            [WorkerAdvert(worker_id="w", region_id="us-1", pool_id="default",
                          capabilities=["exec"])])


@pytest.mark.asyncio
async def test_worker_identity_mismatch_rejected_at_transition():
    from openagent.cloud.errors import InvalidExecutionTransition
    service = _service()
    handle = await service.submit(ExecutionRequest(organization_id="org-1"))
    await service.dispatcher.transition(handle.execution_id, "org-1",
                                        "DISPATCHING", worker_id="worker-legit")
    with pytest.raises(InvalidExecutionTransition):
        await service.dispatcher.transition(handle.execution_id, "org-1",
                                            "STARTING", worker_id="worker-impostor")


def test_cloud_disabled_by_default():
    from openagent.cloud.errors import CloudDisabled
    reset_cloud_service()
    service = CloudRuntimeService(
        settings=CloudSettings(),  # defaults: disabled
        queue_provider=InMemoryQueueProvider(),
        regions=RegionRegistry([Region(id="local-1", name="local-1")]))
    with pytest.raises(CloudDisabled):
        service.require_enabled()
