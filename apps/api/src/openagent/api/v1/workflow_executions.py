"""Workflow execution API endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Optional, List, Dict, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request, HTTPException, status, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.db.session import get_db
from openagent.db.models import (
    Workflow,
    WorkflowExecution,
    WorkflowExecutionStatus,
    WorkflowExecutionTriggerType,
    ExecutionEvent,
)
from openagent.db.repositories import WorkflowRepository, WorkflowExecutionRepository
from openagent.schemas.base import ApiErrorResponse, PaginatedResponse
from openagent.api.dependencies import (
    get_current_org_context,
    require_permission,
)
from openagent.runtime.core import get_runtime

router = APIRouter(prefix="/organizations/{organization_id}/workflows", tags=["workflow-execution"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ExecuteRequest(BaseModel):
    """Request to execute a workflow."""
    version: Optional[str] = Field(default=None, max_length=50)
    input: Optional[Dict[str, Any]] = Field(default=None)
    idempotency_key: Optional[str] = Field(default=None, max_length=100)


class ExecuteResponse(BaseModel):
    execution_id: str
    status: str
    message: str = "Workflow execution started"


class ExecutionResponse(BaseModel):
    id: UUID
    organization_id: UUID
    workflow_id: UUID
    workflow_version_id: Optional[UUID] = None
    status: str
    trigger_type: str
    input: Optional[Dict[str, Any]] = None
    output: Optional[Dict[str, Any]] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ExecutionListResponse(PaginatedResponse[ExecutionResponse]):
    pass


class ExecutionDetailResponse(ExecutionResponse):
    """Execution with node runs and events."""
    node_runs: List[Dict[str, Any]] = []
    events: List[Dict[str, Any]] = []


class CancelResponse(BaseModel):
    status: str
    message: str


class RetryRequest(BaseModel):
    mode: str = Field(default="full", pattern="^(full|from_failed)$")


class RetryResponse(BaseModel):
    status: str
    message: str
    new_execution_id: Optional[str] = None


class ResumeRequest(BaseModel):
    approval_id: UUID = Field(description="Persisted APPROVED approval for this execution")


class ResumeResponse(BaseModel):
    status: str
    message: str


class EventResponse(BaseModel):
    id: UUID
    execution_id: UUID
    event_type: str
    node_id: Optional[str] = None
    sequence: int
    timestamp: datetime
    payload: Dict[str, Any] = {}

    class Config:
        from_attributes = True


class EventsResponse(PaginatedResponse[EventResponse]):
    pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_execution_or_404(
    db: AsyncSession,
    organization_id: UUID,
    execution_id: UUID,
) -> WorkflowExecution:
    """Get execution or raise 404."""
    result = await db.execute(
        select(WorkflowExecution).where(
            WorkflowExecution.id == execution_id,
            WorkflowExecution.organization_id == organization_id,
        )
    )
    execution = result.scalar_one_or_none()
    if not execution:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Execution not found", "code": "EXECUTION_NOT_FOUND"},
        )
    return execution


# ---------------------------------------------------------------------------
# Execute workflow
# ---------------------------------------------------------------------------

@router.post(
    "/{workflow_id}/execute",
    response_model=ExecuteResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        401: {"model": ApiErrorResponse},
        403: {"model": ApiErrorResponse},
        404: {"model": ApiErrorResponse},
        409: {"model": ApiErrorResponse},
        501: {"model": ApiErrorResponse},
    },
)
async def execute_workflow(
    request: Request,
    organization_id: UUID,
    workflow_id: UUID,
    data: ExecuteRequest,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Execute a workflow."""
    # Check permissions
    await require_permission("workflow:execute")(request, db)
    
    # Get workflow
    workflow = await db.execute(
        select(Workflow).where(
            Workflow.id == workflow_id,
            Workflow.organization_id == organization_id,
            Workflow.deleted_at.is_(None),
        )
    )
    workflow = workflow.scalar_one_or_none()
    if not workflow:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Workflow not found", "code": "WORKFLOW_NOT_FOUND"},
        )
    
    # Check if workflow is runnable
    if workflow.status != "active":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "Workflow must be published to execute", "code": "WORKFLOW_NOT_ACTIVE"},
        )
    
    # Get runtime
    runtime = get_runtime()
    
    # Create execution
    execution_id = await runtime.create_execution(
        workflow_id=str(workflow_id),
        organization_id=str(organization_id),
        triggered_by=auth_context.user_id,
        trigger_input=data.input or {},
        version=data.version,
    )
    
    # Start execution (async)
    await runtime.start_execution(execution_id)
    
    return ExecuteResponse(
        execution_id=execution_id,
        status="queued",
        message="Workflow execution started",
    )


