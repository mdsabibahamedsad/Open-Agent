"""MP25: internal worker API (§58-59).

Service-authenticated endpoints for the fleet: register, heartbeat,
claim/ack/progress/complete/fail, lease renewal, drain/shutdown.
Never exposed without the worker service token.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.cloud.errors import InvalidExecutionTransition, InvalidWorkerTransition
from openagent.cloud.service import get_cloud_service
from openagent.cloud.types import is_valid_execution_transition
from openagent.cloud.workers import WorkerRecord
from openagent.core.config import get_settings
from openagent.db.models.cloud import CloudWorker, WorkerHeartbeat
from openagent.db.session import get_db

router = APIRouter(prefix="/internal/workers", tags=["internal-workers"])


def _require_worker_token(
    authorization: str = Header(default=""),
    x_worker_id: str = Header(default="", alias="X-Worker-ID"),
) -> str:
    settings = get_settings()
    expected = getattr(settings, "WORKER_SERVICE_TOKEN", "") or ""
    if not expected:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="Worker API not configured")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Worker authentication required")
    if not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid worker credential")
    if token and x_worker_id:
        return x_worker_id
    return ""


# ------------------------------------------------------------------ schemas ---
class RegisterRequest(BaseModel):
    worker_id: str = Field(min_length=1, max_length=128)
    region: str = Field(min_length=1, max_length=100)
    pool: str = Field(default="default", max_length=100)
    capabilities: List[str] = Field(default_factory=list)
    max_concurrency: int = Field(default=4, ge=1, le=256)
    cpu_millicores_total: int = Field(default=2000, ge=100, le=256000)
    memory_mb_total: int = Field(default=4096, ge=128, le=1048576)
    supports_gpu: bool = Field(default=False)
    version: str = Field(default="0.1.0", max_length=50)
    labels: Dict[str, str] = Field(default_factory=dict)


class HeartbeatRequest(BaseModel):
    active_count: int = Field(default=0, ge=0, le=1024)
    cpu_used: int = Field(default=0, ge=0)
    memory_used: int = Field(default=0, ge=0)
    state: str = Field(default="")


class ClaimRequest(BaseModel):
    queues: List[str] = Field(default_factory=list)
    visibility_seconds: int = Field(default=300, ge=30, le=3600)


class AckRequest(BaseModel):
    queue: str = Field(min_length=1, max_length=100)
    message_id: str = Field(min_length=1, max_length=64)


class ProgressRequest(BaseModel):
    execution_id: str = Field(min_length=1, max_length=64)
    organization_id: str = Field(min_length=1, max_length=64)
    to_state: str = Field(min_length=1, max_length=32)
    usage: Dict[str, float] = Field(default_factory=dict)


# ---------------------------------------------------------------- endpoints ---
@router.post("/register", response_model=Dict[str, Any])
async def register_worker(
    body: RegisterRequest,
    worker_header: str = Depends(_require_worker_token),
    db: AsyncSession = Depends(get_db),
):
    if worker_header and worker_header != body.worker_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Worker identity mismatch")
    if not body.capabilities:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="capabilities are required")
    service = get_cloud_service()
    service.require_enabled()
    try:
        record = service.register_worker(WorkerRecord(
            worker_id=body.worker_id,
            service_identity=f"svc:{body.worker_id}",
            region_id=body.region, pool_id=body.pool,
            capabilities=body.capabilities[:32], labels=body.labels,
            version=body.version, max_concurrency=body.max_concurrency,
            cpu_millicores_total=body.cpu_millicores_total,
            memory_mb_total=body.memory_mb_total,
            supports_gpu=body.supports_gpu))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    row = (await db.execute(
        select(CloudWorker).where(CloudWorker.worker_id == body.worker_id))).scalar_one_or_none()
    if row is None:
        row = CloudWorker(worker_id=body.worker_id,
                          service_identity=f"svc:{body.worker_id}")
        db.add(row)
    row.region_slug = body.region
    row.pool_slug = body.pool
    row.capabilities = body.capabilities[:32]
    row.labels = body.labels
    row.state = "READY"
    row.version = body.version
    row.max_concurrency = body.max_concurrency
    row.cpu_millicores_total = body.cpu_millicores_total
    row.memory_mb_total = body.memory_mb_total
    row.supports_gpu = body.supports_gpu
    row.last_heartbeat_at = datetime.now(timezone.utc)
    await db.commit()
    return {"worker": body.worker_id, "status": "READY"}


@router.post("/{worker_id}/heartbeat", response_model=Dict[str, Any])
async def worker_heartbeat(
    worker_id: str, body: HeartbeatRequest,
    worker_header: str = Depends(_require_worker_token),
    db: AsyncSession = Depends(get_db),
):
    if worker_header and worker_header != worker_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Worker identity mismatch")
    service = get_cloud_service()
    service.require_enabled()
    try:
        service.workers.heartbeat(worker_id, active_count=body.active_count,
                                  cpu_used=body.cpu_used,
                                  memory_used=body.memory_used,
                                  state=body.state or "")
    except InvalidWorkerTransition as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except Exception as exc:
        # In-memory registry is best-effort; DB stays canonical.
        if "unknown worker" in str(exc).lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                detail="Worker not registered")
        raise
    row = (await db.execute(
        select(CloudWorker).where(CloudWorker.worker_id == worker_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Worker not registered")
    row.active_count = body.active_count
    row.last_heartbeat_at = datetime.now(timezone.utc)
    if body.state:
        row.state = body.state
    db.add(WorkerHeartbeat(worker_id=worker_id, state=row.state,
                           active_count=body.active_count,
                           cpu_millicores_used=body.cpu_used,
                           memory_mb_used=body.memory_used))
    await db.commit()
    return {"worker": worker_id, "status": row.state}


@router.post("/{worker_id}/claim", response_model=Dict[str, Any])
async def claim_work(
    worker_id: str, body: ClaimRequest,
    worker_header: str = Depends(_require_worker_token),
):
    if worker_header and worker_header != worker_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Worker identity mismatch")
    service = get_cloud_service()
    service.require_enabled()
    for queue in (body.queues or ["workflow.default"])[:8]:
        message = await service.queues.claim(queue, worker_id,
                                             visibility_seconds=body.visibility_seconds)
        if message is not None:
            creds = await service.worker_credentials(
                worker_id=worker_id, execution_id=message.execution_id,
                organization_id=message.organization_id)
            return {"queue": queue, "message_id": message.message_id,
                    "execution_id": message.execution_id,
                    "organization_id": message.organization_id,
                    "payload": message.payload, "attempt": message.attempt,
                    "credentials": creds}
    return {"queue": "", "message_id": "", "execution_id": ""}


@router.post("/{worker_id}/ack", response_model=Dict[str, Any])
async def ack_work(
    worker_id: str, body: AckRequest,
    worker_header: str = Depends(_require_worker_token),
):
    if worker_header and worker_header != worker_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Worker identity mismatch")
    service = get_cloud_service()
    service.require_enabled()
    await service.queues.ack(body.queue, body.message_id, worker_id)
    return {"ok": True}


@router.post("/{worker_id}/progress", response_model=Dict[str, Any])
async def report_progress(
    worker_id: str, body: ProgressRequest,
    worker_header: str = Depends(_require_worker_token),
):
    if worker_header and worker_header != worker_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Worker identity mismatch (no impersonation)")
    service = get_cloud_service()
    service.require_enabled()
    try:
        view = await service.dispatcher.transition(
            body.execution_id, body.organization_id, body.to_state.upper(),
            worker_id=worker_id)
    except InvalidExecutionTransition as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return {"execution_id": view.execution_id, "status": view.status}


@router.post("/{worker_id}/drain", response_model=Dict[str, Any])
async def drain_self(
    worker_id: str,
    worker_header: str = Depends(_require_worker_token),
    db: AsyncSession = Depends(get_db),
):
    if worker_header and worker_header != worker_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Worker identity mismatch")
    service = get_cloud_service()
    service.require_enabled()
    try:
        service.workers.drain(worker_id)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    row = (await db.execute(
        select(CloudWorker).where(CloudWorker.worker_id == worker_id))).scalar_one_or_none()
    if row is not None:
        row.state = "DRAINING"
        row.drained_at = datetime.now(timezone.utc)
        await db.commit()
    return {"worker": worker_id, "status": "DRAINING"}
