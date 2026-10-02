"""MP26: organization enterprise controls — IP policy, retention,
policy presets, rotation jobs, private runtime enrollment, session
policy view. Scoped to the caller's organization (§47-54, §58-61).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.api.dependencies import get_current_org_context
from openagent.control.enterprise import (
    SessionPolicy, apply_preset, ip_allowed, merge_retention,
)
from openagent.control.observability import redact
from openagent.db.models.control import (
    IpPolicyRow, PrivateEnrollmentRow, RotationJobRow,
)
from openagent.db.session import get_db
from openagent.services.authorization import AuthorizationContext

router = APIRouter(prefix="/enterprise", tags=["enterprise"])

PLATFORM_RETENTION_MINIMUMS = {
    "audit_logs": 31536000,      # 365d: compliance floor
    "security_events": 31536000,
    "executions": 7776000,       # 90d
    "logs": 2592000,             # 30d
    "artifacts": 2592000,
}


class IpPolicyUpsert(BaseModel):
    allowlist: list[str] = Field(default_factory=list)
    denylist: list[str] = Field(default_factory=list)
    enabled: bool = Field(default=True)


class RetentionUpsert(BaseModel):
    policy: dict[str, int]


class RotationCreate(BaseModel):
    kind: str = Field(pattern="^(credential|api_key|service_identity|cloud_secret)$")
    ref: str = Field(min_length=1, max_length=255)


@router.get("/ip-policy", summary="Organization IP restrictions")
async def get_ip_policy(
    auth: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(select(IpPolicyRow).where(
        IpPolicyRow.organization_id == auth.organization_id))).scalar_one_or_none()
    if row is None:
        return {"enabled": False, "allowlist": [], "denylist": []}
    return {"enabled": row.enabled, "allowlist": row.allowlist,
            "denylist": row.denylist}


@router.put("/ip-policy", summary="Update IP restrictions")
async def put_ip_policy(
    body: IpPolicyUpsert,
    auth: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    import ipaddress
    for rule in body.allowlist + body.denylist:
        try:
            ipaddress.ip_network(rule, strict=False)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail=f"Invalid CIDR {rule}")
    row = (await db.execute(select(IpPolicyRow).where(
        IpPolicyRow.organization_id == auth.organization_id))).scalar_one_or_none()
    if row is None:
        row = IpPolicyRow(organization_id=auth.organization_id,
                          updated_by=str(auth.user_id))
        db.add(row)
    row.allowlist = body.allowlist[:200]
    row.denylist = body.denylist[:200]
    row.enabled = body.enabled
    await db.commit()
    return {"enabled": row.enabled}


@router.get("/retention", summary="Effective retention (platform floors enforced)")
async def get_retention(
    auth: AuthorizationContext = Depends(get_current_org_context),
):
    merged, _ = merge_retention(PLATFORM_RETENTION_MINIMUMS, {})
    return {"retention_seconds": merged,
            "minimums": PLATFORM_RETENTION_MINIMUMS}


@router.put("/retention", summary="Propose retention (floors cannot be bypassed)")
async def put_retention(
    body: RetentionUpsert,
    auth: AuthorizationContext = Depends(get_current_org_context),
):
    merged, clamped = merge_retention(PLATFORM_RETENTION_MINIMUMS, body.policy)
    return {"retention_seconds": merged, "clamped_to_minimum": clamped}


@router.get("/presets", summary="Policy preset bundles")
async def list_presets(
    auth: AuthorizationContext = Depends(get_current_org_context),
    name: str = Query(default="standard"),
):
    try:
        return {"preset": name, "policy": apply_preset(name)}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=str(exc))


@router.get("/session-policy", summary="Organization session policy")
async def session_policy(
    auth: AuthorizationContext = Depends(get_current_org_context),
):
    policy = SessionPolicy()
    return {"lifetime_minutes": policy.lifetime_minutes,
            "idle_timeout_minutes": policy.idle_timeout_minutes,
            "max_concurrent": policy.max_concurrent}


@router.post("/rotations", summary="Start secret rotation (no downtime)")
async def start_rotation(
    body: RotationCreate,
    auth: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    from openagent.control.enterprise import RotationJob
    job = RotationJob(kind=body.kind, ref=body.ref)
    row = RotationJobRow(kind=job.kind, ref=job.ref, stage=job.stage,
                         created_by=str(auth.user_id))
    db.add(row)
    await db.commit()
    return {"job_id": str(row.id), "stage": row.stage}


@router.post("/rotations/{job_id}/advance", summary="Advance rotation stage")
async def advance_rotation(
    job_id: UUID,
    auth: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
    ok: bool = Query(default=True),
    error: str = Query(default=""),
):
    from openagent.control.enterprise import RotationJob
    row = (await db.execute(select(RotationJobRow).where(
        RotationJobRow.id == job_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Rotation job not found")
    job = RotationJob(job_id=str(row.id), kind=row.kind, ref=row.ref,
                      stage=row.stage)
    advanced, message = job.advance(ok, error[:1000])
    row.stage = job.stage
    row.error = job.error
    if job.verified_at:
        row.verified_at = job.verified_at
    await db.commit()
    if not advanced:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=message)
    return {"job_id": str(row.id), "stage": row.stage}


@router.post("/private-workers/redeem", summary="Redeem enrollment (private runtime)")
async def redeem_enrollment(
    token: str = Query(min_length=1, max_length=256),
    worker_id: str = Query(min_length=1, max_length=128),
    auth: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    import hashlib
    from openagent.control.enterprise import PrivateEnrollment
    digest = hashlib.sha256(token.encode()).hexdigest()
    row = (await db.execute(select(PrivateEnrollmentRow).where(
        PrivateEnrollmentRow.token_hash == digest,
        PrivateEnrollmentRow.organization_id == auth.organization_id)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Unknown enrollment token")
    enrollment = PrivateEnrollment(
        enrollment_id=str(row.id),
        organization_id=str(row.organization_id),
        token_hash=row.token_hash, expires_at=row.expires_at,
        used=row.used, worker_id=row.worker_id)
    ok, message = enrollment.redeem(token, worker_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_410_GONE
                            if "expired" in message or "used" in message
                            else status.HTTP_403_FORBIDDEN, detail=message)
    row.used = enrollment.used
    row.worker_id = enrollment.worker_id
    await db.commit()
    return {"enrolled": True, "worker": worker_id}