# ---------------------------------------------------------------------------
# List executions
# ---------------------------------------------------------------------------

@router.get(
    "/{workflow_id}/executions",
    response_model=ExecutionListResponse,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def list_executions(
    request: Request,
    organization_id: UUID,
    workflow_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """List executions for a workflow."""
    await require_permission("execution:read")(request, db)
    
    # Verify workflow exists
    workflow = await db.execute(
        select(Workflow).where(
            Workflow.id == workflow_id,
            Workflow.organization_id == organization_id,
            Workflow.deleted_at.is_(None),
        )
    )
    if not workflow.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Workflow not found", "code": "WORKFLOW_NOT_FOUND"},
        )
    
    query = select(WorkflowExecution).where(
        WorkflowExecution.workflow_id == workflow_id,
        WorkflowExecution.organization_id == organization_id,
    )
    count_query = select(func.count(WorkflowExecution.id)).where(
        WorkflowExecution.workflow_id == workflow_id,
        WorkflowExecution.organization_id == organization_id,
    )
    
    if status_filter:
        try:
            status_enum = WorkflowExecutionStatus(status_filter)
            query = query.where(WorkflowExecution.status == status_enum)
            count_query = count_query.where(WorkflowExecution.status == status_enum)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": f"Invalid status: {status_filter}", "code": "INVALID_STATUS"},
            )
    
    total = (await db.execute(count_query)).scalar_one()
    query = query.order_by(WorkflowExecution.created_at.desc()).limit(page_size).offset((page - 1) * page_size)
    executions = list((await db.execute(query)).scalars().all())
    
    items = []
    for e in executions:
        items.append(ExecutionResponse(
            id=e.id,
            organization_id=e.organization_id,
            workflow_id=e.workflow_id,
            workflow_version_id=e.workflow_version_id,
            status=e.status.value if hasattr(e.status, "value") else str(e.status),
            trigger_type=e.trigger_type.value if hasattr(e.trigger_type, "value") else str(e.trigger_type),
            started_at=e.started_at,
            completed_at=e.completed_at,
            error_code=e.error_code,
            error_message=e.error_message,
            created_at=e.created_at,
        ))
    
    from openagent.db.pagination import create_pagination_meta
    return ExecutionListResponse(data=items, meta=create_pagination_meta(page, page_size, total))


# ---------------------------------------------------------------------------
# Get execution detail
# ---------------------------------------------------------------------------

