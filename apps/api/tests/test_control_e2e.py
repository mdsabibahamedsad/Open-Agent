"""MP26 failure + E2E: observability outages never break execution;
control restart is clean; full org->incident->resolution flow on fakes."""

import pytest

from openagent.cloud.config import CloudSettings
from openagent.cloud.placement import Region, RegionRegistry
from openagent.cloud.queues import InMemoryQueueProvider
from openagent.cloud.runtime import ExecutionRequest
from openagent.cloud.service import CloudRuntimeService, reset_cloud_service
from openagent.control.configuration import ConfigEntry
from openagent.control.feature_flags import FeatureFlag
from openagent.control.observability import Telemetry
from openagent.control.policies import PolicyDecision, PolicyResolver
from openagent.control.reliability import (
    AlertEngine, AlertRule, Incident, MemoryController,
)
from openagent.control.resources import ResourceRef, hierarchy_for
from openagent.control.service import ControlPlaneService, reset_control_service


def _cloud() -> CloudRuntimeService:
    reset_cloud_service()
    return CloudRuntimeService(
        settings=CloudSettings(OPENAGENT_CLOUD_ENABLED=True,
                               OPENAGENT_RUNTIME_MODE="cloud"),
        queue_provider=InMemoryQueueProvider(),
        regions=RegionRegistry([Region(id="local-1", name="local-1")]))


def test_metrics_outage_does_not_break_dispatch():
    telemetry = Telemetry()
    telemetry.disabled = True  # metrics backend down
    telemetry.counter("dispatch.count")  # must not raise
    assert telemetry.snapshot() == {"counters": {},
                                    "gauges": {}, "observations": {}}


@pytest.mark.asyncio
async def test_execution_survives_observability_outage():
    service = _cloud()
    service.events = None  # event persistence down
    handle = await service.submit(ExecutionRequest(organization_id="org-1"))
    assert handle.status == "QUEUED"
    view = await service.dispatcher.describe(handle.execution_id, "org-1")
    assert view.execution_id == handle.execution_id


@pytest.mark.asyncio
async def test_alerting_failure_does_not_break_execution():
    from openagent.control.reliability import LogNotifier, Alert
    notifier = LogNotifier()
    alert = Alert(rule_id="r1", severity="CRITICAL", source="q")
    ok, _ = await notifier.send(alert, "webhook:https://example.invalid/hook")
    assert ok  # recorded locally; execution path unaffected
    service = _cloud()
    handle = await service.submit(ExecutionRequest(organization_id="org-1"))
    assert handle.status == "QUEUED"


def test_control_plane_restart_is_clean():
    reset_control_service()
    from openagent.control.service import get_control_service
    first = get_control_service()
    first.set_config(ConfigEntry(scope="PLATFORM", scope_id="",
                                 category="runtime", key="k", value=1))
    reset_control_service()  # simulated restart
    second = get_control_service()
    assert second.resolved_config() == {}  # no phantom state
    assert second.audit.verify()[0]


def test_reconciliation_repairs_drift():
    controller = MemoryController("worker_pool", {"desired": 4})
    controller.run_once()
    controller._have["desired"] = 1  # drift (crashed scale-down)
    result = controller.run_once()
    assert result["verified"] and controller._have["desired"] == 4


@pytest.mark.asyncio
async def test_e2e_org_to_resolution_on_fakes():
    # Organization -> Project -> Environment -> Workflow -> Execution ->
    # Worker -> Telemetry -> Incident -> Resolution.
    reset_control_service()
    from openagent.control.service import get_control_service
    control = get_control_service()
    control.policies = PolicyResolver([
        ("membership", lambda ctx: PolicyDecision.allow("member")),
        ("env", lambda ctx: PolicyDecision.allow("env matches")),
    ])
    assert control.policies.decide({}).allowed

    resource = ResourceRef(id="exe_e2e", type="execution",
                           organization_id="org-e2e", project_id="proj-e2e",
                           environment="PRODUCTION")
    assert hierarchy_for(resource).environment == "PRODUCTION"

    cloud = _cloud()
    handle = await cloud.submit(ExecutionRequest(
        organization_id="org-e2e", execution_class="workflow",
        environment="PRODUCTION"))
    assert handle.status == "QUEUED"

    control.telemetry.counter("workflow.execution.count")
    control.telemetry.gauge("queue.depth", 1)
    assert control.telemetry.snapshot()["counters"]

    engine = AlertEngine()
    rule = AlertRule(rule_id="queue-watch", metric="queue.depth",
                     condition="gt", threshold=0, severity="WARNING")
    alert = engine.evaluate(rule, 1, source="workflow.default")
    assert alert is not None

    incident = Incident(title="e2e queue pressure", severity="WARNING")
    assert incident.transition("ACKNOWLEDGED", "e2e")[0]
    assert incident.transition("INVESTIGATING", "e2e")[0]
    assert incident.transition("MITIGATING", "e2e", "scaled +2")[0]
    assert incident.transition("MONITORING", "e2e")[0]
    assert incident.transition("RESOLVED", "e2e", "queue drained")[0]
    assert incident.transition("CLOSED", "e2e")[0]
    assert len(incident.timeline) >= 6

    control.flags.add(FeatureFlag(key="ui.ops", scope="PLATFORM",
                                  strategy="boolean", enabled=True))
    assert control.flags.evaluate("ui.ops").allowed
