"""MP25: cloud control-plane API.

Tenant-scoped execution submission + operations. Every read/write is
organization-checked (§23); rate limits reuse the platform middleware.
Exact route names follow the existing ``/api/v1`` conventions.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.api.dependencies import (
    get_current_org_context, require_platform_owner,
)
from openagent.cloud.dispatcher import DispatchContext
from openagent.cloud.errors import (
    CloudDisabled, EntitlementDenied, IncidentBlocked, PlacementFailed,
    QuotaExceeded,
)
from openagent.cloud.ops import QuotaCheck
from openagent.cloud.runtime import ExecutionRequest
from openagent.cloud.service import get_cloud_service
from openagent.cloud.types import (
    DataResidency, ExecutionClass, ExecutionPriority,
)
from openagent.db.models.cloud import (
    CloudArtifact, CloudQueueState, CloudRegion, CloudWorker,
    DeadLetterMessage, ExecutionPlacement, RuntimePolicy,
)
from openagent.db.session import get_db
from openagent.services.authorization import AuthorizationContext

router = APIRouter(prefix="/cloud", tags=["cloud"])
regions_router = APIRouter(prefix="/cloud/regions", tags=["cloud-regions"])
master_router = APIRouter(prefix="/master/cloud", tags=["master-cloud"])


def _svc():
    service = get_cloud_service()
    service.require_enabled()
    return service


# ------------------------------------------------------------------ schemas ---
class SubmitExecutionRequest(BaseModel):
    execution_class: str = Field(default="workflow", max_length=32)
    workflow_id: str = Field(default="", max_length=64)
    agent_id: str = Field(default="", max_length=64)
    project_id: str = Field(default="", max_length=64)
    environment: str = Field(default="production", max_length=32)
    payload: Dict[str, Any] = Field(default_factory=dict)
    priority: str = Field(default="NORMAL", max_length=16)
    region_id: str = Field(default="", max_length=100)
    pool_id: str = Field(default="default", max_length=100)
    residency: str = Field(default="ANY_REGION", max_length=32)
    cpu_millicores: int = Field(default=500, ge=10, le=32000)
    memory_mb: int = Field(default=512, ge=64, le=131072)
    timeout_seconds: int = Field(default=600, ge=5, le=86400)


class ReportUsageRequest(BaseModel):
    execution_id: str = Field(min_length=1, max_length=64)
    usage: Dict[str, float]


class UpsertPolicyRequest(BaseModel):
    residency: str = Field(default="ANY_REGION", max_length=32)
    allowed_regions: List[str] = Field(default_factory=list)
    pool_preference: str = Field(default="default", max_length=100)
    max_concurrent_executions: int = Field(default=10, ge=1, le=10000)
    artifact_retention_seconds: int = Field(default=2592000, ge=0, le=315360000)
    webhook_limit_per_minute: int = Field(default=120, ge=1, le=100000)


def _ctx_from_request(request: SubmitExecutionRequest,
                      auth: AuthorizationContext) -> DispatchContext:
    return DispatchContext(
        organization_id=str(auth.organization_id),
        entitlements=[], quotas=[],
        plan_allows_high=True, plan_allows_critical=False,
        residency=request.residency or DataResidency.ANY_REGION)


def _handle_error(exc: Exception) -> HTTPException:
    if isinstance(exc, CloudDisabled):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                             detail="Cloud runtime is disabled on this installation")
    if isinstance(exc, IncidentBlocked):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                             detail=str(exc))
    if isinstance(exc, (EntitlementDenied, QuotaExceeded)):
        return HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED
                             if isinstance(exc, EntitlementDenied)
                             else status.HTTP_429_TOO_MANY_REQUESTS,
                             detail=str(exc))
    if isinstance(exc, PlacementFailed):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                             detail=str(exc))
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, (ValueError, KeyError)):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                         detail="Cloud operation failed")


# --------------------------------------------------------------- executions ---
@router.post("/executions", response_model=Dict[str, Any],
             summary="Submit a cloud execution")
async def submit_execution(
    body: SubmitExecutionRequest,
    request: Request,
    auth: AuthorizationContext = Depends(get_current_org_context),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db),
):
    try:
        service = _svc()
    except CloudDisabled as exc:
        raise _handle_error(exc)
    if body.execution_class not in ExecutionClass.ALL:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"unknown execution class {body.execution_class}")
    if body.priority.upper() not in ExecutionPriority.ALL:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"unknown priority {body.priority}")
    if body.residency.upper() not in DataResidency.ALL:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"unknown residency {body.residency}")
    ctx = _ctx_from_request(body, auth)
    req = ExecutionRequest(
        organization_id=str(auth.organization_id), project_id=body.project_id,
        environment=body.environment, execution_class=body.execution_class,
        workflow_id=body.workflow_id, agent_id=body.agent_id,
        payload=body.payload, priority=body.priority.upper(),
        region_id=body.region_id, pool_id=body.pool_id,
        residency=body.residency.upper(), cpu_millicores=body.cpu_millicores,
        memory_mb=body.memory_mb, timeout_seconds=body.timeout_seconds,
        idempotency_key=(idempotency_key or "")[:255])
    try:
        handle = await service.submit(req, ctx)
    except Exception as exc:
        raise _handle_error(exc)
    # Persist placement (control-plane metadata, §2).
    try:
        db.add(ExecutionPlacement(
            execution_id=handle.execution_id,
            organization_id=auth.organization_id,
            region_slug=handle.region_id, pool_slug=body.pool_id or "default",
            queue=handle.queue, priority=body.priority.upper(),
            residency=body.residency.upper()))
        await db.commit()
    except Exception:
        await db.rollback()
    return {"execution_id": handle.execution_id, "status": handle.status,
            "region": handle.region_id, "queue": handle.queue}


@router.get("/executions/{execution_id}", response_model=Dict[str, Any])
async def get_execution(
    execution_id: str,
    auth: AuthorizationContext = Depends(get_current_org_context),
):
    try:
        view = await _svc().dispatcher.describe(
            execution_id, str(auth.organization_id))
    except Exception as exc:
        raise _handle_error(exc)
    return {"execution_id": view.execution_id, "status": view.status,
            "region": view.region_id, "queue": view.queue,
            "worker": view.worker_id, "attempt": view.attempt,
            "started": view.started_at, "completed": view.completed_at,
            "error": view.error}


@router.post("/executions/{execution_id}/cancel", response_model=Dict[str, Any])
async def cancel_execution(
    execution_id: str,
    auth: AuthorizationContext = Depends(get_current_org_context),
):
    try:
        view = await _svc().dispatcher.cancel(execution_id, str(auth.organization_id))
    except Exception as exc:
        raise _handle_error(exc)
    return {"execution_id": view.execution_id, "status": view.status}


@router.post("/executions/{execution_id}/retry", response_model=Dict[str, Any])
async def retry_execution(
    execution_id: str,
    auth: AuthorizationContext = Depends(get_current_org_context),
):
    try:
        handle = await _svc().dispatcher.retry(execution_id, str(auth.organization_id))
    except Exception as exc:
        raise _handle_error(exc)
    return {"execution_id": handle.execution_id, "status": handle.status,
            "region": handle.region_id, "queue": handle.queue}


@router.get("/executions/{execution_id}/events", response_model=Dict[str, Any])
async def get_execution_events(
    execution_id: str,
    auth: AuthorizationContext = Depends(get_current_org_context),
    from_sequence: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=1000),
):
    try:
        service = _svc()
        service.dispatcher._lookup(execution_id, str(auth.organization_id))
        events = await service.events.list(execution_id,
                                           from_sequence=from_sequence, limit=limit)
    except Exception as exc:
        raise _handle_error(exc)
    return {"execution_id": execution_id,
            "events": [e.to_dict() for e in events]}


@router.get("/executions/{execution_id}/stream")
async def stream_execution(
    execution_id: str,
    auth: AuthorizationContext = Depends(get_current_org_context),
    from_sequence: int = Query(default=0, ge=0),
):
    try:
        service = _svc()
        gen = service.dispatcher.stream(execution_id, str(auth.organization_id),
                                        from_sequence=from_sequence)
    except Exception as exc:
        raise _handle_error(exc)

    async def _sse():
        async for event in gen:
            import json
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(_sse(), media_type="text/event-stream")


# ------------------------------------------------------------------- workers ---
@router.get("/workers", response_model=Dict[str, Any])
async def list_workers(
    auth: AuthorizationContext = Depends(get_current_org_context),
    region: str = Query(default=""),
    pool: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
):
    _svc()
    query = select(CloudWorker)
    if region:
        query = query.where(CloudWorker.region_slug == region)
    if pool:
        query = query.where(CloudWorker.pool_slug == pool)
    query = query.order_by(CloudWorker.worker_id).limit(200)
    rows = (await db.execute(query)).scalars().all()
    return {"workers": [
        {"worker": r.worker_id, "region": r.region_slug, "pool": r.pool_slug,
         "status": r.state, "capacity": r.max_concurrency,
         "active": r.active_count, "cpu_total": r.cpu_millicores_total,
         "memory_total": r.memory_mb_total, "version": r.version,
         "heartbeat": r.last_heartbeat_at.isoformat() if r.last_heartbeat_at else None}
        for r in rows]}


@router.post("/workers/{worker_id}/drain", response_model=Dict[str, Any])
async def drain_worker(
    worker_id: str,
    auth: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    _svc()
    row = (await db.execute(
        select(CloudWorker).where(CloudWorker.worker_id == worker_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Worker not found")
    try:
        get_cloud_service().workers.drain(worker_id)
    except Exception:
        pass  # in-memory registry may not track this worker; DB is canonical
    row.state = "DRAINING"
    row.drained_at = datetime.now(timezone.utc)
    await db.commit()
    return {"worker": worker_id, "status": "DRAINING"}


# -------------------------------------------------------------------- queues ---
@router.get("/queues", response_model=Dict[str, Any])
async def list_queues(
    auth: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    service = _svc()
    rows = (await db.execute(select(CloudQueueState))).scalars().all()
    cached = {r.queue: r for r in rows}
    out = []
    from openagent.cloud.types import QueueName
    for queue in QueueName.ALL:
        depth = await service.queues.depth(queue)
        age = await service.queues.oldest_age_seconds(queue)
        row = cached.get(queue)
        out.append({"queue": queue, "depth": depth, "oldest_job_age_s": age,
                    "processing": row.processing if row else 0,
                    "failed": row.dead_letter_count if row else 0,
                    "paused": row.paused if row else False})
    return {"queues": out}


@router.get("/queues/{queue_name}/dead-letter", response_model=Dict[str, Any])
async def list_dead_letter(
    queue_name: str,
    auth: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
):
    _svc()
    rows = (await db.execute(
        select(DeadLetterMessage)
        .where(DeadLetterMessage.queue == queue_name,
               DeadLetterMessage.organization_id == auth.organization_id)
        .order_by(DeadLetterMessage.created_at.desc()).limit(limit))).scalars().all()
    return {"queue": queue_name, "entries": [
        {"id": str(r.id), "message_id": r.message_id, "execution": r.execution_id,
         "reason": r.reason, "status": r.status,
         "created": r.created_at.isoformat()} for r in rows]}


@router.post("/queues/{queue_name}/dead-letter/{entry_id}/retry",
             response_model=Dict[str, Any])
async def retry_dead_letter(
    queue_name: str, entry_id: str,
    auth: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    from uuid import UUID as _UUID
    try:
        eid = _UUID(entry_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Invalid entry id")
    row = (await db.execute(
        select(DeadLetterMessage).where(
            DeadLetterMessage.id == eid,
            DeadLetterMessage.organization_id == auth.organization_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Dead-letter entry not found")
    row.status = "RETRY_QUEUED"
    row.resolved_at = datetime.now(timezone.utc)
    await db.commit()
    return {"id": entry_id, "status": "RETRY_QUEUED"}


# ------------------------------------------------------------------- regions ---
@regions_router.get("", response_model=Dict[str, Any])
async def list_regions(
    auth: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    _svc()
    rows = (await db.execute(select(CloudRegion).order_by(CloudRegion.slug))).scalars().all()
    return {"regions": [
        {"region": r.slug, "name": r.name, "health": r.status,
         "capabilities": r.capabilities, "private": r.is_private} for r in rows]}


# ------------------------------------------------------------------- storage ---
@router.get("/storage", response_model=Dict[str, Any])
async def storage_overview(
    auth: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    _svc()
    total = (await db.execute(
        select(func.coalesce(func.sum(CloudArtifact.size), 0)).where(
            CloudArtifact.organization_id == auth.organization_id,
            CloudArtifact.state == "ACTIVE"))).scalar_one()
    count = (await db.execute(
        select(func.count(CloudArtifact.id)).where(
            CloudArtifact.organization_id == auth.organization_id,
            CloudArtifact.state == "ACTIVE"))).scalar_one()
    largest = (await db.execute(
        select(CloudArtifact).where(
            CloudArtifact.organization_id == auth.organization_id,
            CloudArtifact.state == "ACTIVE")
        .order_by(CloudArtifact.size.desc()).limit(10))).scalars().all()
    return {"usage_bytes": int(total or 0), "artifact_count": int(count or 0),
            "largest": [{"id": a.artifact_id, "name": a.name, "size": a.size,
                         "category": a.category} for a in largest]}


@router.get("/usage", response_model=Dict[str, Any])
async def cloud_usage(
    auth: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    from openagent.db.models.cloud import CloudUsageEvent
    _svc()
    rows = (await db.execute(
        select(CloudUsageEvent.meter, func.sum(CloudUsageEvent.quantity))
        .where(CloudUsageEvent.organization_id == auth.organization_id)
        .group_by(CloudUsageEvent.meter))).all()
    return {"usage": {meter: float(total or 0.0) for meter, total in rows}}


@router.get("/health", response_model=Dict[str, Any])
async def cloud_health(
    auth: AuthorizationContext = Depends(get_current_org_context),
):
    return await _svc().health()


@router.post("/usage/report", response_model=Dict[str, Any])
async def report_usage(
    body: ReportUsageRequest,
    auth: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    from openagent.db.models.cloud import CloudUsageEvent
    service = _svc()
    records = service.usage_records(organization_id=str(auth.organization_id),
                                    execution_id=body.execution_id,
                                    usage=body.usage)
    staged = 0
    for record in records:
        exists = (await db.execute(
            select(CloudUsageEvent).where(
                CloudUsageEvent.dedup_key == record["dedup_key"]))).scalar_one_or_none()
        if exists is None:
            db.add(CloudUsageEvent(
                organization_id=auth.organization_id,
                execution_id=body.execution_id, meter=record["meter"],
                quantity=record["quantity"], dedup_key=record["dedup_key"]))
            staged += 1
    await db.commit()
    return {"staged": staged}


@router.get("/settings", response_model=Dict[str, Any])
async def get_org_policy(
    auth: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    _svc()
    row = (await db.execute(
        select(RuntimePolicy).where(
            RuntimePolicy.scope == "organization",
            RuntimePolicy.organization_id == auth.organization_id))).scalar_one_or_none()
    if row is None:
        return {"residency": "ANY_REGION", "allowed_regions": [],
                "pool": "default", "max_concurrent": 10,
                "artifact_retention_s": 2592000, "webhook_per_minute": 120}
    return {"residency": row.residency, "allowed_regions": row.allowed_regions,
            "pool": row.pool_preference, "max_concurrent": row.max_concurrent_executions,
            "artifact_retention_s": row.artifact_retention_seconds,
            "webhook_per_minute": row.webhook_limit_per_minute}


@router.put("/settings", response_model=Dict[str, Any])
async def put_org_policy(
    body: UpsertPolicyRequest,
    auth: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    from openagent.cloud.types import DataResidency
    _svc()
    if body.residency.upper() not in DataResidency.ALL:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"unknown residency {body.residency}")
    row = (await db.execute(
        select(RuntimePolicy).where(
            RuntimePolicy.scope == "organization",
            RuntimePolicy.organization_id == auth.organization_id))).scalar_one_or_none()
    if row is None:
        row = RuntimePolicy(scope="organization",
                            organization_id=auth.organization_id)
        db.add(row)
    row.residency = body.residency.upper()
    row.allowed_regions = body.allowed_regions[:32]
    row.pool_preference = body.pool_preference
    row.max_concurrent_executions = body.max_concurrent_executions
    row.artifact_retention_seconds = body.artifact_retention_seconds
    row.webhook_limit_per_minute = body.webhook_limit_per_minute
    await db.commit()
    return {"ok": True}


# ------------------------------------------------------------ master console ---
@master_router.get("/overview", response_model=Dict[str, Any])
async def master_overview(
    user=Depends(require_platform_owner()),
    db: AsyncSession = Depends(get_db),
):
    service = get_cloud_service()  # master view works even if cloud disabled
    health = await service.health()
    active = (await db.execute(
        select(func.count(CloudWorker.id)).where(CloudWorker.state.in_(
            ["READY", "BUSY", "STARTING"])))).scalar_one()
    regions = (await db.execute(select(func.count(CloudRegion.id)))).scalar_one()
    return {"health": health, "active_workers": int(active or 0),
            "regions": int(regions or 0),
            "incident_mode": service.settings.CLOUD_INCIDENT_MODE}


@master_router.get("/limits", response_model=Dict[str, Any])
async def master_limits(user=Depends(require_platform_owner())):
    s = get_cloud_service().settings
    return {"global_max_workers": s.GLOBAL_MAX_WORKERS,
            "global_max_executions": s.GLOBAL_MAX_EXECUTIONS,
            "global_max_queue_depth": s.GLOBAL_MAX_QUEUE_DEPTH,
            "global_max_sandbox": s.GLOBAL_MAX_SANDBOX_COUNT,
            "global_max_browser": s.GLOBAL_MAX_BROWSER_COUNT,
            "global_max_storage_bytes": s.GLOBAL_MAX_STORAGE_BYTES,
            "autoscale": {"min": s.AUTOSCALE_MIN_WORKERS,
                         "max": s.AUTOSCALE_MAX_WORKERS,
                         "cooldown_s": s.AUTOSCALE_COOLDOWN_SECONDS}}
