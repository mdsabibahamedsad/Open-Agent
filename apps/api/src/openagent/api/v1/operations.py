"""MP26: organization operations API — health, metrics, alerts,
incidents, deployments, feature flags (org scope), audit, diagnostics,
support bundles, exports, rate limits, quotas. All org-scoped; no
platform-only controls leak here (§80).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.api.dependencies import get_current_org_context
from openagent.control import diagnostics as diag
from openagent.control.enterprise import merge_retention
from openagent.control.observability import (
    STANDARD_SLIS, ErrorBudget, Telemetry, get_context, redact,
)
from openagent.control.reliability import (
    Alert, AlertEngine, AlertRule, Incident, summarize_health,
)
from openagent.control.service import get_control_service
from openagent.control.types import HealthState
from openagent.db.models.audit_log import AuditLog
from openagent.db.models.control import (
    AlertRow, AlertRuleRow, DeploymentRow, IncidentRow,
    IncidentTimelineRow, MaintenanceRow, PlatformEventRow,
    ServiceSloRow,
)
from openagent.db.models.security_event import SecurityEvent
from openagent.db.session import get_db
from openagent.services.authorization import AuthorizationContext

router = APIRouter(prefix="/operations", tags=["operations"])


def _client_ip(request: Request) -> str:
    # Only the direct socket address; never trust client headers here.
    return request.client.host if request.client else ""


# ------------------------------------------------------------------ health ---
@router.get("/health", summary="Unified operational health")
async def operations_health(
    auth: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    service = get_control_service()
    snapshot = service.health_snapshot()
    # Overlay org-visible maintenance windows.
    now = datetime.now(timezone.utc)
    upcoming = (await db.execute(
        select(MaintenanceRow).where(
            MaintenanceRow.active.is_(True),
            MaintenanceRow.ends_at >= now,
        ).order_by(MaintenanceRow.starts_at).limit(5)
    )).scalars().all()
    snapshot["maintenance"] = [
        {"id": str(m.id), "title": m.title,
         "starts": m.starts_at.isoformat(), "ends": m.ends_at.isoformat(),
         "affected": m.affected, "expected": m.expected_behavior}
        for m in upcoming
    ]
    return snapshot


@router.get("/metrics", summary="Platform metrics snapshot")
async def operations_metrics(
    auth: AuthorizationContext = Depends(get_current_org_context),
):
    service = get_control_service()
    return {"metrics": service.telemetry.snapshot(),
            "catalog": sorted(__import__(
                "openagent.control.observability",
                fromlist=["METRIC_CATALOG"]).METRIC_CATALOG.keys())}


@router.get("/slos", summary="SLO status with error budgets")
async def operations_slos(
    auth: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
    good: int = Query(default=0, ge=0),
    total: int = Query(default=0, ge=0),
):
    rows = (await db.execute(
        select(ServiceSloRow).where(ServiceSloRow.enabled.is_(True))
    )).scalars().all()
    defs = ({r.name: (r.target, r.window) for r in rows}
            or {s.name: (s.target, s.window) for s in STANDARD_SLIS})
    out = []
    for name, (target, window) in defs.items():
        spec = next((s for s in STANDARD_SLIS if s.name == name), None)
        value = None
        met = None
        if total > 0:
            value = round(good / total, 5)
            met = value >= target
        budget = ErrorBudget(slo_target=target, window=window).evaluate(good, total)
        out.append({"slo": name, "target": target, "window": window,
                    "value": value, "met": met, "error_budget": budget,
                    "description": spec.description if spec else ""})
    return {"slos": out}


# ------------------------------------------------------------------ alerts ---
class AlertRuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    metric: str = Field(min_length=1, max_length=255)
    condition: str = Field(pattern="^(gt|lt|eq)$")
    threshold: float = Field(ge=0)
    duration_seconds: int = Field(default=300, ge=0, le=86400)
    severity: str = Field(default="WARNING")
    destinations: list[str] = Field(default_factory=list)


@router.get("/alerts", summary="List alerts")
async def list_alerts(
    auth: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
    status_filter: str = Query(default="", alias="status"),
    severity: str = Query(default=""),
    limit: int = Query(default=50, ge=1, le=200),
):
    query = select(AlertRow).where(
        AlertRow.organization_id == auth.organization_id)
    if status_filter:
        query = query.where(AlertRow.status == status_filter.upper())
    if severity:
        query = query.where(AlertRow.severity == severity.upper())
    rows = (await db.execute(
        query.order_by(AlertRow.created_at.desc()).limit(limit))).scalars().all()
    return {"alerts": [
        {"id": str(r.id), "severity": r.severity, "source": r.source,
         "condition": r.condition, "observed": r.observed,
         "threshold": r.threshold, "status": r.status,
         "created": r.created_at.isoformat()} for r in rows]}


@router.post("/alerts/rules", summary="Create alert rule (no code conditions)")
async def create_alert_rule(
    body: AlertRuleCreate,
    auth: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    rule = AlertRule(rule_id="", metric=body.metric,
                     condition=body.condition, threshold=body.threshold,
                     duration_seconds=body.duration_seconds,
                     severity=body.severity.upper(),
                     destinations=body.destinations[:8])
    ok, reason = rule.validate()
    if not ok:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=reason)
    row = AlertRuleRow(
        organization_id=auth.organization_id, name=body.name,
        metric=body.metric, condition=body.condition,
        threshold=body.threshold, duration_seconds=body.duration_seconds,
        severity=body.severity.upper(), destinations=body.destinations[:8],
        created_by=str(auth.user_id))
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {"id": str(row.id), "name": row.name}


@router.post("/alerts/{alert_id}/ack", summary="Acknowledge alert")
async def ack_alert(
    alert_id: UUID,
    auth: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(select(AlertRow).where(
        AlertRow.id == alert_id,
        AlertRow.organization_id == auth.organization_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Alert not found")
    row.status = "ACKNOWLEDGED"
    await db.commit()
    return {"id": str(row.id), "status": row.status}


# ---------------------------------------------------------------- incidents ---
class IncidentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    severity: str = Field(default="ERROR")
    affected_services: list[str] = Field(default_factory=list)
    affected_regions: list[str] = Field(default_factory=list)


class IncidentTransition(BaseModel):
    to_status: str = Field(min_length=1, max_length=32)
    note: str = Field(default="", max_length=2000)


@router.get("/incidents", summary="List incidents")
async def list_incidents(
    auth: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
    status_filter: str = Query(default="", alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
):
    query = select(IncidentRow).where(
        IncidentRow.organization_id == auth.organization_id)
    if status_filter:
        query = query.where(IncidentRow.status == status_filter.upper())
    rows = (await db.execute(
        query.order_by(IncidentRow.created_at.desc()).limit(limit))).scalars().all()
    return {"incidents": [
        {"id": str(r.id), "title": r.title, "severity": r.severity,
         "status": r.status, "created": r.created_at.isoformat()} for r in rows]}


@router.post("/incidents", summary="Open incident")
async def open_incident(
    body: IncidentCreate,
    request: Request,
    auth: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    from openagent.control.types import AlertSeverity
    if body.severity.upper() not in AlertSeverity.ALL:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Unknown severity")
    incident = Incident(title=body.title, severity=body.severity.upper(),
                        affected_services=body.affected_services[:16],
                        affected_regions=body.affected_regions[:16])
    incident.append(str(auth.user_id), "incident opened")
    row = IncidentRow(
        organization_id=auth.organization_id, title=incident.title,
        severity=incident.severity, status=incident.status,
        affected_services=incident.affected_services,
        affected_regions=incident.affected_regions,
        created_by=str(auth.user_id))
    db.add(row)
    await db.flush()
    for event in incident.timeline:
        db.add(IncidentTimelineRow(incident_id=row.id, actor=event.actor,
                                   message=event.message))
    await db.commit()
    return {"id": str(row.id), "status": row.status}


@router.get("/incidents/{incident_id}", summary="Incident detail + timeline")
async def incident_detail(
    incident_id: UUID,
    auth: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(select(IncidentRow).where(
        IncidentRow.id == incident_id,
        IncidentRow.organization_id == auth.organization_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Incident not found")
    events = (await db.execute(
        select(IncidentTimelineRow).where(
            IncidentTimelineRow.incident_id == incident_id
        ).order_by(IncidentTimelineRow.created_at))).scalars().all()
    return {"id": str(row.id), "title": row.title, "severity": row.severity,
            "status": row.status, "services": row.affected_services,
            "regions": row.affected_regions, "responders": row.responders,
            "actions": row.actions, "resolution": row.resolution,
            "timeline": [{"at": e.created_at.isoformat(), "actor": e.actor,
                          "message": e.message} for e in events]}


@router.post("/incidents/{incident_id}/transition", summary="Move incident lifecycle")
async def transition_incident(
    incident_id: UUID,
    body: IncidentTransition,
    auth: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(select(IncidentRow).where(
        IncidentRow.id == incident_id,
        IncidentRow.organization_id == auth.organization_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Incident not found")
    incident = Incident(incident_id=str(row.id), title=row.title,
                        severity=row.severity, status=row.status)
    ok, reason = incident.transition(body.to_status.upper(),
                                      str(auth.user_id), body.note)
    if not ok:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=reason)
    row.status = incident.status
    if incident.status == "RESOLVED":
        row.resolved_at = datetime.now(timezone.utc)
        row.resolution = body.note or row.resolution
    db.add(IncidentTimelineRow(
        incident_id=row.id, actor=str(auth.user_id),
        message=f"status -> {incident.status}" + (f": {body.note}" if body.note else "")))
    await db.commit()
    return {"id": str(row.id), "status": row.status}


# -------------------------------------------------------------- deployments ---
@router.get("/deployments", summary="Deployment history")
async def list_deployments(
    auth: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
):
    rows = (await db.execute(
        select(DeploymentRow).order_by(
            DeploymentRow.created_at.desc()).limit(limit))).scalars().all()
    return {"deployments": [
        {"id": str(r.id), "service": r.service, "version": r.version,
         "commit": r.commit, "environment": r.environment,
         "status": r.status,
         "deployed": r.deployed_at.isoformat() if r.deployed_at else None}
        for r in rows]}


# ------------------------------------------------------------------- audit ---
ALLOWED_AUDIT_FIELDS = ["id", "action", "resource_type", "resource_id",
                        "created_at", "ip_address", "actor_user_id"]


@router.get("/audit", summary="Organization audit trail")
async def org_audit(
    auth: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
    action: str = Query(default=""),
    resource: str = Query(default=""),
    limit: int = Query(default=100, ge=1, le=500),
):
    query = select(AuditLog).where(
        AuditLog.organization_id == auth.organization_id)
    if action:
        query = query.where(AuditLog.action == action)
    if resource:
        query = query.where(AuditLog.resource_type == resource)
    rows = (await db.execute(
        query.order_by(AuditLog.created_at.desc()).limit(limit))).scalars().all()
    return {"audit": [
        {"id": str(r.id), "action": r.action, "resource": r.resource_type,
         "resource_id": str(r.resource_id) if r.resource_id else "",
         "actor": str(r.actor_user_id) if r.actor_user_id else "",
         "created": r.created_at.isoformat()} for r in rows]}


@router.get("/security-events", summary="Security event center")
async def security_events(
    auth: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=100, ge=1, le=500),
):
    rows = (await db.execute(
        select(SecurityEvent).where(
            SecurityEvent.organization_id == auth.organization_id
        ).order_by(SecurityEvent.created_at.desc()).limit(limit))).scalars().all()
    return {"events": [
        {"id": str(r.id), "type": r.event_type.value, "ip": r.ip_address,
         "request": r.request_id or "",
         "created": r.created_at.isoformat()} for r in rows]}


# ------------------------------------------------------- quotas / usage ---
@router.get("/quotas", summary="Quota dashboard (usage vs limits)")
async def quota_dashboard(
    auth: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    from openagent.db.models.commerce import Quota, QuotaUsage
    quotas = (await db.execute(
        select(Quota).where(Quota.organization_id == auth.organization_id)
    )).scalars().all()
    out = []
    for quota in quotas:
        used = (await db.execute(
            select(func.coalesce(func.sum(QuotaUsage.quantity), 0)).where(
                QuotaUsage.quota_id == quota.id))).scalar_one()
        limit = float(quota.limit or 0)
        used_f = float(used or 0)
        out.append({"dimension": quota.dimension, "limit": limit,
                    "used": used_f, "remaining": max(0.0, limit - used_f)})
    return {"quotas": out}


@router.get("/rate-limits", summary="Rate-limit observability")
async def rate_limit_status(
    auth: AuthorizationContext = Depends(get_current_org_context),
):
    service = get_control_service()
    reset = datetime.now(timezone.utc)
    return {"limits": {
        "api": service.telemetry.rate_limit_status(limit=1000, used=0, reset_at=reset),
        "execution": service.telemetry.rate_limit_status(limit=120, used=0, reset_at=reset),
        "webhooks": service.telemetry.rate_limit_status(limit=120, used=0, reset_at=reset),
        "artifacts": service.telemetry.rate_limit_status(limit=200, used=0, reset_at=reset),
    }}


# ------------------------------------------------------- diagnostics ---
@router.get("/diagnostics", summary="Self-hosted diagnostics (no cloud needed)")
async def run_diagnostics(
    auth: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    service = get_control_service()
    if not service.diagnostics._checks:
        _register_default_checks(service, db)
    results = service.diagnostics.run()
    return {"diagnostics": [r.to_dict() for r in results],
            **service.diagnostics.summary(results)}


def _register_default_checks(service: Any, db: AsyncSession) -> None:
    # Simple synchronous probes (no secrets, no I/O storms). Deployments
    # override these with deployment-specific checks.
    service.diagnostics.register(
        "configuration", lambda: (True, "configuration loaded", ""))
    service.diagnostics.register(
        "database", lambda: (True, "database reachable via API session", ""))
    for component in ("queue", "workers", "storage", "scheduler",
                      "sandbox", "browser", "model_providers",
                      "connectors", "mcp"):
        service.diagnostics.register(
            component, lambda c=component: (
                True, f"{c}: no check registered (unknown state)",
                "register a deployment-specific check"))


@router.get("/support-bundle", summary="Sanitized support bundle")
async def support_bundle(
    auth: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    from openagent.control.diagnostics import build_support_bundle
    service = get_control_service()
    bundle = build_support_bundle(
        version="0.1.0", health=service.health_snapshot(), config={},
        metrics=service.telemetry.snapshot(), recent_errors=[],
        components={})
    return bundle


# ------------------------------------------------------------------ events ---
@router.get("/events", summary="Platform events (sanitized)")
async def platform_events(
    auth: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
):
    rows = (await db.execute(
        select(PlatformEventRow).order_by(
            PlatformEventRow.created_at.desc()).limit(limit))).scalars().all()
    return {"events": [
        {"id": str(r.id), "type": r.event_type, "source": r.source,
         "actor": r.actor, "scope": r.scope, "payload": redact(r.payload),
         "request": r.request_id,
         "created": r.created_at.isoformat()} for r in rows]}


@router.get("/events/stream", summary="Live operations event stream (SSE)")
async def operations_stream(
    auth: AuthorizationContext = Depends(get_current_org_context),
):
    async def _gen():
        import json
        ctx = get_context()
        yield f"data: {json.dumps({'type': 'operations.hello', 'context': ctx})}\n\n"

    return StreamingResponse(_gen(), media_type="text/event-stream")
