"""Multi-agent orchestration API endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, NoReturn, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.api.dependencies import get_current_org_context, require_permission
from openagent.db.models import Organization
from openagent.db.models.orchestration import (
    AgentCapability,
    AgentRelationship,
    AgentRelationshipType,
    OrchestrationRun,
    OrchestrationTask,
)
from openagent.db.session import get_db
from openagent.orchestration.config import OrchestrationOrgSettings
from openagent.orchestration.planner import RuleBasedPlanner
from openagent.orchestration.service import OrchestrationError, OrchestrationService
from openagent.orchestration.templates import TEMPLATES
from openagent.orchestration.types import Budget, TaskPlan
from openagent.schemas.base import ApiErrorResponse, PaginatedResponse

router = APIRouter(prefix="/organizations/{organization_id}/orchestrations", tags=["orchestrations"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class BudgetInput(BaseModel):
    max_total_steps: int = 1000
    max_total_tokens: int = 500_000
    max_total_cost: float = 10.0
    max_execution_time_seconds: int = 3600
    max_tasks: int = 200
    max_agents: int = 50
    max_delegation_depth: int = 5
    max_tool_calls: int = 500
    max_parallel_tasks: int = 10


class OrchestrationCreate(BaseModel):
    objective: str = Field(min_length=1, max_length=8000)
    budget: Optional[BudgetInput] = None
    root_agent_id: Optional[UUID] = None
    team_id: Optional[UUID] = None
    idempotency_key: Optional[str] = Field(default=None, max_length=255)
    template: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class PlannedTaskInput(BaseModel):
    task_id: str
    title: str
    description: str = ""
    instructions: str = ""
    parent_task_id: Optional[str] = None
    dependencies: List[str] = []
    required_capabilities: List[str] = []
    priority: str = "normal"
    dependency_policy: str = "all_success"
    risk_level: str = "low"
    required_permissions: List[str] = []
    requires_approval: bool = False
    assigned_agent_id: Optional[str] = None
    timeout_seconds: int = 600
    max_retries: int = 1
    retry_strategy: str = "fixed"
    input: Dict[str, Any] = {}


class PlanInput(BaseModel):
    objective: Optional[str] = None
    tasks: Optional[List[PlannedTaskInput]] = None
    template: Optional[str] = None


class OrchestrationResponse(BaseModel):
    id: UUID
    organization_id: UUID
    objective: str
    status: str
    root_agent_id: Optional[UUID] = None
    budget: Dict[str, Any] = {}
    usage: Dict[str, Any] = {}
    final_result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class OrchestrationListResponse(PaginatedResponse[OrchestrationResponse]):
    pass


class TaskResponse(BaseModel):
    id: UUID
    orchestration_run_id: UUID
    external_task_id: str
    title: str
    status: str
    priority: str
    assigned_agent_id: Optional[UUID] = None
    required_capabilities: List[str] = []
    risk_level: str
    output: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    retry_count: int = 0
    depth: int = 1
    created_at: datetime

    class Config:
        from_attributes = True


class MessageResponse(BaseModel):
    id: UUID
    sender_agent_id: Optional[UUID] = None
    recipient_agent_id: Optional[UUID] = None
    task_id: Optional[UUID] = None
    message_type: str
    payload: Dict[str, Any] = {}
    correlation_id: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class EventResponse(BaseModel):
    id: UUID
    task_id: Optional[UUID] = None
    agent_id: Optional[UUID] = None
    event_type: str
    payload: Dict[str, Any] = {}
    trace_id: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ReassignInput(BaseModel):
    agent_id: UUID


class DelegateInput(BaseModel):
    parent_agent_id: UUID
    target_agent_id: UUID


class HandoffInput(BaseModel):
    from_agent_id: Optional[UUID] = None
    to_agent_id: Optional[UUID] = None
    completed_work: Dict[str, Any] = {}
    artifacts: List[Dict[str, Any]] = []
    relevant_context: Dict[str, Any] = {}
    constraints: List[str] = []
    warnings: List[str] = []
    expected_next_action: str = ""


class RelationshipCreate(BaseModel):
    source_agent_id: UUID
    target_agent_id: UUID
    relationship_type: str = Field(pattern="^(manages|reports_to|collaborates_with|can_delegate_to|can_review|specializes_in)$")
    role: str = "worker"


class CapabilityCreate(BaseModel):
    agent_id: UUID
    name: str = Field(min_length=1, max_length=128)
    description: str = ""
    version: str = "1.0"
    required_tools: List[str] = []
    required_permissions: List[str] = []
    risk_level: str = "low"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _service(db: AsyncSession, org: Optional[Organization] = None) -> OrchestrationService:
    settings = OrchestrationOrgSettings.from_organization_settings(
        getattr(org, "settings", None) if org else None
    )
    return OrchestrationService(db, settings)


def _check_org(organization_id: UUID, auth_context: Any) -> None:
    if auth_context.organization_id != organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "Organization mismatch", "code": "FORBIDDEN"},
        )


def _handle_error(exc: OrchestrationError) -> NoReturn:
    mapping = {
        "NOT_FOUND": status.HTTP_404_NOT_FOUND,
        "AGENT_NOT_FOUND": status.HTTP_404_NOT_FOUND,
        "INVALID_PLAN": status.HTTP_422_UNPROCESSABLE_ENTITY,
        "EMPTY_OBJECTIVE": status.HTTP_422_UNPROCESSABLE_ENTITY,
        "INVALID_STATE": status.HTTP_409_CONFLICT,
        "INVALID_TRANSITION": status.HTTP_409_CONFLICT,
        "RETRIES_EXHAUSTED": status.HTTP_409_CONFLICT,
        "DELEGATION_TOO_DEEP": status.HTTP_422_UNPROCESSABLE_ENTITY,
        "DELEGATION_DENIED": status.HTTP_403_FORBIDDEN,
        "SELF_DELEGATION": status.HTTP_422_UNPROCESSABLE_ENTITY,
        "DELEGATION_DISABLED": status.HTTP_403_FORBIDDEN,
        "PAUSED": status.HTTP_409_CONFLICT,
    }
    raise HTTPException(
        status_code=mapping.get(exc.code, status.HTTP_400_BAD_REQUEST),
        detail={"error": exc.message, "code": exc.code},
    )


def _to_run_response(run: OrchestrationRun) -> OrchestrationResponse:
    return OrchestrationResponse(
        id=run.id,
        organization_id=run.organization_id,
        objective=run.objective,
        status=run.status.value,
        root_agent_id=run.root_agent_id,
        budget=dict(run.budget or {}),
        usage=dict(run.usage or {}),
        final_result=run.final_result,
        error=run.error,
        started_at=run.started_at,
        completed_at=run.completed_at,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


def _to_task_response(task: OrchestrationTask) -> TaskResponse:
    return TaskResponse(
        id=task.id,
        orchestration_run_id=task.orchestration_run_id,
        external_task_id=task.external_task_id,
        title=task.title,
        status=task.status.value,
        priority=task.priority,
        assigned_agent_id=task.assigned_agent_id,
        required_capabilities=list(task.required_capabilities or []),
        risk_level=task.risk_level,
        output=task.output,
        error=task.error,
        retry_count=task.retry_count,
        depth=task.depth,
        created_at=task.created_at,
    )


def _task_plan_from_input(data: PlanInput, fallback_objective: str) -> TaskPlan:
    from openagent.orchestration.types import (
        DependencyPolicy,
        PlannedTask,
        RiskLevel,
        TaskPriority,
        RetryStrategy,
    )

    objective = data.objective or fallback_objective
    tasks: List[PlannedTask] = []
    for item in data.tasks or []:
        try:
            priority = TaskPriority(item.priority)
        except ValueError:
            priority = TaskPriority.NORMAL
        try:
            policy = DependencyPolicy(item.dependency_policy)
        except ValueError:
            policy = DependencyPolicy.ALL_SUCCESS
        try:
            risk = RiskLevel(item.risk_level)
        except ValueError:
            risk = RiskLevel.LOW
        try:
            retry = RetryStrategy(item.retry_strategy)
        except ValueError:
            retry = RetryStrategy.FIXED
        tasks.append(
            PlannedTask(
                task_id=item.task_id,
                title=item.title,
                description=item.description,
                instructions=item.instructions,
                parent_task_id=item.parent_task_id,
                dependencies=list(item.dependencies or []),
                required_capabilities=list(item.required_capabilities or []),
                priority=priority,
                dependency_policy=policy,
                risk_level=risk,
                required_permissions=list(item.required_permissions or []),
                requires_approval=item.requires_approval,
                assigned_agent_id=item.assigned_agent_id,
                timeout_seconds=item.timeout_seconds,
                max_retries=item.max_retries,
                retry_strategy=retry,
                input=dict(item.input or {}),
            )
        )
    return TaskPlan(objective=objective, tasks=tasks, metadata={"source": "api"})


# ---------------------------------------------------------------------------
# Run CRUD + lifecycle
# ---------------------------------------------------------------------------

@router.post(
    "",
    response_model=OrchestrationResponse,
    status_code=status.HTTP_201_CREATED,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}},
)
async def create_orchestration(
    organization_id: UUID,
    payload: OrchestrationCreate,
    request: Request,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:create")(request, db)
    if payload.template and payload.template not in TEMPLATES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": f"unknown template: {payload.template}", "code": "UNKNOWN_TEMPLATE"},
        )
    idempotency_key = payload.idempotency_key or request.headers.get("Idempotency-Key")
    service = _service(db)
    budget = Budget(**payload.budget.model_dump()) if payload.budget else None
    try:
        run = await service.create_run(
            organization_id=organization_id,
            objective=payload.objective,
            budget=budget,
            root_agent_id=payload.root_agent_id,
            team_id=payload.team_id,
            created_by=auth_context.user_id,
            idempotency_key=idempotency_key,
            metadata=dict(payload.metadata or {}),
        )
    except OrchestrationError as exc:
        _handle_error(exc)
    # Optional inline template planning for convenience.
    if payload.template:
        plan = TEMPLATES[payload.template](run.objective)
        try:
            await service.plan_run(organization_id, run.id, plan)
        except OrchestrationError as exc:
            _handle_error(exc)
        run = await service.get_run(organization_id, run.id)
    return _to_run_response(run)


@router.get("", response_model=OrchestrationListResponse)
async def list_orchestrations(
    organization_id: UUID,
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:read")(request, db)
    query = select(OrchestrationRun).where(OrchestrationRun.organization_id == organization_id)
    count_query = select(func.count(OrchestrationRun.id)).where(
        OrchestrationRun.organization_id == organization_id
    )
    if status_filter:
        query = query.where(OrchestrationRun.status == status_filter)
        count_query = count_query.where(OrchestrationRun.status == status_filter)
    total = (await db.execute(count_query)).scalar_one()
    rows = list(
        (await db.execute(
            query.order_by(OrchestrationRun.created_at.desc())
            .limit(page_size).offset((page - 1) * page_size)
        )).scalars().all()
    )
    total_pages = max(1, (total + page_size - 1) // page_size)
    return {
        "data": [_to_run_response(r) for r in rows],
        "meta": {
            "page": page, "page_size": page_size, "total_items": total,
            "total_pages": total_pages, "has_next": page < total_pages, "has_prev": page > 1,
        },
    }


@router.get("/{run_id}", response_model=OrchestrationResponse)
async def get_orchestration(
    organization_id: UUID,
    run_id: UUID,
    request: Request,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:read")(request, db)
    try:
        run = await _service(db).get_run(organization_id, run_id)
    except OrchestrationError as exc:
        _handle_error(exc)
    return _to_run_response(run)


@router.post("/{run_id}/plan", response_model=List[TaskResponse])
async def plan_orchestration(
    organization_id: UUID,
    run_id: UUID,
    payload: PlanInput,
    request: Request,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:create")(request, db)
    service = _service(db)
    try:
        run = await service.get_run(organization_id, run_id)
    except OrchestrationError as exc:
        _handle_error(exc)
    if payload.template:
        if payload.template not in TEMPLATES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"error": f"unknown template: {payload.template}", "code": "UNKNOWN_TEMPLATE"},
            )
        plan = TEMPLATES[payload.template](payload.objective or run.objective)
    elif payload.tasks is not None:
        plan = _task_plan_from_input(payload, run.objective)
    else:
        # Agent-assisted planning hook would go here; default to rule-based.
        planner = RuleBasedPlanner()
        plan = await planner.create_plan(payload.objective or run.objective)
    try:
        tasks = await service.plan_run(organization_id, run_id, plan)
    except OrchestrationError as exc:
        _handle_error(exc)
    return [_to_task_response(t) for t in tasks]


@router.post("/{run_id}/start", response_model=OrchestrationResponse)
async def start_orchestration(
    organization_id: UUID,
    run_id: UUID,
    request: Request,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Start execution inline (durable workers pick up via queue in production).

    For API-driven runs this executes the DAG in-process; the worker queue
    path enqueues the same service call for background execution.
    """
    _check_org(organization_id, auth_context)
    await require_permission("agent:run")(request, db)
    service = _service(db)
    try:
        result = await service.execute_run(organization_id, run_id)
        run = await service.get_run(organization_id, run_id)
    except OrchestrationError as exc:
        _handle_error(exc)
    _ = result
    return _to_run_response(run)


