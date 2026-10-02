"""Management-layer API: managers, contracts, delegations, handoffs,
reviews, escalations, dynamic teams, workforce, console, org chart, SSE."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any, Dict, List, NoReturn, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.api.dependencies import get_current_org_context, require_permission
from openagent.db.models import Organization
from openagent.db.session import get_db
from openagent.management.service import ManagementService
from openagent.management.teams import TeamFormationRequest
from openagent.orchestration.config import OrchestrationOrgSettings
from openagent.orchestration.service import OrchestrationError
from openagent.schemas.base import ApiErrorResponse

router = APIRouter(prefix="/organizations/{organization_id}/management", tags=["management"])


def _service(db: AsyncSession, org: Optional[Organization] = None) -> ManagementService:
    settings = OrchestrationOrgSettings.from_organization_settings(
        getattr(org, "settings", None) if org else None
    )
    return ManagementService(db, settings)


def _check_org(organization_id: UUID, auth_context: Any) -> None:
    if auth_context.organization_id != organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "Organization mismatch", "code": "FORBIDDEN"},
        )


def _fail(exc: OrchestrationError) -> NoReturn:
    mapping = {
        "NOT_FOUND": status.HTTP_404_NOT_FOUND,
        "AGENT_NOT_FOUND": status.HTTP_404_NOT_FOUND,
        "NO_CANDIDATE": status.HTTP_422_UNPROCESSABLE_ENTITY,
        "INVALID_CONTRACT": status.HTTP_422_UNPROCESSABLE_ENTITY,
        "INVALID_HANDOFF": status.HTTP_422_UNPROCESSABLE_ENTITY,
        "INVALID_ESCALATION": status.HTTP_422_UNPROCESSABLE_ENTITY,
        "INVALID_COLLABORATION": status.HTTP_422_UNPROCESSABLE_ENTITY,
        "INVALID_STATE": status.HTTP_409_CONFLICT,
        "INVALID_TRANSITION": status.HTTP_409_CONFLICT,
        "INVALID_MODE": status.HTTP_422_UNPROCESSABLE_ENTITY,
        "INVALID_ACTION": status.HTTP_422_UNPROCESSABLE_ENTITY,
        "INVALID_STATUS": status.HTTP_422_UNPROCESSABLE_ENTITY,
        "INVALID_SEVERITY": status.HTTP_422_UNPROCESSABLE_ENTITY,
        "INVALID_TEAM_TYPE": status.HTTP_422_UNPROCESSABLE_ENTITY,
        "INVALID_NAME": status.HTTP_422_UNPROCESSABLE_ENTITY,
        "AUTHORITY_DENIED": status.HTTP_403_FORBIDDEN,
        "SELF_DELEGATION": status.HTTP_422_UNPROCESSABLE_ENTITY,
        "SELF_HANDOFF": status.HTTP_422_UNPROCESSABLE_ENTITY,
        "NO_TARGET": status.HTTP_422_UNPROCESSABLE_ENTITY,
        "TEAM_FULL": status.HTTP_409_CONFLICT,
        "ALREADY_MANAGER": status.HTTP_409_CONFLICT,
        "MANAGER_SUSPENDED": status.HTTP_403_FORBIDDEN,
        "NOT_MANAGER": status.HTTP_403_FORBIDDEN,
        "REVISIONS_EXHAUSTED": status.HTTP_409_CONFLICT,
        "BUDGET_EXHAUSTED": status.HTTP_429_TOO_MANY_REQUESTS,
    }
    raise HTTPException(
        status_code=mapping.get(exc.code, status.HTTP_400_BAD_REQUEST),
        detail={"error": exc.message, "code": exc.code},
    )


def _dump(row: Any, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    data: Dict[str, Any] = {}
    for column in row.__table__.columns:
        value = getattr(row, column.name, None)
        if isinstance(value, UUID):
            value = str(value)
        elif isinstance(value, datetime):
            value = value.isoformat()
        elif hasattr(value, "value"):
            value = value.value
        data[column.name] = value
    if extra:
        data.update(extra)
    return data


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ProfileCreate(BaseModel):
    agent_id: UUID
    label: str = "manager"
    allowed_actions: Optional[List[str]] = None
    scope: str = "organization"


class ContractCreate(BaseModel):
    objective: str
    responsibilities: List[str] = []
    inputs: Dict[str, Any] = {}
    expected_outputs: Dict[str, Any] = {}
    capabilities: List[str] = []
    constraints: List[str] = []
    permissions: List[str] = []
    budget: Dict[str, Any] = {}
    quality_requirements: List[str] = []
    acceptance_criteria: List[Dict[str, Any]] = []
    escalation_conditions: List[str] = []
    max_revisions: int = 3
    manager_agent_id: Optional[UUID] = None
    task_id: Optional[UUID] = None
    run_id: Optional[UUID] = None
    idempotency_key: Optional[str] = None


class DelegationCreate(BaseModel):
    source_agent_id: UUID
    task_id: Optional[UUID] = None
    run_id: Optional[UUID] = None
    reason: str = ""
    contract: Optional[Dict[str, Any]] = None
    contract_id: Optional[UUID] = None
    required_capabilities: List[str] = []
    policy: str = "hybrid"
    budget: Dict[str, Any] = {}
    explicit_target_id: Optional[UUID] = None
    idempotency_key: Optional[str] = None


class DelegationTransition(BaseModel):
    reason: str = ""
    decided_by: Optional[UUID] = None


class HandoffCreate(BaseModel):
    run_id: UUID
    task_id: UUID
    source_agent_id: Optional[UUID] = None
    target_agent_id: Optional[UUID] = None
    mode: str = "full_handoff"
    package: Dict[str, Any] = {}
    contract_id: Optional[UUID] = None
    idempotency_key: Optional[str] = None


class ReviewCreate(BaseModel):
    run_id: UUID
    task_id: UUID
    reviewer_agent_id: Optional[UUID] = None
    output: Optional[Dict[str, Any]] = None
    status_override: Optional[str] = None


class EscalationCreate(BaseModel):
    source_agent_id: Optional[UUID] = None
    task_id: Optional[UUID] = None
    run_id: Optional[UUID] = None
    trigger: str = "blocked"
    reason: str = ""
    severity: str = "warning"
    recommended_action: str = ""
    chain: Optional[List[str]] = None
    idempotency_key: Optional[str] = None


class EscalationTransition(BaseModel):
    note: str = ""


class TeamCreate(BaseModel):
    name: str
    manager_agent_id: Optional[UUID] = None
    team_type: str = "temporary"
    run_id: Optional[UUID] = None
    task_id: Optional[UUID] = None
    department_id: Optional[UUID] = None
    charter: Optional[Dict[str, Any]] = None
    budget: Dict[str, Any] = {}
    idempotency_key: Optional[str] = None


class TeamFormRequest(BaseModel):
    objective: str
    required_roles: Dict[str, List[str]]
    team_type: str = "temporary"
    max_size: int = 12
    run_id: Optional[UUID] = None
    manager_agent_id: Optional[UUID] = None
    budget: Dict[str, Any] = {}


class MemberAdd(BaseModel):
    agent_id: UUID
    role: str = "worker"
    responsibilities: List[str] = []


class AvailabilitySet(BaseModel):
    state: str


class CapacitySet(BaseModel):
    max_concurrent_tasks: Optional[int] = None
    max_concurrent_runs: Optional[int] = None
    max_daily_cost: Optional[float] = None
    max_token_budget: Optional[int] = None


class CollaborationCreate(BaseModel):
    run_id: UUID
    from_agent_id: UUID
    to_agent_id: UUID
    action: str
    task_id: Optional[UUID] = None
    payload: Dict[str, Any] = {}


class ProgressReport(BaseModel):
    agent_id: UUID
    progress: float = 0.0
    status: str = "running"
    current_step: str = ""
    blocked: bool = False
    blocked_reason: Optional[str] = None


class PlanVersionCreate(BaseModel):
    reason: str
    snapshot: Dict[str, Any] = {}
    changes: List[str] = []
    created_by_agent_id: Optional[UUID] = None


class DecisionCreate(BaseModel):
    manager_agent_id: Optional[UUID] = None
    run_id: Optional[UUID] = None
    task_id: Optional[UUID] = None
    decision_type: str = "general"
    selected_action: str = ""
    alternatives: List[str] = []
    policy_basis: str = ""
    rationale: str = ""


class DepartmentCreate(BaseModel):
    name: str
    description: str = ""


# ---------------------------------------------------------------------------
# Managers
# ---------------------------------------------------------------------------

@router.post("/managers", status_code=status.HTTP_201_CREATED,
             responses={403: {"model": ApiErrorResponse}})
async def create_manager_profile(
    organization_id: UUID, payload: ProfileCreate, request: Request,
    auth_context=Depends(get_current_org_context), db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:create")(request, db)
    try:
        row = await _service(db).create_profile(
            organization_id, payload.agent_id, label=payload.label,
            actor=auth_context.user_id, allowed_actions=payload.allowed_actions,
            scope=payload.scope,
        )
    except OrchestrationError as exc:
        _fail(exc)
    return _dump(row)


@router.get("/managers")
async def list_manager_profiles(
    organization_id: UUID, request: Request,
    auth_context=Depends(get_current_org_context), db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:read")(request, db)
    from openagent.db.models.management import ManagerProfile

    rows = list((await db.execute(
        select(ManagerProfile).where(ManagerProfile.organization_id == organization_id)
        .order_by(ManagerProfile.created_at.desc()).limit(200)
    )).scalars().all())
    return {"data": [_dump(r) for r in rows]}


@router.get("/managers/{agent_id}")
async def get_manager_profile(
    organization_id: UUID, agent_id: UUID, request: Request,
    auth_context=Depends(get_current_org_context), db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:read")(request, db)
    service = _service(db)
    try:
        profile = await service._require_profile(organization_id, agent_id)
    except OrchestrationError as exc:
        _fail(exc)
    return _dump(profile)


@router.post("/managers/{agent_id}/tick")
async def manager_tick(
    organization_id: UUID, agent_id: UUID, request: Request,
    run_id: UUID = Query(...),
    auth_context=Depends(get_current_org_context), db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:run")(request, db)
    try:
        result = await _service(db).manager_tick(
            organization_id, run_id, agent_id, actor=auth_context.user_id)
    except OrchestrationError as exc:
        _fail(exc)
    return result


@router.get("/agents/{agent_id}/reports")
async def agent_reports(
    organization_id: UUID, agent_id: UUID, request: Request,
    auth_context=Depends(get_current_org_context), db: AsyncSession = Depends(get_db),
):
    """Agents reporting to a manager via MANAGES relationships."""
    _check_org(organization_id, auth_context)
    await require_permission("agent:read")(request, db)
    from openagent.db.models.orchestration import AgentRelationship

    rows = list((await db.execute(
        select(AgentRelationship).where(
            AgentRelationship.organization_id == organization_id,
            AgentRelationship.source_agent_id == agent_id,
            AgentRelationship.relationship_type == "manages",
        ).limit(200)
    )).scalars().all())
    return {"data": [
        {"agent_id": str(r.target_agent_id), "relationship": r.relationship_type.value,
         "role": r.role} for r in rows
    ]}


@router.get("/agents/{agent_id}/team")
async def agent_team(
    organization_id: UUID, agent_id: UUID, request: Request,
    auth_context=Depends(get_current_org_context), db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:read")(request, db)
    service = _service(db)
    memberships = await service.memberships.list_by_agent(organization_id, agent_id)
    out = []
    for membership in memberships:
        team = await service.teams.get_by_id(membership.team_id)
        if team:
            out.append({"team_id": str(team.id), "name": team.name,
                        "status": team.status.value, "role": membership.role})
    return {"data": out}


# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------

@router.post("/contracts", status_code=status.HTTP_201_CREATED)
async def create_contract(
    organization_id: UUID, payload: ContractCreate, request: Request,
    auth_context=Depends(get_current_org_context), db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:create")(request, db)
    try:
        row = await _service(db).create_contract(
            organization_id, payload.model_dump(),
            manager_agent_id=payload.manager_agent_id, task_id=payload.task_id,
            run_id=payload.run_id, actor=auth_context.user_id,
            idempotency_key=payload.idempotency_key,
        )
    except OrchestrationError as exc:
        _fail(exc)
    return _dump(row)


@router.get("/contracts")
async def list_contracts(
    organization_id: UUID, request: Request, task_id: Optional[UUID] = Query(None),
    auth_context=Depends(get_current_org_context), db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:read")(request, db)
    service = _service(db)
    if task_id:
        rows = await service.contracts.list_by_task(task_id)
        rows = [r for r in rows if r.organization_id == organization_id]
    else:
        rows = await service.contracts.list(organization_id, limit=100)
    return {"data": [_dump(r) for r in rows]}


# ---------------------------------------------------------------------------
# Delegations
# ---------------------------------------------------------------------------

@router.post("/delegations", status_code=status.HTTP_201_CREATED)
async def create_delegation(
    organization_id: UUID, payload: DelegationCreate, request: Request,
    auth_context=Depends(get_current_org_context), db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:create")(request, db)
    try:
        row = await _service(db).request_delegation(
            organization_id, source_agent_id=payload.source_agent_id,
            task_id=payload.task_id, run_id=payload.run_id, reason=payload.reason,
            contract=payload.contract, contract_id=payload.contract_id,
            required_capabilities=payload.required_capabilities, policy=payload.policy,
            budget=payload.budget, explicit_target_id=payload.explicit_target_id,
            actor=auth_context.user_id, idempotency_key=payload.idempotency_key,
        )
    except OrchestrationError as exc:
        _fail(exc)
    return _dump(row)


@router.get("/delegations")
async def list_delegations(
    organization_id: UUID, request: Request, run_id: Optional[UUID] = Query(None),
    auth_context=Depends(get_current_org_context), db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:read")(request, db)
    service = _service(db)
    if run_id:
        rows = await service.delegations.list_by_run(run_id)
        rows = [r for r in rows if r.organization_id == organization_id]
    else:
        rows = await service.delegations.list(organization_id, limit=200)
    return {"data": [_dump(r) for r in rows]}


@router.get("/delegations/{delegation_id}")
async def get_delegation(
    organization_id: UUID, delegation_id: UUID, request: Request,
    auth_context=Depends(get_current_org_context), db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:read")(request, db)
    row = await _service(db).delegations.get_by_id_with_org(delegation_id, organization_id)
    if row is None:
        raise HTTPException(status_code=404, detail={"error": "Not found", "code": "NOT_FOUND"})
    return _dump(row)


@router.post("/delegations/{delegation_id}/{action}")
async def transition_delegation(
    organization_id: UUID, delegation_id: UUID, action: str, payload: DelegationTransition,
    request: Request,
    auth_context=Depends(get_current_org_context), db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:create")(request, db)
    mapping = {"accept": "accepted", "reject": "rejected", "expire": "expired",
               "cancel": "cancelled", "complete": "completed"}
    if action not in mapping:
        raise HTTPException(status_code=422, detail={"error": "Unknown action", "code": "INVALID_ACTION"})
    from openagent.db.models.management import DelegationRequestStatus as DBStatus

    try:
        row = await _service(db).transition_delegation(
            organization_id, delegation_id, DBStatus(mapping[action]),
            reason=payload.reason, actor=auth_context.user_id, decided_by=payload.decided_by,
        )
    except OrchestrationError as exc:
        _fail(exc)
    return _dump(row)


# ---------------------------------------------------------------------------
# Handoffs
# ---------------------------------------------------------------------------

@router.post("/handoffs", status_code=status.HTTP_201_CREATED)
async def create_handoff(
    organization_id: UUID, payload: HandoffCreate, request: Request,
    auth_context=Depends(get_current_org_context), db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:create")(request, db)
    try:
        row = await _service(db).prepare_handoff(
            organization_id, payload.run_id, payload.task_id,
            source_agent_id=payload.source_agent_id, target_agent_id=payload.target_agent_id,
            mode=payload.mode, package=payload.package, contract_id=payload.contract_id,
            actor=auth_context.user_id, idempotency_key=payload.idempotency_key,
        )
    except OrchestrationError as exc:
        _fail(exc)
    return _dump(row)


@router.get("/handoffs")
async def list_handoffs(
    organization_id: UUID, request: Request, run_id: Optional[UUID] = Query(None),
    auth_context=Depends(get_current_org_context), db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:read")(request, db)
    service = _service(db)
    if run_id:
        rows = await service.handoffs.list_by_run(run_id)
        rows = [r for r in rows if r.organization_id == organization_id]
    else:
        rows = await service.handoffs.list(organization_id, limit=200)
    return {"data": [_dump(r) for r in rows]}


@router.get("/handoffs/{handoff_id}")
async def get_handoff(
    organization_id: UUID, handoff_id: UUID, request: Request,
    auth_context=Depends(get_current_org_context), db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:read")(request, db)
    row = await _service(db).handoffs.get_by_id_with_org(handoff_id, organization_id)
    if row is None:
        raise HTTPException(status_code=404, detail={"error": "Not found", "code": "NOT_FOUND"})
    return _dump(row)


@router.post("/handoffs/{handoff_id}/{action}")
async def transition_handoff(
    organization_id: UUID, handoff_id: UUID, action: str, request: Request,
    auth_context=Depends(get_current_org_context), db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:create")(request, db)
    mapping = {"accept": "accepted", "reject": "rejected", "execute": "executing",
               "complete": "completed", "expire": "expired", "cancel": "cancelled"}
    if action not in mapping:
        raise HTTPException(status_code=422, detail={"error": "Unknown action", "code": "INVALID_ACTION"})
    from openagent.db.models.management import HandoffPackageStatus as DBStatus

    try:
        row = await _service(db).transition_handoff(
            organization_id, handoff_id, DBStatus(mapping[action]), actor=auth_context.user_id)
    except OrchestrationError as exc:
        _fail(exc)
    return _dump(row)


# ---------------------------------------------------------------------------
# Reviews
# ---------------------------------------------------------------------------

@router.post("/reviews", status_code=status.HTTP_201_CREATED)
async def submit_review(
    organization_id: UUID, payload: ReviewCreate, request: Request,
    auth_context=Depends(get_current_org_context), db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:create")(request, db)
    try:
        row = await _service(db).submit_review(
            organization_id, payload.run_id, payload.task_id,
            reviewer_agent_id=payload.reviewer_agent_id, output=payload.output,
            status_override=payload.status_override, actor=auth_context.user_id,
        )
    except OrchestrationError as exc:
        _fail(exc)
    return _dump(row)


@router.get("/reviews")
async def list_reviews(
    organization_id: UUID, request: Request, task_id: Optional[UUID] = Query(None),
    run_id: Optional[UUID] = Query(None),
    auth_context=Depends(get_current_org_context), db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:read")(request, db)
    service = _service(db)
    if task_id:
        rows = await service.reviews.list_by_task(task_id)
        rows = [r for r in rows if r.organization_id == organization_id]
    elif run_id:
        from openagent.db.models.management import ReviewResult

        rows = list((await db.execute(
            select(ReviewResult).where(ReviewResult.orchestration_run_id == run_id,
                                       ReviewResult.organization_id == organization_id)
            .order_by(ReviewResult.created_at.desc()).limit(200)
        )).scalars().all())
    else:
        rows = await service.reviews.list(organization_id, limit=200)
    return {"data": [_dump(r) for r in rows]}


# ---------------------------------------------------------------------------
# Escalations
# ---------------------------------------------------------------------------

@router.post("/escalations", status_code=status.HTTP_201_CREATED)
async def create_escalation(
    organization_id: UUID, payload: EscalationCreate, request: Request,
    auth_context=Depends(get_current_org_context), db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:create")(request, db)
    try:
        row = await _service(db).open_escalation(
            organization_id, source_agent_id=payload.source_agent_id,
            task_id=payload.task_id, run_id=payload.run_id, trigger=payload.trigger,
            reason=payload.reason, severity=payload.severity,
            recommended_action=payload.recommended_action, chain=payload.chain,
            actor=auth_context.user_id, idempotency_key=payload.idempotency_key,
        )
    except OrchestrationError as exc:
        _fail(exc)
    return _dump(row)


@router.get("/escalations")
async def list_escalations(
    organization_id: UUID, request: Request, open_only: bool = Query(True),
    auth_context=Depends(get_current_org_context), db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:read")(request, db)
    service = _service(db)
    if open_only:
        rows = await service.escalations.list_open(organization_id)
    else:
        rows = await service.escalations.list(organization_id, limit=200)
    return {"data": [_dump(r) for r in rows]}


@router.get("/escalations/{escalation_id}")
async def get_escalation(
    organization_id: UUID, escalation_id: UUID, request: Request,
    auth_context=Depends(get_current_org_context), db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:read")(request, db)
    row = await _service(db).escalations.get_by_id_with_org(escalation_id, organization_id)
    if row is None:
        raise HTTPException(status_code=404, detail={"error": "Not found", "code": "NOT_FOUND"})
    return _dump(row)


@router.post("/escalations/{escalation_id}/{action}")
async def transition_escalation(
    organization_id: UUID, escalation_id: UUID, action: str, payload: EscalationTransition,
    request: Request,
    auth_context=Depends(get_current_org_context), db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:create")(request, db)
    mapping = {"ack": "acknowledged", "acknowledge": "acknowledged", "progress": "in_progress",
               "resolve": "resolved", "chain": "escalated", "close": "closed"}
    if action not in mapping:
        raise HTTPException(status_code=422, detail={"error": "Unknown action", "code": "INVALID_ACTION"})
    from openagent.db.models.management import EscalationStatus as DBStatus

    try:
        row = await _service(db).transition_escalation(
            organization_id, escalation_id, DBStatus(mapping[action]),
            note=payload.note, actor=auth_context.user_id,
        )
    except OrchestrationError as exc:
        _fail(exc)
    return _dump(row)


# ---------------------------------------------------------------------------
# Dynamic teams
# ---------------------------------------------------------------------------

@router.post("/teams", status_code=status.HTTP_201_CREATED)
async def create_team(
    organization_id: UUID, payload: TeamCreate, request: Request,
    auth_context=Depends(get_current_org_context), db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:create")(request, db)
    try:
        row = await _service(db).create_team(
            organization_id, name=payload.name, manager_agent_id=payload.manager_agent_id,
            team_type=payload.team_type, run_id=payload.run_id, task_id=payload.task_id,
            department_id=payload.department_id, charter=payload.charter,
            budget=payload.budget, actor=auth_context.user_id,
            idempotency_key=payload.idempotency_key,
        )
    except OrchestrationError as exc:
        _fail(exc)
    return _dump(row)


@router.post("/teams/form", status_code=status.HTTP_201_CREATED)
async def form_team(
    organization_id: UUID, payload: TeamFormRequest, request: Request,
    auth_context=Depends(get_current_org_context), db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:create")(request, db)
    try:
        result = await _service(db).form_team_from_roles(
            organization_id,
            TeamFormationRequest(
                objective=payload.objective, required_roles=payload.required_roles,
                max_size=payload.max_size, budget=payload.budget,
            ),
            run_id=payload.run_id, manager_agent_id=payload.manager_agent_id,
            actor=auth_context.user_id,
        )
    except OrchestrationError as exc:
        _fail(exc)
    return result


@router.get("/teams")
async def list_teams(
    organization_id: UUID, request: Request, run_id: Optional[UUID] = Query(None),
    auth_context=Depends(get_current_org_context), db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:read")(request, db)
    service = _service(db)
    if run_id:
        rows = await service.teams.list_by_run(run_id)
        rows = [r for r in rows if r.organization_id == organization_id]
    else:
        rows = await service.teams.list(organization_id, limit=200)
    return {"data": [_dump(r) for r in rows]}


@router.get("/teams/{team_id}")
async def get_team(
    organization_id: UUID, team_id: UUID, request: Request,
    auth_context=Depends(get_current_org_context), db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:read")(request, db)
    service = _service(db)
    team = await service.teams.get_by_id_with_org(team_id, organization_id)
    if team is None:
        raise HTTPException(status_code=404, detail={"error": "Not found", "code": "NOT_FOUND"})
    members = await service.memberships.list_by_team(team.id)
    charter = await service.charters.get_by_team(team.id)
    return _dump(team, {
        "members": [{"agent_id": str(m.agent_id), "role": m.role, "status": m.status,
                     "responsibilities": m.responsibilities} for m in members],
        "charter": _dump(charter) if charter else None,
    })


@router.post("/teams/{team_id}/{action}")
async def transition_team(
    organization_id: UUID, team_id: UUID, action: str, request: Request,
    auth_context=Depends(get_current_org_context), db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:create")(request, db)
    mapping = {"form": "forming", "activate": "active", "wind_down": "winding_down",
               "complete": "completed", "cancel": "cancelled"}
    if action not in mapping:
        raise HTTPException(status_code=422, detail={"error": "Unknown action", "code": "INVALID_ACTION"})
    from openagent.db.models.management import DynamicTeamStatus as DBStatus

    try:
        row = await _service(db).transition_team(
            organization_id, team_id, DBStatus(mapping[action]), actor=auth_context.user_id)
    except OrchestrationError as exc:
        _fail(exc)
    return _dump(row)


@router.post("/teams/{team_id}/members", status_code=status.HTTP_201_CREATED)
async def add_team_member(
    organization_id: UUID, team_id: UUID, payload: MemberAdd, request: Request,
    auth_context=Depends(get_current_org_context), db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:create")(request, db)
    try:
        row = await _service(db).add_member(
            organization_id, team_id, payload.agent_id, role=payload.role,
            responsibilities=payload.responsibilities, actor=auth_context.user_id,
        )
    except OrchestrationError as exc:
        _fail(exc)
    return _dump(row)


@router.delete("/teams/{team_id}/members/{agent_id}")
async def remove_team_member(
    organization_id: UUID, team_id: UUID, agent_id: UUID, request: Request,
    auth_context=Depends(get_current_org_context), db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:create")(request, db)
    try:
        row = await _service(db).remove_member(
            organization_id, team_id, agent_id, actor=auth_context.user_id)
    except OrchestrationError as exc:
        _fail(exc)
    return _dump(row)


# ---------------------------------------------------------------------------
# Departments, availability, capacity
# ---------------------------------------------------------------------------

@router.post("/departments", status_code=status.HTTP_201_CREATED)
async def create_department(
    organization_id: UUID, payload: DepartmentCreate, request: Request,
    auth_context=Depends(get_current_org_context), db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:create")(request, db)
    try:
        row = await _service(db).create_department(
            organization_id, payload.name, description=payload.description,
            actor=auth_context.user_id,
        )
    except OrchestrationError as exc:
        _fail(exc)
    return _dump(row)


@router.get("/departments")
async def list_departments(
    organization_id: UUID, request: Request,
    auth_context=Depends(get_current_org_context), db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:read")(request, db)
    rows = await _service(db).departments.list(organization_id, limit=200)
    return {"data": [_dump(r) for r in rows]}


@router.put("/agents/{agent_id}/availability")
async def set_availability(
    organization_id: UUID, agent_id: UUID, payload: AvailabilitySet, request: Request,
    auth_context=Depends(get_current_org_context), db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:create")(request, db)
    try:
        row = await _service(db).set_availability(
            organization_id, agent_id, payload.state, actor=auth_context.user_id)
    except OrchestrationError as exc:
        _fail(exc)
    return _dump(row)


@router.put("/agents/{agent_id}/capacity")
async def set_capacity(
    organization_id: UUID, agent_id: UUID, payload: CapacitySet, request: Request,
    auth_context=Depends(get_current_org_context), db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:create")(request, db)
    try:
        row = await _service(db).set_capacity(
            organization_id, agent_id,
            {k: v for k, v in payload.model_dump().items() if v is not None},
            actor=auth_context.user_id,
        )
    except OrchestrationError as exc:
        _fail(exc)
    return _dump(row)


@router.get("/agents/{agent_id}/capabilities")
async def agent_capabilities(
    organization_id: UUID, agent_id: UUID, request: Request,
    auth_context=Depends(get_current_org_context), db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:read")(request, db)
    from openagent.db.repositories.orchestration import AgentCapabilityRepository

    repo = AgentCapabilityRepository(db)
    rows = await repo.list_for_agent(agent_id)
    rows = [r for r in rows if r.organization_id in (None, organization_id)]
    return {"data": [_dump(r) for r in rows]}


# ---------------------------------------------------------------------------
# Collaboration, progress, plans, decisions
# ---------------------------------------------------------------------------

@router.post("/collaborations", status_code=status.HTTP_201_CREATED)
async def create_collaboration(
    organization_id: UUID, payload: CollaborationCreate, request: Request,
    auth_context=Depends(get_current_org_context), db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:create")(request, db)
    try:
        row = await _service(db).request_collaboration(
            organization_id, payload.run_id, from_agent_id=payload.from_agent_id,
            to_agent_id=payload.to_agent_id, action=payload.action,
            task_id=payload.task_id, payload=payload.payload, actor=auth_context.user_id,
        )
    except OrchestrationError as exc:
        _fail(exc)
    return _dump(row)


@router.post("/collaborations/{collaboration_id}/{action}")
async def transition_collaboration(
    organization_id: UUID, collaboration_id: UUID, action: str, request: Request,
    auth_context=Depends(get_current_org_context), db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:create")(request, db)
    if action not in ("accept", "decline", "complete", "cancel"):
        raise HTTPException(status_code=422, detail={"error": "Unknown action", "code": "INVALID_ACTION"})
    mapping = {"accept": "accepted", "decline": "declined",
               "complete": "completed", "cancel": "cancelled"}
    try:
        row = await _service(db).transition_collaboration(
            organization_id, collaboration_id, mapping[action], actor=auth_context.user_id)
    except OrchestrationError as exc:
        _fail(exc)
    return _dump(row)


@router.post("/runs/{run_id}/tasks/{task_id}/progress")
async def report_progress(
    organization_id: UUID, run_id: UUID, task_id: UUID, payload: ProgressReport,
    request: Request,
    auth_context=Depends(get_current_org_context), db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:create")(request, db)
    try:
        result = await _service(db).report_progress(
            organization_id, run_id, task_id, agent_id=payload.agent_id,
            report=payload.model_dump(),
        )
    except OrchestrationError as exc:
        _fail(exc)
    return result


@router.post("/runs/{run_id}/tasks/{task_id}/escalate", status_code=status.HTTP_201_CREATED)
async def escalate_task(
    organization_id: UUID, run_id: UUID, task_id: UUID, payload: EscalationCreate,
    request: Request,
    auth_context=Depends(get_current_org_context), db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:create")(request, db)
    try:
        row = await _service(db).open_escalation(
            organization_id, source_agent_id=payload.source_agent_id,
            task_id=task_id, run_id=run_id, trigger=payload.trigger,
            reason=payload.reason, severity=payload.severity,
            recommended_action=payload.recommended_action, chain=payload.chain,
            actor=auth_context.user_id, idempotency_key=payload.idempotency_key,
        )
    except OrchestrationError as exc:
        _fail(exc)
    return _dump(row)


@router.post("/runs/{run_id}/plan-versions", status_code=status.HTTP_201_CREATED)
async def create_plan_version(
    organization_id: UUID, run_id: UUID, payload: PlanVersionCreate, request: Request,
    auth_context=Depends(get_current_org_context), db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:create")(request, db)
    try:
        row = await _service(db).record_plan_version(
            organization_id, run_id, reason=payload.reason, snapshot=payload.snapshot,
            changes=payload.changes, created_by_agent_id=payload.created_by_agent_id,
            actor=auth_context.user_id,
        )
    except OrchestrationError as exc:
        _fail(exc)
    return _dump(row)


@router.get("/runs/{run_id}/plan-versions")
async def list_plan_versions(
    organization_id: UUID, run_id: UUID, request: Request,
    auth_context=Depends(get_current_org_context), db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:read")(request, db)
    service = _service(db)
    try:
        run = await service.orchestrator.get_run(organization_id, run_id)
        rows = await service.versions.list_by_run(run.id)
    except OrchestrationError as exc:
        _fail(exc)
    return {"data": [_dump(r) for r in rows]}


@router.get("/runs/{run_id}/decisions")
async def list_decisions(
    organization_id: UUID, run_id: UUID, request: Request,
    auth_context=Depends(get_current_org_context), db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:read")(request, db)
    service = _service(db)
    try:
        run = await service.orchestrator.get_run(organization_id, run_id)
        rows = await service.decisions.list_by_run(run.id)
    except OrchestrationError as exc:
        _fail(exc)
    return {"data": [_dump(r) for r in rows]}


# ---------------------------------------------------------------------------
# Console + org chart
# ---------------------------------------------------------------------------

@router.get("/console")
async def manager_console(
    organization_id: UUID, request: Request,
    run_id: Optional[UUID] = Query(None),
    auth_context=Depends(get_current_org_context), db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:read")(request, db)
    service = _service(db)
    from openagent.db.models.management import DynamicTeam, Escalation
    from openagent.db.models.orchestration import OrchestrationTask

    teams = await service.teams.list(organization_id, limit=200)
    if run_id:
        teams = [t for t in teams if t.orchestration_run_id == run_id]
    escalations = await service.escalations.list_open(organization_id)
    delegations = await service.delegations.list(organization_id, limit=200)
    if run_id:
        delegations = [d for d in delegations if d.orchestration_run_id == run_id]
    tasks: List[Any] = []
    failed = 0
    blocked = 0
    if run_id:
        try:
            run = await service.orchestrator.get_run(organization_id, run_id)
            tasks = await service.orchestrator.tasks.list_by_run(run.id, limit=10000)
            failed = sum(1 for t in tasks if t.status.value in ("failed", "timed_out"))
            blocked = sum(1 for t in tasks if (t.task_metadata or {}).get("blocked"))
        except OrchestrationError:
            pass
    return {
        "active_teams": sum(1 for t in teams if t.status.value == "active"),
        "teams": [{"id": str(t.id), "name": t.name, "status": t.status.value} for t in teams[:50]],
        "active_tasks": sum(1 for t in tasks if t.status.value in ("running", "assigned", "ready")),
        "blocked_tasks": blocked,
        "failed_tasks": failed,
        "pending_delegations": sum(1 for d in delegations if d.status.value == "pending"),
        "delegations": [{"id": str(d.id), "status": d.status.value} for d in delegations[:50]],
        "open_escalations": len(escalations),
        "escalations": [{"id": str(e.id), "severity": e.severity,
                         "status": e.status.value} for e in escalations[:50]],
    }


@router.get("/organization/chart")
async def organization_chart(
    organization_id: UUID, request: Request,
    auth_context=Depends(get_current_org_context), db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:read")(request, db)
    from openagent.db.models import Agent
    from openagent.db.models.management import DynamicTeamMembership, ManagerProfile
    from openagent.db.models.orchestration import AgentRelationship

    agents = list((await db.execute(
        select(Agent).where(Agent.organization_id == organization_id).limit(500)
    )).scalars().all())
    profiles = list((await db.execute(
        select(ManagerProfile).where(ManagerProfile.organization_id == organization_id).limit(200)
    )).scalars().all())
    relationships = list((await db.execute(
        select(AgentRelationship).where(AgentRelationship.organization_id == organization_id).limit(500)
    )).scalars().all())
    memberships = list((await db.execute(
        select(DynamicTeamMembership).where(
            DynamicTeamMembership.organization_id == organization_id,
            DynamicTeamMembership.status == "active").limit(1000)
    )).scalars().all())
    departments = await _service(db).departments.list(organization_id, limit=100)
    return {
        "agents": [{"id": str(a.id), "name": a.name, "status": a.status.value} for a in agents],
        "managers": [{"agent_id": str(p.agent_id), "label": p.label,
                      "scope": p.scope} for p in profiles],
        "relationships": [{"source": str(r.source_agent_id), "target": str(r.target_agent_id),
                           "type": r.relationship_type.value} for r in relationships],
        "team_memberships": [{"team_id": str(m.team_id), "agent_id": str(m.agent_id),
                              "role": m.role} for m in memberships],
        "departments": [{"id": str(d.id), "name": d.name, "slug": d.slug} for d in departments],
    }


# ---------------------------------------------------------------------------
# SSE live stream
# ---------------------------------------------------------------------------

@router.get("/runs/{run_id}/stream")
async def run_event_stream(
    organization_id: UUID, run_id: UUID, request: Request,
    since: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    # EventSource cannot set custom headers, so the org comes from the path.
    # Membership + permission are verified explicitly (same policy as REST).
    from openagent.api.dependencies import get_auth_context
    from openagent.db.models.orchestration import OrchestrationEvent
    from openagent.services.authorization import AuthorizationService

    user, _, _ = await get_auth_context(request, db)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail={"error": "Authentication required", "code": "UNAUTHORIZED"})
    authz = AuthorizationService(db)
    ctx = await authz.get_user_context(user.id, organization_id)
    if ctx is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail={"error": "Not a member", "code": "FORBIDDEN"})
    try:
        authz.require_permission(ctx, "agent:read")
    except Exception:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail={"error": "Access denied", "code": "FORBIDDEN"})
    service = _service(db)
    try:
        run = await service.orchestrator.get_run(organization_id, run_id)
    except OrchestrationError as exc:
        _fail(exc)

    async def generator():
        last_id = since
        # Short-lived stream windows (proxies/load-balancers); clients resume
        # with Last-Event-ID. Backend remains authoritative.
        for _ in range(150):  # ~5 minutes at 2s polls
            if await request.is_disconnected():
                break
            query = select(OrchestrationEvent).where(
                OrchestrationEvent.orchestration_run_id == run.id)
            if last_id:
                try:
                    query = query.where(OrchestrationEvent.created_at > datetime.fromisoformat(last_id))
                except ValueError:
                    pass
            query = query.order_by(OrchestrationEvent.created_at.asc()).limit(100)
            rows = list((await db.execute(query)).scalars().all())
            for row in rows:
                payload = json.dumps({
                    "id": row.created_at.isoformat(), "event": row.event_type,
                    "task_id": str(row.task_id) if row.task_id else None,
                    "agent_id": str(row.agent_id) if row.agent_id else None,
                    "payload": row.payload,
                })
                last_id = row.created_at.isoformat()
                yield f"id: {last_id}\nevent: {row.event_type}\ndata: {payload}\n\n"
            if not rows:
                yield ": heartbeat\n\n"
            await asyncio.sleep(2)

    return StreamingResponse(generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
