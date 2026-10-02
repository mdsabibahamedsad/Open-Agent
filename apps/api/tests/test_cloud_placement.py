"""MP25 unit: placement (residency, failover, capability) + autoscaler +
schedule dedup."""

import pytest
from datetime import datetime, timedelta, timezone

from openagent.cloud.errors import PlacementFailed
from openagent.cloud.placement import (
    ExecutionPlacementEngine, PlacementRequest, Region, RegionRegistry,
    WorkerAdvert, region_satisfies_residency,
)
from openagent.cloud.scheduling import (
    AutoscaleInput, decide_autoscale, dedup_key, is_misfire,
)


def _regions():
    return RegionRegistry([
        Region(id="eu-1", name="EU", capabilities=["exec", "browser"],
               residency_tags=["EU"], cost_weight=1.0),
        Region(id="us-1", name="US", capabilities=["exec"],
               residency_tags=["US"], cost_weight=2.0),
    ])


def _workers():
    return [
        WorkerAdvert(worker_id="w-eu", region_id="eu-1", pool_id="default",
                     capabilities=["exec", "browser"], max_concurrency=4),
        WorkerAdvert(worker_id="w-us", region_id="us-1", pool_id="default",
                     capabilities=["exec"], max_concurrency=4),
    ]


def test_residency_policy():
    registry = _regions()
    eu = registry.get("eu-1")
    assert eu is not None
    assert region_satisfies_residency(eu, "EU_ONLY")
    assert not region_satisfies_residency(eu, "US_ONLY")
    assert region_satisfies_residency(eu, "ANY_REGION")
    assert not region_satisfies_residency(eu, "ORG_SELECTED", ["us-1"])


def test_placement_honors_residency():
    engine = ExecutionPlacementEngine(_regions())
    decision = engine.place(
        PlacementRequest(organization_id="org-1", execution_class="workflow",
                         residency="EU_ONLY"),
        _workers())
    assert decision.region_id == "eu-1"


def test_placement_failover_never_violates_residency():
    engine = ExecutionPlacementEngine(_regions())
    # Only EU satisfies residency; US-only workers cannot be used.
    with pytest.raises(PlacementFailed):
        engine.place(
            PlacementRequest(organization_id="org-1", execution_class="browser",
                             residency="US_ONLY", needs_browser=True),
            [WorkerAdvert(worker_id="w-eu", region_id="eu-1", pool_id="default",
                          capabilities=["exec", "browser"], max_concurrency=4)])


def test_placement_rejects_without_capacity():
    engine = ExecutionPlacementEngine(_regions())
    with pytest.raises(PlacementFailed):
        engine.place(
            PlacementRequest(organization_id="org-1", execution_class="workflow"),
            [])


def test_autoscaler_scales_up_on_pressure():
    decision = decide_autoscale(AutoscaleInput(
        queue="workflow.default", queue_depth=100, oldest_age_seconds=120,
        worker_count=2, avg_utilization=0.9, min_workers=1, max_workers=10))
    assert decision.action == "scale_up"
    assert decision.desired_workers > 2


def test_autoscaler_respects_max_and_quota():
    capped = decide_autoscale(AutoscaleInput(
        queue="q", queue_depth=10000, oldest_age_seconds=999,
        worker_count=10, avg_utilization=1.0, min_workers=1, max_workers=10))
    assert capped.desired_workers <= 10
    idle = decide_autoscale(AutoscaleInput(
        queue="q", queue_depth=0, oldest_age_seconds=0.0,
        worker_count=5, avg_utilization=0.05, min_workers=2, max_workers=10))
    assert idle.action == "scale_down"
    cooldown = decide_autoscale(AutoscaleInput(
        queue="q", queue_depth=100, oldest_age_seconds=120,
        worker_count=2, avg_utilization=0.9, cooldown_remaining_seconds=60.0))
    assert cooldown.action == "hold"


def test_schedule_dedup_key_stable():
    moment = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
    assert dedup_key("sch_1", moment) == dedup_key("sch_1", moment)
    assert dedup_key("sch_1", moment) != dedup_key("sch_2", moment)
    assert dedup_key("sch_1", moment) != dedup_key(
        "sch_1", moment + timedelta(minutes=5))
    assert is_misfire(moment, moment + timedelta(seconds=600), 300)
    assert not is_misfire(moment, moment + timedelta(seconds=60), 300)