@router.post("/{run_id}/pause", response_model=OrchestrationResponse)
async def pause_orchestration(
    organization_id: UUID,
    run_id: UUID,
    request: Request,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:run")(request, db)
    from openagent.db.models.orchestration import OrchestrationRunStatus as DBStatus

    try:
        run = await _service(db).transition_run(
            organization_id, run_id, DBStatus.PAUSED, actor=auth_context.user_id
        )
    except OrchestrationError as exc:
        _handle_error(exc)
    return _to_run_response(run)


@router.post("/{run_id}/resume", response_model=OrchestrationResponse)
async def resume_orchestration(
    organization_id: UUID,
    run_id: UUID,
    request: Request,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:run")(request, db)
    from openagent.db.models.orchestration import OrchestrationRunStatus as DBStatus

    try:
        run = await _service(db).transition_run(
            organization_id, run_id, DBStatus.RUNNING, actor=auth_context.user_id
        )
    except OrchestrationError as exc:
        _handle_error(exc)
    return _to_run_response(run)


@router.post("/{run_id}/cancel", response_model=OrchestrationResponse)
async def cancel_orchestration(
    organization_id: UUID,
    run_id: UUID,
    request: Request,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:run")(request, db)
    from openagent.db.models.orchestration import OrchestrationRunStatus as DBStatus

    service = _service(db)
    try:
        run = await service.transition_run(
            organization_id, run_id, DBStatus.CANCELLED, actor=auth_context.user_id
        )
        # Cancel pending tasks so resume never restarts them.
        from openagent.db.models.orchestration import OrchestrationTaskStatus as DBTaskStatus

        tasks = await service.tasks.list_by_run(run.id, limit=10000)
        for task in tasks:
            if task.status.value in ("created", "ready", "assigned", "waiting", "paused"):
                task.status = DBTaskStatus.CANCELLED
        await db.commit()
    except OrchestrationError as exc:
        _handle_error(exc)
    return _to_run_response(run)


# ---------------------------------------------------------------------------
# Tasks / agents / messages / events
# ---------------------------------------------------------------------------

@router.get("/{run_id}/tasks", response_model=List[TaskResponse])
async def list_tasks(
    organization_id: UUID,
    run_id: UUID,
    request: Request,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:read")(request, db)
    service = _service(db)
    try:
        await service.get_run(organization_id, run_id)
        tasks = await service.tasks.list_by_run(run_id, limit=10000)
    except OrchestrationError as exc:
        _handle_error(exc)
    return [_to_task_response(t) for t in tasks]


@router.get("/{run_id}/agents")
async def list_run_agents(
    organization_id: UUID,
    run_id: UUID,
    request: Request,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:read")(request, db)
    service = _service(db)
    try:
        await service.get_run(organization_id, run_id)
        tasks = await service.tasks.list_by_run(run_id, limit=10000)
    except OrchestrationError as exc:
        _handle_error(exc)
    grouped: Dict[str, Dict[str, Any]] = {}
    for task in tasks:
        key = str(task.assigned_agent_id) if task.assigned_agent_id else "unassigned"
        entry = grouped.setdefault(key, {"agent_id": key, "tasks": [], "status": "assigned"})
        entry["tasks"].append(task.external_task_id)
        entry["status"] = task.status.value
    return {"data": list(grouped.values())}


@router.get("/{run_id}/messages", response_model=List[MessageResponse])
async def list_messages(
    organization_id: UUID,
    run_id: UUID,
    request: Request,
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:read")(request, db)
    service = _service(db)
    try:
        await service.get_run(organization_id, run_id)
        messages = await service.messages.list_by_run(run_id, limit=limit, offset=offset)
    except OrchestrationError as exc:
        _handle_error(exc)
    return [MessageResponse.model_validate(m, from_attributes=True) for m in messages]


@router.get("/{run_id}/events", response_model=List[EventResponse])
async def list_events(
    organization_id: UUID,
    run_id: UUID,
    request: Request,
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:read")(request, db)
    service = _service(db)
    try:
        await service.get_run(organization_id, run_id)
        events = await service.events.list_by_run(run_id, limit=limit, offset=offset)
    except OrchestrationError as exc:
        _handle_error(exc)
    return [EventResponse.model_validate(e, from_attributes=True) for e in events]


@router.post("/{run_id}/tasks/{task_id}/retry", response_model=TaskResponse)
async def retry_task(
    organization_id: UUID,
    run_id: UUID,
    task_id: UUID,
    request: Request,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:run")(request, db)
    try:
        task = await _service(db).retry_task(
            organization_id, run_id, task_id, actor=auth_context.user_id
        )
    except OrchestrationError as exc:
        _handle_error(exc)
    return _to_task_response(task)


@router.post("/{run_id}/tasks/{task_id}/reassign", response_model=TaskResponse)
async def reassign_task(
    organization_id: UUID,
    run_id: UUID,
    task_id: UUID,
    payload: ReassignInput,
    request: Request,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:run")(request, db)
    try:
        task = await _service(db).reassign_task(
            organization_id, run_id, task_id, agent_id=payload.agent_id,
            actor=auth_context.user_id,
        )
    except OrchestrationError as exc:
        _handle_error(exc)
    return _to_task_response(task)


@router.post("/{run_id}/tasks/{task_id}/delegate", response_model=TaskResponse)
async def delegate_task(
    organization_id: UUID,
    run_id: UUID,
    task_id: UUID,
    payload: DelegateInput,
    request: Request,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:run")(request, db)
    try:
        task = await _service(db).delegate_task(
            organization_id, run_id, task_id,
            parent_agent_id=payload.parent_agent_id,
            target_agent_id=payload.target_agent_id,
            actor=auth_context.user_id,
        )
    except OrchestrationError as exc:
        _handle_error(exc)
    return _to_task_response(task)


@router.post("/{run_id}/tasks/{task_id}/handoff")
async def handoff_task(
    organization_id: UUID,
    run_id: UUID,
    task_id: UUID,
    payload: HandoffInput,
    request: Request,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:run")(request, db)
    try:
        handoff = await _service(db).handoff_task(
            organization_id, run_id, task_id,
            from_agent_id=payload.from_agent_id,
            to_agent_id=payload.to_agent_id,
            package=payload.model_dump(),
            actor=auth_context.user_id,
        )
    except OrchestrationError as exc:
        _handle_error(exc)
    return {"id": str(handoff.id), "status": handoff.status}


class ReviewTaskInput(BaseModel):
    evaluation_id: UUID
    worker_agent_id: Optional[str] = None


@router.post("/{run_id}/tasks/{task_id}/review")
async def review_task(
    organization_id: UUID,
    run_id: UUID,
    task_id: UUID,
    payload: ReviewTaskInput,
    request: Request,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Manager review of a worker result: never blindly trusts subordinates.

    Returns accept / reject / reassign / escalate based on the referenced
    evaluation; the manager then uses retry / reassign / handoff endpoints.
    """
    _check_org(organization_id, auth_context)
    await require_permission("evaluation:read")(request, db)
    from openagent.db.models.evaluation import Evaluation
    from openagent.evaluator.integrations import supervisor_review_packet
    result = await db.execute(select(Evaluation).where(
        Evaluation.id == payload.evaluation_id))
    evaluation = result.scalar_one_or_none()
    if evaluation is None or evaluation.organization_id != organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Evaluation not found")
    verification = {"decision": evaluation.decision or "FAIL",
                    "score": evaluation.score or 0.0,
                    "reason_codes": (evaluation.result or {}).get("reason_codes", []),
                    "failure_reason": evaluation.failure_reason or "",
                    "status": str(evaluation.status.value
                                  if hasattr(evaluation.status, "value")
                                  else evaluation.status),
                    "correction_strategy": (evaluation.result or {}).get(
                        "correction_strategy")}
    packet = supervisor_review_packet(
        worker_result={"status": "done", "task_id": str(task_id)},
        verification=verification,
        worker_agent_id=payload.worker_agent_id or "")
    return {**packet, "evaluation_id": str(evaluation.id)}


# ---------------------------------------------------------------------------
# Relationships & capabilities
# ---------------------------------------------------------------------------

@router.get("/{run_id}/relationships")
async def list_relationships(
    organization_id: UUID,
    run_id: UUID,
    request: Request,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:read")(request, db)
    rows = list(
        (await db.execute(
            select(AgentRelationship).where(AgentRelationship.organization_id == organization_id)
            .limit(500)
        )).scalars().all()
    )
    return {"data": [
        {
            "id": str(r.id),
            "source_agent_id": str(r.source_agent_id),
            "target_agent_id": str(r.target_agent_id),
            "relationship_type": r.relationship_type.value,
            "role": r.role,
        }
        for r in rows
    ]}


@router.post("/{run_id}/relationships", status_code=status.HTTP_201_CREATED)
async def create_relationship(
    organization_id: UUID,
    run_id: UUID,
    payload: RelationshipCreate,
    request: Request,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:create")(request, db)
    service = _service(db)
    try:
        await service.get_run(organization_id, run_id)
        # Tenant check: both agents must belong to this organization.
        await service._require_agent(organization_id, payload.source_agent_id)
        await service._require_agent(organization_id, payload.target_agent_id)
    except OrchestrationError as exc:
        _handle_error(exc)
    rel = AgentRelationship(
        organization_id=organization_id,
        source_agent_id=payload.source_agent_id,
        target_agent_id=payload.target_agent_id,
        relationship_type=AgentRelationshipType(payload.relationship_type),
        role=payload.role,
    )
    db.add(rel)
    await db.commit()
    await db.refresh(rel)
    return {"id": str(rel.id), "relationship_type": rel.relationship_type.value}


@router.post("/capabilities", status_code=status.HTTP_201_CREATED)
async def register_capability(
    organization_id: UUID,
    payload: CapabilityCreate,
    request: Request,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:create")(request, db)
    service = _service(db)
    try:
        await service._require_agent(organization_id, payload.agent_id)
    except OrchestrationError as exc:
        _handle_error(exc)
    cap = AgentCapability(
        organization_id=organization_id,
        agent_id=payload.agent_id,
        name=payload.name.strip().lower(),
        description=payload.description,
        version=payload.version,
        required_tools=list(payload.required_tools),
        required_permissions=list(payload.required_permissions),
        risk_level=payload.risk_level,
        available=True,
    )
    db.add(cap)
    await db.commit()
    await db.refresh(cap)
    return {"id": str(cap.id), "name": cap.name}
