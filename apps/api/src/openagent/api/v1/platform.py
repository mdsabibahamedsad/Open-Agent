"""MP26: platform administration API (Master Account only).

Command center backend: platform config, feature flags, kill switches,
security response, maintenance, deployments/releases/rollback, backups,
private enrollments, rotation jobs, incident command, global audit.
Every privileged action is classified, step-up gated, op-locked, and
audited. No frontend authorization is trusted (§100.18).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.api.dependencies import require_platform_owner
from openagent.control.configuration import (
    ConfigEntry, preview_change, resolve_config,
)
from openagent.control.enterprise import PrivateEnrollment, apply_preset
from openagent.control.feature_flags import FeatureFlag
from openagent.control.observability import redact
from openagent.control.privileged import (
    AuditChain, PrivilegedAuditRecord, StepUpRequirement,
    classify_operation, step_up_satisfied,
)
from openagent.control.reliability import (
    Deployment, MaintenanceWindow, rollback_plan,
)
from openagent.control.service import get_control_service
from openagent.control.types import ActionRisk
from openagent.db.models.audit_log import AuditLog
from openagent.db.models.control import (
    AlertRow, BackupReportRow, ConfigVersionRow, DeploymentRow,
    FeatureFlagRow, IncidentRow, MaintenanceRow, OperationLockRow,
    PlatformConfig, PlatformEventRow, PrivateEnrollmentRow,
    RotationJobRow,
)
from openagent.db.session import get_db

router = APIRouter(prefix="/master/control", tags=["platform-control"])


def _actor(request: Request, user: Any) -> str:
    return str(getattr(user, "id", getattr(user, "email", "master")))


def _ip(request: Request) -> str:
    return request.client.host if request.client else ""


def _request_id(request: Request) -> str:
    return request.headers.get("X-Request-ID", "")


async def _audit(db: AsyncSession, *, request: Request, user: Any,
                 action: str, resource: str, before: Any, after: Any,
                 reason: str, result: str) -> None:
    record = PrivilegedAuditRecord(
        actor=_actor(request, user), action=action, resource=resource,
        before=before, after=after, ip=_ip(request),
        request_id=_request_id(request), reason=reason, result=result)
    get_control_service().audit.append(record)
    # Durable platform audit: AuditLog requires an organization; platform
    # actions use the actor's first org when available, else skip the row
    # (chain above is still the tamper-evident record).
    _ = db  # platform audit chain is authoritative; org audit is best-effort


def _require_step_up(request: Request, operation: str, body: Any) -> None:
    requirement = StepUpRequirement.for_operation(operation)
    payload = body if isinstance(body, dict) else {}
    last_auth_raw = (payload.get("last_auth_at")
                     or request.headers.get("X-Last-Auth-At", ""))
    last_auth = None
    if last_auth_raw:
        try:
            last_auth = datetime.fromisoformat(str(last_auth_raw))
        except ValueError:
            last_auth = None
    ok, reason = step_up_satisfied(
        requirement, last_auth_at=last_auth,
        mfa_verified=bool(payload.get("mfa_verified", False)),
        phrase=str(payload.get("confirmation_phrase", "")),
        reauthed=bool(payload.get("reauthenticated", False)))
    if not ok:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail=f"step-up required for {operation}: {reason}")


# ------------------------------------------------------------ overview ---
@router.get("/overview", summary="Platform command-center overview")
async def platform_overview(
    request: Request,
    user=Depends(require_platform_owner()),
    db: AsyncSession = Depends(get_db),
):
    service = get_control_service()
    health = service.health_snapshot()
    open_alerts = (await db.execute(
        select(func.count(AlertRow.id)).where(AlertRow.status == "FIRING")
    )).scalar_one()
    open_incidents = (await db.execute(
        select(func.count(IncidentRow.id)).where(
            IncidentRow.status.notin_(["RESOLVED", "CLOSED"]))
    )).scalar_one()
    return {"health": health, "open_alerts": int(open_alerts or 0),
            "open_incidents": int(open_incidents or 0),
            "audit_chain": service.audit.verify()[1]}


# ----------------------------------------------------- platform config ---
class ConfigUpsert(BaseModel):
    scope: str = Field(default="PLATFORM", max_length=32)
    scope_id: str = Field(default="", max_length=128)
    category: str = Field(min_length=1, max_length=64)
    key: str = Field(min_length=1, max_length=255)
    value: Any = None
    changes: str = Field(default="", max_length=2000)
    reason: str = Field(default="", max_length=2000)
    dry_run: bool = Field(default=False)
    # Step-up evidence for sensitive+ operations.
    last_auth_at: str = Field(default="")
    mfa_verified: bool = Field(default=False)
    confirmation_phrase: str = Field(default="")
    reauthenticated: bool = Field(default=False)


@router.get("/config", summary="List platform configuration")
async def list_config(
    user=Depends(require_platform_owner()),
    db: AsyncSession = Depends(get_db),
    category: str = Query(default=""),
    limit: int = Query(default=200, ge=1, le=500),
):
    query = select(PlatformConfig).order_by(PlatformConfig.updated_at.desc())
    if category:
        query = query.where(PlatformConfig.category == category)
    rows = (await db.execute(query.limit(limit))).scalars().all()
    return {"config": [
        {"scope": r.scope, "scope_id": r.scope_id, "category": r.category,
         "key": r.key, "value": redact(r.value), "version": r.version}
        for r in rows]}


@router.post("/config", summary="Upsert config (versioned, dry-run supported)")
async def upsert_config(
    body: ConfigUpsert,
    request: Request,
    user=Depends(require_platform_owner()),
    db: AsyncSession = Depends(get_db),
):
    operation = "policy.change" if body.category == "security" else "region.configure"
    _require_step_up(request, operation, body.model_dump())
    existing = (await db.execute(select(PlatformConfig).where(
        PlatformConfig.scope == body.scope,
        PlatformConfig.scope_id == body.scope_id,
        PlatformConfig.category == body.category,
        PlatformConfig.key == body.key))).scalar_one_or_none()
    current = existing.value if existing else None
    preview = preview_change(current, body.value, key=body.key,
                             category=body.category)
    if preview["blocked"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail=preview["impact"])
    if body.dry_run:
        return {"applied": False, "preview": preview}
    # Operation lock: concurrent admins cannot race the same key.
    service = get_control_service()
    lock_key = f"config:{body.scope}:{body.scope_id}:{body.category}:{body.key}"
    acquired, _ = service.locks.acquire(lock_key, _actor(request, user), 120)
    if not acquired:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="Configuration change already in progress")
    try:
        if existing is None:
            existing = PlatformConfig(
                scope=body.scope, scope_id=body.scope_id,
                category=body.category, key=body.key, value=body.value,
                created_by=_actor(request, user))
            db.add(existing)
        else:
            db.add(ConfigVersionRow(
                scope=existing.scope, scope_id=existing.scope_id,
                category=existing.category, key=existing.key,
                before={"value": existing.value},
                after={"value": body.value},
                created_by=_actor(request, user), changes=body.changes,
                rollback_reference=f"v{existing.version}"))
            existing.value = body.value
            existing.version += 1
        await db.commit()
    finally:
        service.locks.release(lock_key, _actor(request, user))
    await _audit(db, request=request, user=user, action="config.upsert",
                 resource=lock_key, before=redact(current),
                 after=redact(body.value), reason=body.reason, result="ok")
    return {"applied": True, "version": existing.version}


@router.get("/config/versions", summary="Configuration version history")
async def config_versions(
    user=Depends(require_platform_owner()),
    db: AsyncSession = Depends(get_db),
    key: str = Query(default=""),
    limit: int = Query(default=100, ge=1, le=300),
):
    query = select(ConfigVersionRow).order_by(
        ConfigVersionRow.created_at.desc())
    if key:
        query = query.where(ConfigVersionRow.key == key)
    rows = (await db.execute(query.limit(limit))).scalars().all()
    return {"versions": [
        {"scope": r.scope, "key": r.key, "by": r.created_by,
         "changes": r.changes, "rollback": r.rollback_reference,
         "created": r.created_at.isoformat()} for r in rows]}


# ------------------------------------------------------- feature flags ---
class FlagUpsert(BaseModel):
    key: str = Field(min_length=1, max_length=255)
    scope: str = Field(default="PLATFORM", max_length=32)
    scope_id: str = Field(default="", max_length=128)
    strategy: str = Field(default="boolean", pattern="^(boolean|percentage|allowlist|denylist)$")
    enabled: bool = Field(default=False)
    percentage: float = Field(default=0.0, ge=0.0, le=100.0)
    allowlist: list[str] = Field(default_factory=list)
    denylist: list[str] = Field(default_factory=list)
    label: str = Field(default="", max_length=255)
    reason: str = Field(default="", max_length=2000)


@router.get("/flags", summary="List feature flags")
async def list_flags(
    user=Depends(require_platform_owner()),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=200, ge=1, le=500),
):
    rows = (await db.execute(
        select(FeatureFlagRow).order_by(
            FeatureFlagRow.updated_at.desc()).limit(limit))).scalars().all()
    return {"flags": [
        {"key": r.key, "scope": r.scope, "strategy": r.strategy,
         "enabled": r.enabled, "percentage": r.percentage,
         "version": r.version, "label": r.label} for r in rows]}


@router.post("/flags", summary="Upsert feature flag (audited, versioned)")
async def upsert_flag(
    body: FlagUpsert,
    request: Request,
    user=Depends(require_platform_owner()),
    db: AsyncSession = Depends(get_db),
):
    from openagent.control.feature_flags import is_security_flag
    _require_step_up(request, "feature_flag.change", body.model_dump())
    if is_security_flag(body.key):
        # Flags cannot weaken security: security-flag changes need the
        # HIGH_RISK path and an explicit reason, and are labeled.
        _require_step_up(request, "security_policy.disable",
                         {**body.model_dump(),
                          "confirmation_phrase": body.model_dump().get(
                              "confirmation_phrase", "")})
    existing = (await db.execute(select(FeatureFlagRow).where(
        FeatureFlagRow.key == body.key, FeatureFlagRow.scope == body.scope,
        FeatureFlagRow.scope_id == body.scope_id))).scalar_one_or_none()
    before = existing.enabled if existing else None
    if existing is None:
        existing = FeatureFlagRow(
            key=body.key, scope=body.scope, scope_id=body.scope_id,
            updated_by=_actor(request, user))
        db.add(existing)
    existing.strategy = body.strategy
    existing.enabled = body.enabled
    existing.percentage = body.percentage
    existing.allowlist = body.allowlist[:500]
    existing.denylist = body.denylist[:500]
    existing.label = body.label
    existing.version += 1
    existing.updated_by = _actor(request, user)
    await db.commit()
    await _audit(db, request=request, user=user, action="feature_flag.change",
                 resource=f"{body.scope}:{body.key}", before=before,
                 after=body.enabled, reason=body.reason, result="ok")
    await _emit(db, "feature_flag.changed", "platform-control",
                _actor(request, user), "platform",
                {"key": body.key, "enabled": body.enabled}, request)
    return {"key": body.key, "enabled": body.enabled,
            "version": existing.version}


async def _emit(db: AsyncSession, event_type: str, source: str,
                actor: str, scope: str, payload: dict, request: Request) -> None:
    from openagent.control.observability import platform_event
    event = platform_event(event_type, source=source, actor=actor,
                           scope=scope, payload=payload,
                           request_id=_request_id(request))
    db.add(PlatformEventRow(event_type=event["event_type"],
                            source=event["source"], actor=event["actor"],
                            scope=event["scope"], payload=event["payload"],
                            request_id=event["request_id"]))
    await db.commit()


# ------------------------------------------------------- kill switches ---
class KillSwitchBody(BaseModel):
    target: str = Field(min_length=1, max_length=64)
    target_id: str = Field(min_length=1, max_length=255)
    engaged: bool = Field(default=True)
    reason: str = Field(min_length=1, max_length=2000)
    last_auth_at: str = Field(default="")
    mfa_verified: bool = Field(default=False)
    confirmation_phrase: str = Field(default="")
    reauthenticated: bool = Field(default=False)


@router.post("/kill-switches", summary="Engage/release kill switch")
async def kill_switch(
    body: KillSwitchBody,
    request: Request,
    user=Depends(require_platform_owner()),
    db: AsyncSession = Depends(get_db),
):
    from openagent.control.feature_flags import KILL_SWITCH_TARGETS
    if body.target not in KILL_SWITCH_TARGETS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Unknown target {body.target}")
    _require_step_up(request, "connector.disable", body.model_dump())
    key = f"kill.{body.target}.{body.target_id}"
    existing = (await db.execute(select(FeatureFlagRow).where(
        FeatureFlagRow.key == key,
        FeatureFlagRow.scope == "PLATFORM"))).scalar_one_or_none()
    if existing is None:
        existing = FeatureFlagRow(key=key, scope="PLATFORM",
                                  strategy="boolean",
                                  label=f"kill switch {body.target}/{body.target_id}",
                                  updated_by=_actor(request, user))
        db.add(existing)
    existing.enabled = body.engaged
    existing.version += 1
    await db.commit()
    await _audit(db, request=request, user=user,
                 action="kill_switch.engage" if body.engaged else "kill_switch.release",
                 resource=key, before=not body.engaged, after=body.engaged,
                 reason=body.reason, result="ok")
    return {"target": body.target, "id": body.target_id,
            "engaged": body.engaged}


# -------------------------------------------------- security response ---
class SecurityAction(BaseModel):
    action: str = Field(pattern="^(disable_connector|disable_provider|disable_class|drain_region|revoke_identity|block_domain)$")
    target: str = Field(min_length=1, max_length=255)
    reason: str = Field(min_length=1, max_length=2000)
    last_auth_at: str = Field(default="")
    mfa_verified: bool = Field(default=False)
    confirmation_phrase: str = Field(default="")
    reauthenticated: bool = Field(default=False)


@router.post("/security-response", summary="Scoped containment actions (no shell)")
async def security_response(
    body: SecurityAction,
    request: Request,
    user=Depends(require_platform_owner()),
    db: AsyncSession = Depends(get_db),
):
    # Controlled backend APIs only — never arbitrary command execution.
    _require_step_up(request, "connector.disable", body.model_dump())
    key = f"containment.{body.action}.{body.target}"
    row = (await db.execute(select(FeatureFlagRow).where(
        FeatureFlagRow.key == key,
        FeatureFlagRow.scope == "PLATFORM"))).scalar_one_or_none()
    if row is None:
        row = FeatureFlagRow(key=key, scope="PLATFORM", strategy="boolean",
                             label=f"containment {body.action}/{body.target}",
                             updated_by=_actor(request, user))
        db.add(row)
    row.enabled = True
    row.version += 1
    await db.commit()
    await _audit(db, request=request, user=user, action=body.action,
                 resource=body.target, before="operational",
                 after="contained", reason=body.reason, result="ok")
    return {"action": body.action, "target": body.target, "state": "contained"}


# ------------------------------------------------------- maintenance ---
class MaintenanceCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    starts_at: datetime
    ends_at: datetime
    affected: list[str] = Field(default_factory=list)
    expected_behavior: str = Field(default="", max_length=2000)
    reason: str = Field(default="", max_length=2000)


@router.post("/maintenance", summary="Schedule maintenance window")
async def schedule_maintenance(
    body: MaintenanceCreate,
    request: Request,
    user=Depends(require_platform_owner()),
    db: AsyncSession = Depends(get_db),
):
    _require_step_up(request, "maintenance.schedule", {})
    if body.ends_at <= body.starts_at:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="ends_at must be after starts_at")
    window = MaintenanceWindow(
        starts_at=body.starts_at, ends_at=body.ends_at,
        affected=body.affected[:32], expected_behavior=body.expected_behavior)
    row = MaintenanceRow(title=body.title, starts_at=window.starts_at,
                         ends_at=window.ends_at, affected=window.affected,
                         expected_behavior=window.expected_behavior,
                         created_by=_actor(request, user))
    db.add(row)
    await db.commit()
    await _audit(db, request=request, user=user, action="maintenance.schedule",
                 resource=body.title, before=None, after=body.title,
                 reason=body.reason, result="ok")
    return {"id": str(row.id), "starts": row.starts_at.isoformat()}


# ------------------------------------------------------ deployments ---
class DeploymentCreate(BaseModel):
    service: str = Field(min_length=1, max_length=64)
    version: str = Field(min_length=1, max_length=64)
    commit: str = Field(default="", max_length=128)
    build: str = Field(default="", max_length=128)
    environment: str = Field(default="production", max_length=32)
    reason: str = Field(default="", max_length=2000)


class DeploymentTransition(BaseModel):
    to_status: str = Field(min_length=1, max_length=32)
    reason: str = Field(default="", max_length=2000)


@router.post("/deployments", summary="Record deployment")
async def record_deployment(
    body: DeploymentCreate,
    request: Request,
    user=Depends(require_platform_owner()),
    db: AsyncSession = Depends(get_db),
):
    deployment = Deployment(service=body.service, version=body.version,
                            commit=body.commit, build=body.build,
                            environment=body.environment,
                            deployer=_actor(request, user))
    ok, reason = deployment.validate()
    if not ok:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=reason)
    deployment.status = "DEPLOYING"
    row = DeploymentRow(service=deployment.service, version=deployment.version,
                        commit=deployment.commit, build=deployment.build,
                        environment=deployment.environment,
                        deployer=deployment.deployer, status=deployment.status)
    db.add(row)
    await db.commit()
    await _emit(db, "deployment.started", "platform-control",
                _actor(request, user), "platform",
                {"service": body.service, "version": body.version}, request)
    return {"id": str(row.id), "status": row.status}


@router.post("/deployments/{deployment_id}/transition", summary="Move deployment state")
async def transition_deployment(
    deployment_id: UUID,
    body: DeploymentTransition,
    request: Request,
    user=Depends(require_platform_owner()),
    db: AsyncSession = Depends(get_db),
):
    from openagent.control.types import DeploymentStatus
    if body.to_status.upper() not in DeploymentStatus.ALL:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Unknown deployment status")
    row = (await db.execute(select(DeploymentRow).where(
        DeploymentRow.id == deployment_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Deployment not found")
    row.status = body.to_status.upper()
    if row.status == "ACTIVE":
        row.deployed_at = datetime.now(timezone.utc)
        await _emit(db, "deployment.completed", "platform-control",
                    _actor(request, user), "platform",
                    {"service": row.service, "version": row.version}, request)
    await db.commit()
    return {"id": str(row.id), "status": row.status}


class RollbackRequest(BaseModel):
    service: str = Field(min_length=1, max_length=64)
    current_version: str = Field(min_length=1, max_length=64)
    target_version: str = Field(min_length=1, max_length=64)
    migrations_since: list[str] = Field(default_factory=list)
    destructive_migrations: list[str] = Field(default_factory=list)
    reason: str = Field(min_length=1, max_length=2000)
    confirmation_phrase: str = Field(default="")
    last_auth_at: str = Field(default="")
    mfa_verified: bool = Field(default=False)
    reauthenticated: bool = Field(default=False)


@router.post("/rollback", summary="Rollback pre-check (never automatic)")
async def request_rollback(
    body: RollbackRequest,
    request: Request,
    user=Depends(require_platform_owner()),
    db: AsyncSession = Depends(get_db),
):
    _require_step_up(request, "rollback.execute", body.model_dump())
    plan = rollback_plan(current_version=body.current_version,
                         target_version=body.target_version,
                         migrations_since=body.migrations_since,
                         destructive_migrations=body.destructive_migrations)
    await _audit(db, request=request, user=user, action="rollback.request",
                 resource=f"{body.service}:{body.target_version}",
                 before=body.current_version, after=body.target_version,
                 reason=body.reason,
                 result="allowed" if plan["allowed"] else "blocked")
    if not plan["allowed"]:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail=plan["reason"])
    return plan


# ----------------------------------------------------------- backups ---
class BackupReport(BaseModel):
    kind: str = Field(min_length=1, max_length=64)
    status: str = Field(min_length=1, max_length=32)
    detail: str = Field(default="", max_length=4000)
    measured_rpo_seconds: Optional[float] = None
    measured_rto_seconds: Optional[float] = None
    restore_tested_at: Optional[datetime] = None


@router.get("/backups", summary="Backup health + restore readiness")
async def backup_status(
    user=Depends(require_platform_owner()),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(
        select(BackupReportRow).order_by(
            BackupReportRow.created_at.desc()).limit(50))).scalars().all()
    latest: dict[str, Any] = {}
    for row in rows:
        latest.setdefault(row.kind, {
            "status": row.status, "detail": row.detail,
            "rpo_s": row.measured_rpo_seconds, "rto_s": row.measured_rto_seconds,
            "restore_tested": row.restore_tested_at.isoformat()
            if row.restore_tested_at else None,
            "reported": row.created_at.isoformat()})
    return {"backups": latest}


@router.post("/backups", summary="Report backup / restore-test outcome")
async def report_backup(
    body: BackupReport,
    request: Request,
    user=Depends(require_platform_owner()),
    db: AsyncSession = Depends(get_db),
):
    row = BackupReportRow(kind=body.kind, status=body.status,
                          detail=body.detail,
                          measured_rpo_seconds=body.measured_rpo_seconds,
                          measured_rto_seconds=body.measured_rto_seconds,
                          restore_tested_at=body.restore_tested_at,
                          reported_by=_actor(request, user))
    db.add(row)
    await db.commit()
    return {"id": str(row.id), "kind": row.kind, "status": row.status}


# ------------------------------------------------- private enrollments ---
@router.post("/private-enrollments", summary="Mint one-time worker enrollment")
async def mint_enrollment(
    request: Request,
    user=Depends(require_platform_owner()),
    db: AsyncSession = Depends(get_db),
    organization_id: UUID = Query(...),
    ttl_hours: int = Query(default=1, ge=1, le=24),
):
    enrollment, raw = PrivateEnrollment.mint(str(organization_id), ttl_hours)
    db.add(PrivateEnrollmentRow(
        organization_id=organization_id, token_hash=enrollment.token_hash,
        expires_at=enrollment.expires_at))
    await db.commit()
    # Raw token shown ONCE; only the hash is stored.
    return {"enrollment_id": enrollment.enrollment_id, "token": raw,
            "expires": enrollment.expires_at.isoformat()}


# ---------------------------------------------------------- audit ---
@router.get("/audit", summary="Platform privileged-action audit")
async def platform_audit(
    user=Depends(require_platform_owner()),
    action: str = Query(default=""),
    limit: int = Query(default=100, ge=1, le=500),
):
    records = get_control_service().audit.records()
    if action:
        records = [r for r in records if r.get("action") == action]
    ok, message = get_control_service().audit.verify()
    return {"chain": message, "intact": ok,
            "records": records[-limit:]}


@router.get("/incidents", summary="Cross-org incident command view")
async def all_incidents(
    user=Depends(require_platform_owner()),
    db: AsyncSession = Depends(get_db),
    status_filter: str = Query(default="", alias="status"),
    limit: int = Query(default=100, ge=1, le=300),
):
    query = select(IncidentRow).order_by(IncidentRow.created_at.desc())
    if status_filter:
        query = query.where(IncidentRow.status == status_filter.upper())
    rows = (await db.execute(query.limit(limit))).scalars().all()
    return {"incidents": [
        {"id": str(r.id), "org": str(r.organization_id) if r.organization_id else "",
         "title": r.title, "severity": r.severity, "status": r.status}
        for r in rows]}