@router.get(
    "/{workflow_id}/executions/{execution_id}",
    response_model=ExecutionDetailResponse,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def get_execution(
    request: Request,
    organization_id: UUID,
    workflow_id: UUID,
    execution_id: UUID,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Get execution detail with node runs and events."""
    await require_permission("execution:read")(request, db)
    execution = await _get_execution_or_404(db, organization_id, execution_id)
    
    # Verify workflow_id matches
    if execution.workflow_id != workflow_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Execution not found for this workflow", "code": "EXECUTION_NOT_FOUND"},
        )
    
    # Get node runs
    from openagent.db.models import WorkflowExecution as WE
    # For now, we don't have a separate node_runs table, so we'll extract from execution metadata
    node_runs = []
    if execution.metadata and "node_runs" in execution.metadata:
        for nr in execution.metadata["node_runs"]:
            node_runs.append({
                "node_id": nr.get("node_id"),
                "node_type": nr.get("node_type"),
                "node_name": nr.get("node_name"),
                "status": nr.get("status"),
                "outputs": nr.get("outputs"),
                "error": nr.get("error"),
                "error_code": nr.get("error_code"),
                "started_at": nr.get("started_at"),
                "completed_at": nr.get("completed_at"),
                "attempt": nr.get("attempt", 1),
            })
    
    # Get events
    events_result = await db.execute(
        select(ExecutionEvent)
        .where(ExecutionEvent.workflow_execution_id == execution_id)
        .order_by(ExecutionEvent.sequence)
    )
    events = []
    for e in events_result.scalars().all():
        events.append(EventResponse(
            id=e.id,
            execution_id=e.workflow_execution_id,
            event_type=e.event_type,
            node_id=str(e.node_id) if e.node_id else None,
            sequence=e.sequence,
            timestamp=e.timestamp,
            payload=e.payload,
        ))
    
    return ExecutionDetailResponse(
        id=execution.id,
        organization_id=execution.organization_id,
        workflow_id=execution.workflow_id,
        workflow_version_id=execution.workflow_version_id,
        status=execution.status.value if hasattr(execution.status, "value") else str(execution.status),
        trigger_type=execution.trigger_type.value if hasattr(execution.trigger_type, "value") else str(execution.trigger_type),
        started_at=execution.started_at,
        completed_at=execution.completed_at,
        error_code=execution.error_code,
        error_message=execution.error_message,
        created_at=execution.created_at,
        node_runs=node_runs,
        events=events,
    )


# ---------------------------------------------------------------------------
# Cancel execution
# ---------------------------------------------------------------------------

@router.post(
    "/{workflow_id}/executions/{execution_id}/cancel",
    response_model=CancelResponse,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def cancel_execution(
    request: Request,
    organization_id: UUID,
    workflow_id: UUID,
    execution_id: UUID,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Cancel a running execution."""
    await require_permission("execution:cancel")(request, db)
    execution = await _get_execution_or_404(db, organization_id, execution_id)
    
    if execution.workflow_id != workflow_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Execution not found for this workflow", "code": "EXECUTION_NOT_FOUND"},
        )
    
    if execution.status not in [
        WorkflowExecutionStatus.QUEUED,
        WorkflowExecutionStatus.RUNNING,
        WorkflowExecutionStatus.WAITING,
        WorkflowExecutionStatus.PAUSED,
    ]:
        return CancelResponse(
            status="already_terminal",
            message=f"Execution is already in terminal state: {execution.status.value}",
        )
    
    execution.status = WorkflowExecutionStatus.CANCELLED
    execution.completed_at = datetime.now(timezone.utc)
    await db.commit()
    
    return CancelResponse(
        status="cancelled",
        message="Execution cancelled",
    )


# ---------------------------------------------------------------------------
# Retry execution
# ---------------------------------------------------------------------------

@router.post(
    "/{workflow_id}/executions/{execution_id}/retry",
    response_model=RetryResponse,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def retry_execution(
    request: Request,
    organization_id: UUID,
    workflow_id: UUID,
    execution_id: UUID,
    data: RetryRequest = RetryRequest(),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Retry a failed execution."""
    await require_permission("execution:retry")(request, db)
    execution = await _get_execution_or_404(db, organization_id, execution_id)
    
    if execution.workflow_id != workflow_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Execution not found for this workflow", "code": "EXECUTION_NOT_FOUND"},
        )
    
    if execution.status not in [WorkflowExecutionStatus.FAILED, WorkflowExecutionStatus.CANCELLED, WorkflowExecutionStatus.TIMED_OUT]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "Only failed, cancelled, or timed out executions can be retried", "code": "NOT_RETRYABLE"},
        )
    
    # Reset execution to queued
    execution.status = WorkflowExecutionStatus.QUEUED
    execution.error_message = None
    execution.error_code = None
    execution.completed_at = None
    execution.started_at = None
    execution.metadata = {**(execution.metadata or {}), "retry_count": (execution.metadata or {}).get("retry_count", 0) + 1}
    
    await db.commit()
    
    # Re-trigger execution via runtime
    runtime = get_runtime()
    await runtime.start_execution(str(execution.id))
    
    return RetryResponse(
        status="retry_queued",
        message="Execution re-queued for retry",
    )


# ---------------------------------------------------------------------------
# Resume execution (MP19: approval-bound, idempotent, no side-effect replay)
# ---------------------------------------------------------------------------

@router.post(
    "/{workflow_id}/executions/{execution_id}/resume",
    response_model=ResumeResponse,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}, 409: {"model": ApiErrorResponse}},
)
async def resume_execution(
    request: Request,
    organization_id: UUID,
    workflow_id: UUID,
    execution_id: UUID,
    data: ResumeRequest,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Resume a WAITING execution after human approval.

    The approval must be APPROVED, belong to this organization, reference
    this execution, and be unexpired. It is consumed single-use, so replaying
    the same approval cannot duplicate side effects.
    """
    await require_permission("execution:retry")(request, db)
    from openagent.approvals.engine import ApprovalEngine, ApprovalError
    from openagent.db.models.approval import Approval, ApprovalStatus

    execution = await _get_execution_or_404(db, organization_id, execution_id)
    if execution.workflow_id != workflow_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Execution not found for this workflow", "code": "EXECUTION_NOT_FOUND"},
        )
    if execution.status != WorkflowExecutionStatus.WAITING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": f"Only WAITING executions can be resumed (is {execution.status.value})",
                    "code": "NOT_WAITING"},
        )
    result = await db.execute(select(Approval).where(Approval.id == data.approval_id))
    approval = result.scalar_one_or_none()
    if approval is None or approval.organization_id != organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail={"error": "Approval not found", "code": "APPROVAL_NOT_FOUND"})
    payload = approval.payload or {}
    if payload.get("workflow_execution_id") not in (str(execution_id), str(execution.id)):
        # Fall back to target binding for approvals parked by node executors.
        if payload.get("target_id") not in (str(execution_id),):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"error": "Approval does not authorize this execution",
                        "code": "APPROVAL_SCOPE_MISMATCH"})
    if approval.status != ApprovalStatus.APPROVED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": f"Approval is {approval.status.value}, not approved",
                    "code": "APPROVAL_NOT_GRANTED"})
    engine = ApprovalEngine(db)
    try:
        await engine.begin_execution(
            data.approval_id, organization_id=organization_id,
            action_type=str(payload.get("action_type") or "workflow.resume"),
            action_category=str(payload.get("action_category") or "WRITE"),
            target_type=str(payload.get("target_type") or "workflow_execution"),
            target_id=str(payload.get("target_id") or execution_id),
            params=dict(payload.get("requested_parameters") or {}),
            environment=str(payload.get("environment") or "development"))
        await engine.finish_execution(data.approval_id, organization_id=organization_id,
                                      success=True, result_ref=str(execution_id))
    except ApprovalError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail={"error": str(exc), "code": exc.code})
    execution.status = WorkflowExecutionStatus.QUEUED
    execution.error_message = None
    execution.error_code = None
    await db.commit()
    runtime = get_runtime()
    await runtime.start_execution(str(execution.id))
    return ResumeResponse(status="resume_queued", message="Execution resumed after approval")


