"""MP25: region model + registry (§25-26) and placement engine (§24, §27-28).

Regions are data, never hard-coded provider names. The placement engine
scores candidate workers/regions by capability, residency, quota, queue
pressure, cost and availability, and always respects organization policy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from openagent.cloud.errors import PlacementFailed, RegionNotAvailable
from openagent.cloud.types import DataResidency, ExecutionPriority, RegionStatus


@dataclass
class Region:
    id: str
    name: str
    status: str = RegionStatus.ACTIVE
    capabilities: list[str] = field(default_factory=list)
    residency_tags: list[str] = field(default_factory=list)
    cost_weight: float = 1.0
    max_workers: int = 100
    metadata: dict[str, Any] = field(default_factory=dict)

    def schedulable(self) -> bool:
        return self.status in (RegionStatus.ACTIVE, RegionStatus.DEGRADED)


@dataclass
class WorkerAdvert:
    worker_id: str
    region_id: str
    pool_id: str
    capabilities: list[str]
    max_concurrency: int = 4
    active_count: int = 0
    cpu_millicores_total: int = 2000
    cpu_millicores_used: int = 0
    memory_mb_total: int = 4096
    memory_mb_used: int = 0
    supports_gpu: bool = False
    version: str = "0.1.0"
    draining: bool = False

    def has_capacity(self) -> bool:
        if self.draining:
            return False
        return self.active_count < self.max_concurrency

    def fits(self, cpu_millicores: int, memory_mb: int, needs_gpu: bool) -> bool:
        if needs_gpu and not self.supports_gpu:
            return False
        if self.cpu_millicores_used + cpu_millicores > self.cpu_millicores_total:
            return False
        if self.memory_mb_used + memory_mb > self.memory_mb_total:
            return False
        return True


def region_satisfies_residency(region: Region, residency: str,
                               org_regions: Optional[list[str]] = None) -> bool:
    policy = str(residency or DataResidency.ANY_REGION).upper()
    if policy == DataResidency.ANY_REGION:
        return True
    if policy == DataResidency.ORG_SELECTED:
        return bool(org_regions) and region.id in org_regions
    if policy == DataResidency.PRIVATE_REGION:
        return "private" in region.capabilities
    tag_map = {
        DataResidency.EU_ONLY: "EU",
        DataResidency.US_ONLY: "US",
        DataResidency.APAC_ONLY: "APAC",
    }
    tag = tag_map.get(policy)
    if tag is None:
        return True
    return tag in region.residency_tags


class RegionRegistry:
    """In-process region catalogue (DB-backed regions persist separately)."""

    def __init__(self, regions: Optional[list[Region]] = None) -> None:
        self._regions: dict[str, Region] = {r.id: r for r in (regions or [])}

    def register(self, region: Region) -> None:
        self._regions[region.id] = region

    def get(self, region_id: str) -> Optional[Region]:
        return self._regions.get(region_id)

    def list(self, *, schedulable_only: bool = False) -> list[Region]:
        regions = list(self._regions.values())
        if schedulable_only:
            regions = [r for r in regions if r.schedulable()]
        return sorted(regions, key=lambda r: r.id)

    def set_status(self, region_id: str, status: str) -> Region:
        region = self._regions.get(region_id)
        if region is None:
            raise RegionNotAvailable(f"unknown region {region_id}")
        if status not in RegionStatus.ALL:
            raise ValueError(f"unknown region status {status}")
        region.status = status
        return region


@dataclass
class PlacementRequest:
    organization_id: str
    execution_class: str
    priority: str = ExecutionPriority.NORMAL
    region_hint: str = ""
    pool_id: str = "default"
    residency: str = DataResidency.ANY_REGION
    org_regions: list[str] = field(default_factory=list)
    cpu_millicores: int = 500
    memory_mb: int = 512
    needs_gpu: bool = False
    needs_browser: bool = False
    queue_depths: dict[str, int] = field(default_factory=dict)
    failover_allowed: bool = True


@dataclass
class PlacementDecision:
    region_id: str
    pool_id: str
    queue: str
    worker_id: str = ""
    reason: str = ""
    failover_from: str = ""


class ExecutionPlacementEngine:
    """Score-based placement (§24) honoring residency + policy (§27-28)."""

    def __init__(self, regions: RegionRegistry) -> None:
        self.regions = regions

    def _required_capability(self, request: PlacementRequest) -> str:
        if request.needs_browser:
            return "browser"
        if request.execution_class == "browser":
            return "browser"
        if request.execution_class == "code":
            return "code"
        if request.needs_gpu:
            return "gpu"
        return "exec"

    def place(self, request: PlacementRequest,
              workers: list[WorkerAdvert],
              primary_region: str = "") -> PlacementDecision:
        from openagent.cloud.queues import route_queue
        capability = self._required_capability(request)
        candidates: list[tuple[float, WorkerAdvert, Region]] = []

        ordered_regions = self._region_order(request, primary_region)
        for region in ordered_regions:
            if not region_satisfies_residency(region, request.residency, request.org_regions):
                continue
            for worker in workers:
                if worker.region_id != region.id:
                    continue
                if not worker.has_capacity():
                    continue
                if not worker.fits(request.cpu_millicores, request.memory_mb, request.needs_gpu):
                    continue
                if capability not in worker.capabilities and "exec" not in worker.capabilities and capability != "exec":
                    if capability not in worker.capabilities:
                        continue
                if request.pool_id not in ("", "default") and worker.pool_id != request.pool_id:
                    continue
                score = self._score(worker, region, request)
                candidates.append((score, worker, region))

        if not candidates:
            raise PlacementFailed("no compatible worker capacity for placement request")

        candidates.sort(key=lambda item: item[0])
        _, worker, region = candidates[0]
        queue = route_queue(execution_class=request.execution_class,
                            priority=request.priority,
                            memory_mb=request.memory_mb,
                            cpu_millicores=request.cpu_millicores,
                            pool_id=worker.pool_id)
        pinned = primary_region or request.region_hint
        failover = ""
        if pinned and region.id != pinned:
            failover = pinned
        return PlacementDecision(region_id=region.id, pool_id=worker.pool_id,
                                 queue=queue, worker_id=worker.worker_id,
                                 reason=f"capability={capability} score=best",
                                 failover_from=failover)

    def _region_order(self, request: PlacementRequest, primary_region: str) -> list[Region]:
        regions = [r for r in self.regions.list(schedulable_only=True)]
        if request.region_hint:
            regions.sort(key=lambda r: (0 if r.id == request.region_hint else 1, r.cost_weight))
        elif primary_region:
            regions.sort(key=lambda r: (0 if r.id == primary_region else 1, r.cost_weight))
        else:
            regions.sort(key=lambda r: r.cost_weight)
        if not request.failover_allowed and (request.region_hint or primary_region):
            pinned = request.region_hint or primary_region
            regions = [r for r in regions if r.id == pinned]
        # Residency-violating failover is never allowed: filter happens in place().
        return regions

    def _score(self, worker: WorkerAdvert, region: Region, request: PlacementRequest) -> float:
        load = worker.active_count / max(1, worker.max_concurrency)
        mem_pressure = worker.memory_mb_used / max(1, worker.memory_mb_total)
        queue_pressure = 0.0
        from openagent.cloud.queues import route_queue
        q = route_queue(execution_class=request.execution_class,
                        priority=request.priority, memory_mb=request.memory_mb,
                        cpu_millicores=request.cpu_millicores, pool_id=worker.pool_id)
        depth = request.queue_depths.get(q, 0)
        queue_pressure = min(1.0, depth / 1000.0)
        degraded = 0.5 if region.status == RegionStatus.DEGRADED else 0.0
        priority_boost = -0.2 if request.priority in ("HIGH", "CRITICAL") and load < 0.8 else 0.0
        return load * 2.0 + mem_pressure + queue_pressure + region.cost_weight * 0.1 + degraded + priority_boost
