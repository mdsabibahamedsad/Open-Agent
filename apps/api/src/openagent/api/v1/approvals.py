"""Human approval, guardrail policy & delegation API (MP19).

Tenant isolation is enforced by comparing the path organization_id against
the authenticated org context. RBAC reuses existing permissions plus the new
granular approval:* set. All state transitions go through ApprovalEngine —
there is no endpoint that writes approval status directly.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.api.dependencies import get_current_org_context
from openagent.approvals.delegation import validate_delegation
from openagent.approvals.engine import ApprovalEngine, ApprovalError, CreateRequest
from openagent.approvals.guard import action_context_for_tool
from openagent.approvals.policy import evaluate_policies
from openagent.approvals.risk import evaluate_risk
from openagent.approvals.taxonomy import all_categories
from openagent.approvals.types import ApprovalKind
from openagent.db.models.approval import (Approval, ApprovalDelegation, ApprovalEvent,
                                           ApprovalPolicy, ApprovalPolicyVersion,
                                           ApprovalStatus)
from openagent.db.session import get_db
from openagent.services.authorization import AuthorizationContext, AuthorizationService

router = APIRouter(prefix="/organizations/{organization_id}/approvals", tags=["approvals"])
policies_router = APIRouter(prefix="/organizations/{organization_id}/approval-policies",
                            tags=["approval-policies"])


def _org_or_403(ctx: AuthorizationContext, organization_id: UUID) -> None:
    if ctx.organization_id != organization_id and not ctx.is_platform_owner:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Cross-organization access denied")


def _serialize(a: Approval) -> dict[str, Any]:
    p = a.payload or {}
    return {"id": str(a.id), "organization_id": str(a.organization_id),
            "status": str(a.status.value if hasattr(a.status, "value") else a.status).upper(),
            "approval_type": str(a.approval_type.value if hasattr(a.approval_type, "value")
                                 else a.approval_type),
            "action_type": p.get("action_type"), "action_category": p.get("action_category"),
            "action_description": p.get("action_description"),
            "risk_level": p.get("risk_level"), "risk_score": p.get("risk_score"),
            "risk_reasons": p.get("risk_reasons", []),
            "policy_decision": p.get("policy_decision"),
            "policy_version": p.get("policy_version"),
            "approval_kind": p.get("approval_kind", "SINGLE"),
            "required_approvals": p.get("required_approvals", 1),
            "required_role": p.get("required_role"),
            "target_type": p.get("target_type"), "target_id": p.get("target_id"),
            "target_reference": p.get("target_reference"),
            "requested_parameters": p.get("requested_parameters", {}),
            "impact_summary": p.get("impact_summary", ""),
            "requester_type": p.get("requester_type"), "requester_id": p.get("requester_id"),
            "agent_id": p.get("agent_id"), "agent_run_id": p.get("agent_run_id"),
            "workflow_id": p.get("workflow_id"),
            "workflow_execution_id": p.get("workflow_execution_id"),
            "task_id": p.get("task_id"),
            "approved_by": str(a.approved_by) if a.approved_by else None,
            "approval_reason": p.get("approval_reason"),
            "rejection_reason": p.get("rejection_reason"),
            "escalation_chain": p.get("escalation_chain", []),
            "use_count": p.get("use_count", 0), "max_uses": p.get("max_uses", 1),
            "requested_at": a.created_at.isoformat() if a.created_at else None,
            "expires_at": a.expires_at.isoformat() if a.expires_at else None,
            "resolved_at": a.resolved_at.isoformat() if a.resolved_at else None,
            "created_at": a.created_at.isoformat() if a.created_at else None,
            "updated_at": a.updated_at.isoformat() if a.updated_at else None}


def _err(exc: ApprovalError) -> HTTPException:
    code_map = {"NOT_FOUND": 404, "CROSS_TENANT": 403, "SELF_APPROVAL": 403,
                "EXPIRED": 410, "NOT_APPROVED": 409, "REPLAY": 409,
                "INVALID_APPROVAL": 409, "INVALID_STATE": 409,
                "ILLEGAL_TRANSITION": 409, "ESCALATION_LOOP": 409}
    return HTTPException(status_code=code_map.get(exc.code, 400), detail=str(exc))


# -- schemas ---------------------------------------------------------------
class ApprovalCreate(BaseModel):
    action_type: str = Field(min_length=1, max_length=255)
    action_category: str = Field(default="WRITE", max_length=64)
    requested_action: Optional[str] = None
    requested_params: dict[str, Any] = Field(default_factory=dict)
    target_type: str = Field(default="", max_length=255)
    target_id: str = Field(default="", max_length=512)
    target_reference: str = Field(default="", max_length=1024)
    impact_summary: str = Field(default="", max_length=4000)
    action_description: str = Field(default="", max_length=4000)
    requester_type: str = Field(default="agent", max_length=50)
    agent_id: Optional[UUID] = None
    agent_run_id: Optional[UUID] = None
    workflow_id: Optional[UUID] = None
    workflow_execution_id: Optional[UUID] = None
    task_id: Optional[str] = Field(default=None, max_length=255)
    team_id: Optional[UUID] = None
    environment: str = Field(default="development", max_length=50)
    approval_kind: str = Field(default="SINGLE", max_length=30)
    required_approvals: int = Field(default=1, ge=1, le=10)
    required_role: Optional[str] = Field(default=None, max_length=100)
    expires_in_seconds: int = Field(default=4 * 3600, ge=60, le=7 * 24 * 3600)


class DecisionInput(BaseModel):
    reason: str = Field(default="", max_length=4000)
    idempotency_key: Optional[str] = Field(default=None, max_length=100)


class EscalateInput(BaseModel):
    reason: str = Field(default="", max_length=2000)
    escalate_to: str = Field(default="organization_admin", max_length=100)


class SimulateInput(BaseModel):
    action_type: str = Field(min_length=1, max_length=255)
    action_category: str = Field(default="WRITE", max_length=64)
    target_type: str = Field(default="", max_length=255)
    target_id: str = Field(default="", max_length=512)
    environment: str = Field(default="development", max_length=50)
    tool_name: str = Field(default="", max_length=255)
    agent_trust: str = Field(default="ORGANIZATION", max_length=30)
    tool_trust: str = Field(default="ORGANIZATION", max_length=30)


class PolicyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    level: str = Field(default="organization", max_length=30)
    team_id: Optional[UUID] = None
    agent_id: Optional[UUID] = None
    rules: list[dict[str, Any]] = Field(default_factory=list)
    is_active: bool = True


class PolicyUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    rules: Optional[list[dict[str, Any]]] = None
    is_active: Optional[bool] = None


class DelegationCreate(BaseModel):
    delegate_id: UUID
    scope: str = Field(min_length=1, max_length=200)
    expires_at: datetime


# -- approval CRUD ---------------------------------------------------------
@router.get("", summary="List approval requests")
async def list_approvals(organization_id: UUID,
                         status_filter: Optional[str] = Query(default=None, alias="status"),
                         risk_level: Optional[str] = None,
                         limit: int = Query(default=50, ge=1, le=200),
                         offset: int = Query(default=0, ge=0),
                         db: AsyncSession = Depends(get_db),
                         ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_permission(ctx, "approval:read")
    q = select(Approval).where(Approval.organization_id == organization_id)
    if status_filter:
        try:
            q = q.where(Approval.status == ApprovalStatus(status_filter.lower()))
        except ValueError:
            raise HTTPException(status_code=400, detail="Unknown status")
    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar() or 0
    rows = (await db.execute(q.order_by(Approval.created_at.desc())
                             .limit(limit).offset(offset))).scalars().all()
    return {"items": [_serialize(a) for a in rows], "total": total,
            "limit": limit, "offset": offset}


@router.post("", status_code=201, summary="Request approval (usually via guard, not agents)")
async def create_approval(organization_id: UUID, body: ApprovalCreate,
                          db: AsyncSession = Depends(get_db),
                          ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_permission(ctx, "approval:create")
    try:
        kind = ApprovalKind(body.approval_kind.upper())
    except ValueError:
        raise HTTPException(status_code=400, detail="Unknown approval kind")
    engine = ApprovalEngine(db)
    try:
        approval = await engine.create_request(CreateRequest(
            organization_id=organization_id, action_type=body.action_type,
            action_category=body.action_category.upper(),
            requested_action=body.requested_action or body.action_type,
            requested_params=body.requested_params, target_type=body.target_type,
            target_id=body.target_id, target_reference=body.target_reference,
            impact_summary=body.impact_summary, action_description=body.action_description,
            requester_type=body.requester_type, requester_id=str(ctx.user_id),
            agent_id=body.agent_id, agent_run_id=body.agent_run_id,
            workflow_id=body.workflow_id,
            workflow_execution_id=body.workflow_execution_id, task_id=body.task_id,
            team_id=body.team_id, environment=body.environment,
            approval_kind=kind, required_approvals=body.required_approvals,
            required_role=body.required_role,
            expires_in_seconds=body.expires_in_seconds))
        await db.commit()
    except ApprovalError as exc:
        raise _err(exc)
    return _serialize(approval)


@router.get("/taxonomy", summary="Action taxonomy + risk defaults")
async def get_taxonomy(organization_id: UUID,
                       db: AsyncSession = Depends(get_db),
                       ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_permission(ctx, "approval:read")
    from openagent.approvals.taxonomy import HIGH_RISK_DEFAULTS
    return {"categories": all_categories(), "high_risk_defaults": HIGH_RISK_DEFAULTS,
            "note": "Unknown categories are deny-by-default (REQUIRE_APPROVAL)."}


@router.post("/simulate", summary="Policy simulator (never executes)")
async def simulate(organization_id: UUID, body: SimulateInput,
                   db: AsyncSession = Depends(get_db),
                   ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_permission(ctx, "approval:read")
    actx = action_context_for_tool(tool_name=body.tool_name or body.action_type,
                                   arguments={"target": body.target_id},
                                   organization_id=organization_id,
                                   environment=body.environment,
                                   agent_trust=body.agent_trust, tool_trust=body.tool_trust)
    actx.action_category = body.action_category.upper()
    actx.target_type = body.target_type
    actx.target_id = body.target_id
    risk = evaluate_risk(actx)
    evaluation = evaluate_policies(ctx=actx, risk=risk)
    return {"decision": evaluation.decision.value, "risk_level": risk.risk_level.value,
            "risk_score": risk.risk_score, "reasons": risk.reasons + evaluation.reasons,
            "approval_type": evaluation.approval_kind.value,
            "required_role": evaluation.required_role, "executed": False}


@router.get("/{approval_id}", summary="Get approval detail")
async def get_approval(organization_id: UUID, approval_id: UUID,
                       db: AsyncSession = Depends(get_db),
                       ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_permission(ctx, "approval:read")
    result = await db.execute(select(Approval).where(Approval.id == approval_id))
    approval = result.scalar_one_or_none()
    if approval is None or approval.organization_id != organization_id:
        raise HTTPException(status_code=404, detail="Approval not found")
    data = _serialize(approval)
    events = (await db.execute(select(ApprovalEvent)
                               .where(ApprovalEvent.approval_id == approval_id)
                               .order_by(ApprovalEvent.created_at))).scalars().all()
    data["audit_timeline"] = [{"type": e.event_type, "at": e.created_at.isoformat()
                               if e.created_at else None,
                               "actor_type": e.actor_type, "actor_id": e.actor_id,
                               "data": e.event_data} for e in events]
    return data


@router.post("/{approval_id}/approve", summary="Approve (human only, never the requester)")
async def approve(organization_id: UUID, approval_id: UUID, body: DecisionInput,
                  db: AsyncSession = Depends(get_db),
                  ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_permission(ctx, "approval:approve")
    if ctx.is_service_account:
        raise HTTPException(status_code=403,
                            detail="Service identities cannot approve their own actions")
    try:
        approval = await ApprovalEngine(db).approve(
            approval_id, organization_id=organization_id, approver_id=ctx.user_id,
            reason=body.reason, idempotency_key=body.idempotency_key)
        await db.commit()
    except ApprovalError as exc:
        raise _err(exc)
    return _serialize(approval)


@router.post("/{approval_id}/reject", summary="Reject approval")
async def reject(organization_id: UUID, approval_id: UUID, body: DecisionInput,
                 db: AsyncSession = Depends(get_db),
                 ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_permission(ctx, "approval:approve")
    try:
        approval = await ApprovalEngine(db).reject(
            approval_id, organization_id=organization_id, rejecter_id=ctx.user_id,
            reason=body.reason)
        await db.commit()
    except ApprovalError as exc:
        raise _err(exc)
    return _serialize(approval)


@router.post("/{approval_id}/cancel", summary="Cancel approval")
async def cancel(organization_id: UUID, approval_id: UUID, body: DecisionInput,
                 db: AsyncSession = Depends(get_db),
                 ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_any_permission(ctx, ["approval:cancel", "approval:approve"])
    try:
        approval = await ApprovalEngine(db).cancel(
            approval_id, organization_id=organization_id, actor_id=ctx.user_id,
            reason=body.reason)
        await db.commit()
    except ApprovalError as exc:
        raise _err(exc)
    return _serialize(approval)


@router.post("/{approval_id}/escalate", summary="Escalate approval")
async def escalate(organization_id: UUID, approval_id: UUID, body: EscalateInput,
                   db: AsyncSession = Depends(get_db),
                   ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_any_permission(ctx, ["approval:escalate", "approval:approve"])
    try:
        approval = await ApprovalEngine(db).escalate(
            approval_id, organization_id=organization_id, actor_id=ctx.user_id,
            reason=body.reason, escalate_to=body.escalate_to)
        await db.commit()
    except ApprovalError as exc:
        raise _err(exc)
    return _serialize(approval)


@router.get("/{approval_id}/history", summary="Approval audit timeline")
async def history(organization_id: UUID, approval_id: UUID,
                  db: AsyncSession = Depends(get_db),
                  ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_permission(ctx, "approval:read")
    result = await db.execute(select(Approval).where(Approval.id == approval_id))
    approval = result.scalar_one_or_none()
    if approval is None or approval.organization_id != organization_id:
        raise HTTPException(status_code=404, detail="Approval not found")
    events = (await db.execute(select(ApprovalEvent)
                               .where(ApprovalEvent.approval_id == approval_id)
                               .order_by(ApprovalEvent.created_at))).scalars().all()
    return {"approval_id": str(approval_id),
            "events": [{"type": e.event_type, "at": e.created_at.isoformat()
                        if e.created_at else None, "actor_type": e.actor_type,
                        "actor_id": e.actor_id, "data": e.event_data} for e in events]}


# -- policies --------------------------------------------------------------
@policies_router.get("", summary="List guardrail policies")
async def list_policies(organization_id: UUID,
                        db: AsyncSession = Depends(get_db),
                        ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_permission(ctx, "approval:read")
    rows = (await db.execute(select(ApprovalPolicy)
                             .where(ApprovalPolicy.organization_id == organization_id)
                             .order_by(ApprovalPolicy.created_at.desc()))).scalars().all()
    return {"items": [{"id": str(p.id), "name": p.name, "level": p.level,
                       "rules": p.rules, "is_active": p.is_active,
                       "version": p.version} for p in rows]}


@policies_router.post("", status_code=201, summary="Create guardrail policy")
async def create_policy(organization_id: UUID, body: PolicyCreate,
                        db: AsyncSession = Depends(get_db),
                        ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_permission(ctx, "approval:admin")
    if body.level not in ("organization", "team", "agent", "workflow", "tool"):
        raise HTTPException(status_code=400, detail="Unknown policy level")
    for rule in body.rules:
        if not isinstance(rule, dict) or "decision" not in rule:
            raise HTTPException(status_code=400,
                                detail="Each rule needs a decision and optional safe 'when' clause")
        if "code" in rule or "exec" in rule or "eval" in rule:
            raise HTTPException(status_code=400,
                                detail="Executable policy code is not allowed")
    policy = ApprovalPolicy(organization_id=organization_id, team_id=body.team_id,
                            agent_id=body.agent_id, name=body.name, level=body.level,
                            rules=body.rules, is_active=body.is_active, version=1)
    db.add(policy)
    await db.flush()
    db.add(ApprovalPolicyVersion(policy_id=policy.id, organization_id=organization_id,
                                 version=1, rules=body.rules))
    await db.commit()
    return {"id": str(policy.id), "name": policy.name, "level": policy.level,
            "rules": policy.rules, "version": 1}


@policies_router.patch("/{policy_id}", summary="Update guardrail policy (versioned)")
async def update_policy(organization_id: UUID, policy_id: UUID, body: PolicyUpdate,
                        db: AsyncSession = Depends(get_db),
                        ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_permission(ctx, "approval:admin")
    result = await db.execute(select(ApprovalPolicy).where(ApprovalPolicy.id == policy_id))
    policy = result.scalar_one_or_none()
    if policy is None or policy.organization_id != organization_id:
        raise HTTPException(status_code=404, detail="Policy not found")
    if body.name is not None:
        policy.name = body.name
    if body.is_active is not None:
        policy.is_active = body.is_active
    if body.rules is not None:
        policy.version += 1
        policy.rules = body.rules
        db.add(ApprovalPolicyVersion(policy_id=policy.id,
                                     organization_id=organization_id,
                                     version=policy.version, rules=body.rules))
    await db.commit()
    return {"id": str(policy.id), "version": policy.version}


@policies_router.delete("/{policy_id}", summary="Delete guardrail policy")
async def delete_policy(organization_id: UUID, policy_id: UUID,
                        db: AsyncSession = Depends(get_db),
                        ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_permission(ctx, "approval:admin")
    result = await db.execute(select(ApprovalPolicy).where(ApprovalPolicy.id == policy_id))
    policy = result.scalar_one_or_none()
    if policy is None or policy.organization_id != organization_id:
        raise HTTPException(status_code=404, detail="Policy not found")
    await db.delete(policy)
    await db.commit()
    return {"deleted": True}


# Approval-scoped delegation lives under the approvals router path but is
# registered here to keep one module: mount helper below re-exports it.
delegations_router = APIRouter(prefix="/organizations/{organization_id}/approval-delegations",
                               tags=["approval-delegations"])


@delegations_router.post("", status_code=201, summary="Delegate approval authority")
async def create_delegation(organization_id: UUID, body: DelegationCreate,
                            db: AsyncSession = Depends(get_db),
                            ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_permission(ctx, "approval:admin")
    errors = validate_delegation(delegator_permissions=ctx.permissions,
                                 scope=body.scope, expires_at=body.expires_at)
    if errors:
        raise HTTPException(status_code=400, detail="; ".join(errors))
    delegation = ApprovalDelegation(organization_id=organization_id,
                                    delegator_id=ctx.user_id,
                                    delegate_id=body.delegate_id, scope=body.scope,
                                    expires_at=body.expires_at, is_active=True)
    db.add(delegation)
    await db.commit()
    return {"id": str(delegation.id), "scope": delegation.scope}