class ExecutionVerifyRequest(BaseModel):
    required_nodes: List[str] = Field(default_factory=list)
    forbid_failed: bool = True


@router.post(
    "/{workflow_id}/executions/{execution_id}/verify",
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def verify_execution(
    request: Request,
    organization_id: UUID,
    workflow_id: UUID,
    execution_id: UUID,
    data: ExecutionVerifyRequest,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Verify a workflow execution: required nodes succeeded, no failures.

    Node states come from execution metadata (observable), never from claims.
    """
    await require_permission("evaluation:create")(request, db)
    execution = await _get_execution_or_404(db, organization_id, execution_id)
    if execution.workflow_id != workflow_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Execution not found for this workflow", "code": "EXECUTION_NOT_FOUND"},
        )
    node_states: Dict[str, str] = {}
    if execution.metadata and "node_runs" in execution.metadata:
        for nr in execution.metadata["node_runs"]:
            if isinstance(nr, dict) and nr.get("node_id"):
                node_states[str(nr["node_id"])] = str(nr.get("status", "unknown"))
    from openagent.evaluator.integrations import verify_workflow_execution
    from openagent.evaluator.metrics import inc as metrics_inc
    outcome = await verify_workflow_execution(
        db, organization_id=organization_id, workflow_id=workflow_id,
        workflow_execution_id=execution_id, node_states=node_states,
        required_nodes=data.required_nodes, forbid_failed=data.forbid_failed)
    await db.commit()
    metrics_inc("evaluations_total")
    return outcome


# ---------------------------------------------------------------------------
# Execution events
# ---------------------------------------------------------------------------

@router.get(
    "/{workflow_id}/executions/{execution_id}/events",
    response_model=EventsResponse,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def get_execution_events(
    request: Request,
    organization_id: UUID,
    workflow_id: UUID,
    execution_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Get execution events."""
    await require_permission("execution:read")(request, db)
    execution = await _get_execution_or_404(db, organization_id, execution_id)
    
    if execution.workflow_id != workflow_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Execution not found for this workflow", "code": "EXECUTION_NOT_FOUND"},
        )
    
    total_result = await db.execute(
        select(func.count(ExecutionEvent.id)).where(ExecutionEvent.workflow_execution_id == execution_id)
    )
    total = total_result.scalar_one()
    
    result = await db.execute(
        select(ExecutionEvent)
        .where(ExecutionEvent.workflow_execution_id == execution_id)
        .order_by(ExecutionEvent.sequence)
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    items = [EventResponse.model_validate(e) for e in result.scalars().all()]
    
    from openagent.db.pagination import create_pagination_meta
    return EventsResponse(data=items, meta=create_pagination_meta(page, page_size, total))


# ---------------------------------------------------------------------------
# Node runs
# ---------------------------------------------------------------------------

class NodeRunResponse(BaseModel):
    node_id: str
    node_type: str
    node_name: str
    status: str
    outputs: Dict[str, Any] = {}
    error: Optional[str] = None
    error_code: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    attempt: int = 1


class NodeRunsResponse(BaseModel):
    execution_id: UUID
    node_runs: List[NodeRunResponse]


@router.get(
    "/{workflow_id}/executions/{execution_id}/nodes",
    response_model=NodeRunsResponse,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def get_execution_node_runs(
    request: Request,
    organization_id: UUID,
    workflow_id: UUID,
    execution_id: UUID,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Get node runs for an execution."""
    await require_permission("execution:read")(request, db)
    execution = await _get_execution_or_404(db, organization_id, execution_id)
    
    if execution.workflow_id != workflow_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Execution not found for this workflow", "code": "EXECUTION_NOT_FOUND"},
        )
    
    node_runs = []
    if execution.metadata and "node_runs" in execution.metadata:
        for nr in execution.metadata["node_runs"]:
            node_runs.append(NodeRunResponse(
                node_id=nr.get("node_id", ""),
                node_type=nr.get("node_type", ""),
                node_name=nr.get("node_name", ""),
                status=nr.get("status", "unknown"),
                outputs=nr.get("outputs", {}),
                error=nr.get("error"),
                error_code=nr.get("error_code"),
                started_at=nr.get("started_at"),
                completed_at=nr.get("completed_at"),
                attempt=nr.get("attempt", 1),
            ))
    
    return NodeRunsResponse(execution_id=execution_id, node_runs=node_runs)


# Register execution routes
execution_router = router