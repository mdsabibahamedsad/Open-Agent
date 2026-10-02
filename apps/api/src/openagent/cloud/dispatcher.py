"""MP25: execution dispatcher (§6) + entitlement/quota enforcement (§39-40).

Pipeline per request::

    Authenticate -> Authorize -> Entitlement -> Quota -> Resource limits
    -> Incident gate -> Placement -> Queue select -> Enqueue -> handle

Post-dispatch, workers enforce live limits and finalize usage into the
existing commerce billing path (no second billing system).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Optional

from openagent.cloud.errors import (
    EntitlementDenied, IncidentBlocked, PlacementFailed, QuotaExceeded,
)
from openagent.cloud.ops import (
    QuotaCheck, check_budget, evaluate_quotas, incident_allows_submit,
)
from openagent.cloud.placement import (
    ExecutionPlacementEngine, PlacementDecision, PlacementRequest,
    RegionRegistry,
)
from openagent.cloud.queues import CloudMessage, normalize_priority, route_queue
from openagent.cloud.runtime import ExecutionHandle, ExecutionRequest, ExecutionView
from openagent.cloud.types import (
    DataResidency, ExecutionPriority, ExecutionState,
    is_valid_execution_transition,
)


def new_execution_id() -> str:
    return f"cexe_{uuid.uuid4().hex[:16]}"


@dataclass
class DispatchContext:
    organization_id: str
    entitlements: list[dict[str, Any]] = field(default_factory=list)
    quotas: list[QuotaCheck] = field(default_factory=list)
    plan_allows_high: bool = False
    plan_allows_critical: bool = False
    org_regions: list[str] = field(default_factory=list)
    residency: str = DataResidency.ANY_REGION
    queue_depths: dict[str, int] = field(default_factory=dict)
    incident_mode: str = "NORMAL"


class ExecutionDispatcher:
    """Control-plane dispatcher. Pure logic + injected collaborators."""

    def __init__(self, *, regions: RegionRegistry,
                 queue_provider,
                 event_store=None,
                 idempotency_store=None,
                 global_max_queue_depth: int = 100000) -> None:
        self.regions = regions
        self.placement = ExecutionPlacementEngine(regions)
        self.queues = queue_provider
        self.events = event_store
        self.idempotency = idempotency_store
        self.global_max_queue_depth = global_max_queue_depth
        # In-memory execution index; the service layer persists to Postgres.
        self._executions: dict[str, dict[str, Any]] = {}

    # --------------------------------------------------------------- submit ---
    async def dispatch(self, request: ExecutionRequest,
                       ctx: Optional[DispatchContext] = None) -> ExecutionHandle:
        ctx = ctx or DispatchContext(organization_id=request.organization_id)
        self._require_org_match(request, ctx)

        # Idempotency-Key: repeated submits return the original handle.
        if request.idempotency_key and self.idempotency is not None:
            existing = await self.idempotency.lookup(
                request.organization_id, request.idempotency_key)
            if existing is not None:
                return existing

        # Incident gate (§78): emergency/maintenance stop new executions
        # without silently cancelling existing work.
        allowed, reason = incident_allows_submit(ctx.incident_mode)
        if not allowed:
            raise IncidentBlocked(reason)

        # Entitlement: cloud execution is a commercial capability.
        self._require_entitlement(ctx)

        # Quota (server-side, §40).
        if ctx.quotas:
            ok, why, _ = evaluate_quotas(ctx.quotas)
            if not ok:
                raise QuotaExceeded(why)

        # Resource/budget limits (§41).
        from openagent.cloud.ops import ExecutionBudget
        ok, why = check_budget(cpu_millicores=request.cpu_millicores,
                               memory_mb=request.memory_mb,
                               timeout_seconds=request.timeout_seconds,
                               budget=ExecutionBudget(),
                               needs_browser=request.execution_class == "browser")
        if not ok:
            raise QuotaExceeded(why)

        priority = normalize_priority(
            requested=request.priority,
            plan_allows_high=ctx.plan_allows_high,
            plan_allows_critical=ctx.plan_allows_critical)

        execution_id = new_execution_id()
        placement = self._place(request, ctx, priority, execution_id)

        # Queue backpressure (§93): reject when the target queue is full.
        depth = await self.queues.depth(placement.queue)
        if depth >= self.global_max_queue_depth:
            raise QuotaExceeded(f"queue {placement.queue} at capacity")

        record = {
            "execution_id": execution_id,
            "organization_id": request.organization_id,
            "project_id": request.project_id,
            "environment": request.environment,
            "execution_class": request.execution_class,
            "priority": priority,
            "status": ExecutionState.QUEUED,
            "region_id": placement.region_id,
            "pool_id": placement.pool_id,
            "queue": placement.queue,
            "worker_id": placement.worker_id,
            "attempt": 0,
            "payload_ref": "",
            "error": "",
            "created_at": datetime.now(timezone.utc),
            "failover_from": placement.failover_from,
            "idempotency_key": request.idempotency_key,
        }
        self._executions[execution_id] = record

        message = CloudMessage(
            message_id="", queue=placement.queue, execution_id=execution_id,
            organization_id=request.organization_id, priority=priority,
            payload={"execution_class": request.execution_class,
                     "workflow_id": request.workflow_id,
                     "agent_id": request.agent_id,
                     "payload": request.payload,
                     "timeout_seconds": request.timeout_seconds,
                     "cpu_millicores": request.cpu_millicores,
                     "memory_mb": request.memory_mb,
                     "region_id": placement.region_id,
                     "pool_id": placement.pool_id})
        await self.queues.publish(placement.queue, message)

        if self.events is not None:
            await self.events.append(execution_id, "execution.started",
                                     {"queue": placement.queue,
                                      "region_id": placement.region_id})

        handle = ExecutionHandle(execution_id=execution_id,
                                 status=ExecutionState.QUEUED,
                                 region_id=placement.region_id,
                                 queue=placement.queue)
        if request.idempotency_key and self.idempotency is not None:
            await self.idempotency.store(request.organization_id,
                                         request.idempotency_key, handle)
        return handle

    # -------------------------------------------------------------- operate ---
    async def describe(self, execution_id: str, organization_id: str) -> ExecutionView:
        record = self._lookup(execution_id, organization_id)
        return self._view(record)

    async def cancel(self, execution_id: str, organization_id: str) -> ExecutionView:
        record = self._lookup(execution_id, organization_id)
        if is_valid_execution_transition(record["status"], ExecutionState.CANCELLED):
            record["status"] = ExecutionState.CANCELLED
            record["completed_at"] = datetime.now(timezone.utc)
            if self.events is not None:
                await self.events.append(execution_id, "execution.failed",
                                         {"reason": "cancelled"})
        return self._view(record)

    async def retry(self, execution_id: str, organization_id: str) -> ExecutionHandle:
        record = self._lookup(execution_id, organization_id)
        if not is_valid_execution_transition(record["status"], ExecutionState.RETRYING):
            raise ValueError(f"execution {execution_id} in {record['status']} is not retryable")
        record["status"] = ExecutionState.RETRYING
        record["attempt"] += 1
        # Re-queue through the same queue (deduplicated by execution id).
        message = CloudMessage(message_id="", queue=record["queue"],
                               execution_id=execution_id,
                               organization_id=organization_id,
                               priority=record["priority"],
                               payload={"retry_of": execution_id,
                                        "attempt": record["attempt"]})
        await self.queues.publish(record["queue"], message)
        record["status"] = ExecutionState.QUEUED
        return ExecutionHandle(execution_id=execution_id, status=record["status"],
                               region_id=record["region_id"], queue=record["queue"])

    async def transition(self, execution_id: str, organization_id: str,
                         to_state: str, *, worker_id: str = "") -> ExecutionView:
        """Worker-reported transition. Validated; never arbitrary mutation."""
        from openagent.cloud.errors import InvalidExecutionTransition
        record = self._lookup(execution_id, organization_id)
        if worker_id and record.get("worker_id") and record["worker_id"] != worker_id:
            # Ownership check: a worker may only move executions it holds
            # (or unclaimed ones it just claimed).
            raise InvalidExecutionTransition("worker does not own this execution")
        if not is_valid_execution_transition(record["status"], to_state):
            raise InvalidExecutionTransition(f"{record['status']} -> {to_state} not allowed")
        record["status"] = to_state
        if worker_id:
            record["worker_id"] = worker_id
        return self._view(record)

    async def stream(self, execution_id: str, organization_id: str,
                     from_sequence: int = 0) -> AsyncIterator[dict]:
        self._lookup(execution_id, organization_id)
        if self.events is None:
            yield {"sequence": from_sequence, "type": "execution.started",
                   "execution_id": execution_id}
            return
        async for event in self._iter_events(execution_id, from_sequence):
            yield event

    async def _iter_events(self, execution_id: str, from_sequence: int):
        events = await self.events.list(execution_id, from_sequence=from_sequence)
        for event in events:
            yield event.to_dict()
        return

    # -------------------------------------------------------------- helpers ---
    def _require_org_match(self, request: ExecutionRequest, ctx: DispatchContext) -> None:
        if not request.organization_id:
            raise ValueError("organization_id is required")
        if ctx.organization_id and ctx.organization_id != request.organization_id:
            raise ValueError("organization context mismatch")

    def _require_entitlement(self, ctx: DispatchContext) -> None:
        # ``cloud.execute`` commercial gate. Self-hosted/local mode skips
        # this (no billing dependency); the service layer decides.
        live = [e for e in ctx.entitlements
                if str(e.get("status", "")).upper() == "ACTIVE"]
        if ctx.entitlements and not live:
            raise EntitlementDenied("no active cloud execution entitlement")

    def _place(self, request: ExecutionRequest, ctx: DispatchContext,
               priority: str, execution_id: str) -> PlacementDecision:
        from openagent.cloud.placement import PlacementRequest as PR
        # When no workers are registered (fresh install), fall back to a
        # region-validated direct placement instead of failing closed.
        from openagent.cloud.placement import WorkerAdvert
        if hasattr(self, "_adverts"):
            adverts: list[WorkerAdvert] = list(self._adverts)  # type: ignore[attr-defined]
        else:
            adverts = []
        if not adverts:
            region_id = (request.region_id or
                         (self.regions.list(schedulable_only=True)[0].id
                          if self.regions.list(schedulable_only=True) else "local-1"))
            queue = route_queue(execution_class=request.execution_class,
                                priority=priority, memory_mb=request.memory_mb,
                                cpu_millicores=request.cpu_millicores,
                                pool_id=request.pool_id or "default")
            return PlacementDecision(region_id=region_id,
                                     pool_id=request.pool_id or "default",
                                     queue=queue, reason="direct: no worker fleet")
        placement_request = PR(
            organization_id=request.organization_id,
            execution_class=request.execution_class, priority=priority,
            region_hint=request.region_id, pool_id=request.pool_id or "default",
            residency=request.residency or ctx.residency,
            org_regions=ctx.org_regions, cpu_millicores=request.cpu_millicores,
            memory_mb=request.memory_mb,
            needs_gpu=request.labels.get("gpu") == "true",
            needs_browser=request.execution_class == "browser",
            queue_depths=ctx.queue_depths)
        try:
            return self.placement.place(placement_request, adverts)
        except PlacementFailed:
            raise

    def attach_adverts(self, adverts: list) -> None:
        self._adverts = list(adverts)

    def _lookup(self, execution_id: str, organization_id: str) -> dict:
        record = self._executions.get(execution_id)
        if record is None:
            raise KeyError(f"execution {execution_id} not found")
        if record["organization_id"] != organization_id:
            raise PermissionError("cross-tenant execution access denied")
        return record

    def _view(self, record: dict) -> ExecutionView:
        return ExecutionView(
            execution_id=record["execution_id"], status=record["status"],
            region_id=record["region_id"], queue=record["queue"],
            worker_id=record.get("worker_id", ""),
            attempt=record.get("attempt", 0),
            created_at=record.get("created_at"),
            started_at=record.get("started_at"),
            completed_at=record.get("completed_at"),
            error=record.get("error", ""))
