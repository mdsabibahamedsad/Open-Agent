"""Memory API endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.api.dependencies import get_current_org_context, require_permission
from openagent.db.models import Organization
from openagent.db.models.memory import (
    Memory, MemoryType, MemoryScope, MemoryVisibility, MemoryStatus,
    MemoryEmbeddingStatus, MemorySourceType, MemoryVisibility,
    MemoryAccessLog, MemoryEmbedding, MemoryLink, MemoryConflict,
    MemoryConsolidationJob, MemoryPolicy, MemoryLink, MemoryConflict,
    MemoryConsolidationJob, MemoryPolicy,
)
from openagent.db.session import get_db
from openagent.management.memory_service import MemoryService
from openagent.api.v1.management import TeamFormRequest
from openagent.management.memory_jobs import (
    run_embedding_generation_job,
    run_embedding_retry_job,
    run_memory_expiration_job,
    run_memory_decay_job,
    run_consolidation_job,
    run_embedding_retry_job,
    run_embedding_cleanup_job,
)
from openagent.orchestration.config import OrchestrationOrgSettings
from openagent.schemas.base import ApiErrorResponse, PaginatedResponse

router = APIRouter(prefix="/organizations/{organization_id}/memory", tags=["memory"])


# ==================== Schemas ====================

class MemoryCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=50000)
    memory_type: str = Field(default="short_term", pattern="^(working|short_term|conversation|task|episodic|semantic|procedural|agent|team|organization|user|shared)$")
    scope: str = Field(default="conversation", pattern="^(global|platform|organization|department|team|user|agent|workflow|orchestration|task|conversation|private)$")
    visibility: str = Field(default="private", pattern="^(private|authorized|team|organization|shared)$")
    agent_id: Optional[UUID] = None
    user_id: Optional[UUID] = None
    team_id: Optional[UUID] = None
    task_id: Optional[UUID] = None
    conversation_id: Optional[UUID] = None
    agent_run_id: Optional[UUID] = None
    orchestration_run_id: Optional[UUID] = None
    source_type: str = Field(default="agent_output", pattern="^(user_message|agent_output|tool_result|document|workflow|task|system|imported|explicit|agent_inference|model_generated|consolidated)$")
    source_id: Optional[str] = Field(default=None, max_length=255)
    source_location: Optional[str] = None
    structured_data: Optional[Dict[str, Any]] = None
    tags: List[str] = []
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    confidence_source: Optional[str] = None
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    importance_factors: List[str] = []
    expires_at: Optional[datetime] = None
    visibility: str = Field(default="private", pattern="^(private|authorized|team|organization|shared)$")
    summary: Optional[str] = None
    idempotency_key: Optional[str] = Field(default=None, max_length=255)
    metadata: Optional[Dict[str, Any]] = None


class MemoryUpdate(BaseModel):
    content: Optional[str] = Field(default=None, min_length=1, max_length=50000)
    summary: Optional[str] = None
    structured_data: Optional[Dict[str, Any]] = None
    tags: Optional[List[str]] = None
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    importance: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    importance_factors: Optional[List[str]] = None
    tags: Optional[List[str]] = None
    visibility: Optional[str] = Field(default=None, pattern="^(private|authorized|team|organization|shared)$")
    expires_at: Optional[datetime] = None
    status: Optional[str] = Field(default=None, pattern="^(active|archived|expired|revoked|superseded|deleted|quarantined|pending)$")


class MemoryResponse(BaseModel):
    id: UUID
    organization_id: UUID
    user_id: Optional[UUID] = None
    agent_id: Optional[UUID] = None
    team_id: Optional[UUID] = None
    task_id: Optional[UUID] = None
    conversation_id: Optional[UUID] = None
    agent_run_id: Optional[UUID] = None
    orchestration_run_id: Optional[UUID] = None
    memory_type: str
    scope: str
    visibility: str
    content: str
    summary: Optional[str] = None
    structured_data: Dict[str, Any] = {}
    source_type: str
    source_id: Optional[str] = None
    source_location: Optional[str] = None
    tags: List[str] = []
    confidence: float
    confidence_source: Optional[str] = None
    importance: float
    importance_factors: List[str] = []
    tags: List[str] = []
    expires_at: Optional[datetime] = None
    status: str
    version: int
    parent_memory_id: Optional[UUID] = None
    superseded_by_id: Optional[UUID] = None
    change_reason: Optional[str] = None
    changed_by: Optional[UUID] = None
    access_count: int = 0
    last_accessed_at: Optional[datetime] = None
    last_accessed_by: Optional[UUID] = None
    embedding_status: str
    embedding_model: Optional[str] = None
    embedding_dimensions: Optional[int] = None
    embedded_at: Optional[datetime] = None
    conflict_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class MemoryDetailResponse(MemoryResponse):
    versions_count: int = 0
    latest_version: Optional[int] = None
    conflict: Optional[Dict[str, Any]] = None
    access_logs: List[Dict[str, Any]] = []


class MemoryListResponse(PaginatedResponse[MemoryResponse]):
    pass


class MemorySearch(BaseModel):
    query: Optional[str] = None
    scope: Optional[str] = None
    memory_type: Optional[str] = None
    tags: Optional[List[str]] = None
    agent_id: Optional[UUID] = None
    user_id: Optional[UUID] = None
    task_id: Optional[UUID] = None
    conversation_id: Optional[UUID] = None
    team_id: Optional[UUID] = None
    scope_filter: Optional[str] = None
    memory_type_filter: Optional[str] = None
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)
    use_vector_search: bool = True
    similarity_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    filters: Optional[Dict[str, Any]] = None


class MemorySearchResponse(BaseModel):
    memories: List[MemoryResponse]
    total: int
    query: str
    search_time_ms: float


class MemoryUpdateStatus(BaseModel):
    status: str = Field(..., pattern="^(active|archived|expired|revoked|superseded|deleted|quarantined|pending)$")


class MemoryTransition(BaseModel):
    new_type: str = Field(..., pattern="^(working|short_term|conversation|task|episodic|semantic|procedural|agent|team|organization|user|shared)$")
    new_scope: str = Field(..., pattern="^(global|platform|organization|department|team|user|agent|workflow|orchestration|task|conversation|private)$")
    promoted_by: UUID


class DelegationTransition(BaseModel):
    status: str = Field(..., pattern="^(accepted|rejected|expired|cancelled|completed)$")
    reason: str = ""
    decided_by: Optional[UUID] = None


class HandoffTransition(BaseModel):
    status: str = Field(..., pattern="^(accepted|rejected|executing|completed|expired|cancelled)$")
    actor: Optional[UUID] = None


class ReviewCreate(BaseModel):
    run_id: UUID
    task_id: UUID
    reviewer_agent_id: Optional[UUID] = None
    output: Optional[Dict[str, Any]] = None
    status_override: Optional[str] = Field(default=None, pattern="^(approved|revision_required|rejected|escalate)$")


class EscalationCreate(BaseModel):
    source_agent_id: Optional[UUID] = None
    task_id: Optional[UUID] = None
    run_id: Optional[UUID] = None
    trigger: str = Field(default="blocked", pattern="^(blocked|permission_denied|budget_exceeded|deadline_risk|repeated_failure|high_risk_action|ambiguous_requirement|conflicting_outputs|missing_capability)$")
    reason: str = ""
    severity: str = Field(default="warning", pattern="^(info|warning|high|critical)$")
    recommended_action: str = ""
    chain: Optional[List[str]] = None
    idempotency_key: Optional[str] = None


class EscalationTransition(BaseModel):
    note: str = ""


class TeamCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    manager_agent_id: Optional[UUID] = None
    team_type: str = Field(default="temporary", pattern="^(persistent|temporary|orchestration_scoped|task_scoped)$")
    run_id: Optional[UUID] = None
    task_id: Optional[UUID] = None
    department_id: Optional[UUID] = None
    charter: Optional[Dict[str, Any]] = None
    budget: Dict[str, Any] = {}
    idempotency_key: Optional[str] = None


class TeamTransition(BaseModel):
    status: str = Field(..., pattern="^(forming|active|winding_down|completed|cancelled)$")


class MemberAdd(BaseModel):
    agent_id: UUID
    role: str = "worker"
    responsibilities: List[str] = []


class CollaborationCreate(BaseModel):
    run_id: UUID
    from_agent_id: UUID
    to_agent_id: UUID
    action: str = Field(..., pattern="^(request_information|share_result|request_review|request_artifact|request_analysis)$")
    task_id: Optional[UUID] = None
    payload: Dict[str, Any] = {}


class CollaborationTransition(BaseModel):
    action: str = Field(..., pattern="^(accept|decline|complete|cancel)$")


class ProgressReport(BaseModel):
    agent_id: UUID
    progress: float = Field(default=0.0, ge=0.0, le=1.0)
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
    name: str = Field(min_length=1, max_length=128)
    description: str = ""


class AvailabilitySet(BaseModel):
    state: str = Field(..., pattern="^(available|busy|overloaded|offline|disabled|unhealthy)$")


class CapacitySet(BaseModel):
    max_concurrent_tasks: Optional[int] = Field(default=None, ge=1, le=100)
    max_concurrent_runs: Optional[int] = Field(default=None, ge=1, le=10)
    max_daily_cost: Optional[float] = Field(default=None, ge=0.0)
    max_token_budget: Optional[int] = Field(default=None, ge=0)


class HandoffCreate(BaseModel):
    run_id: UUID
    task_id: UUID
    source_agent_id: Optional[UUID] = None
    target_agent_id: Optional[UUID] = None
    mode: str = Field(default="full_handoff", pattern="^(full_handoff|partial_handoff|review_handoff|escalation_handoff|specialist_handoff|failure_handoff)$")
    package: Dict[str, Any] = {}
    contract_id: Optional[UUID] = None
    idempotency_key: Optional[str] = None


class HandoffTransition(BaseModel):
    status: str = Field(..., pattern="^(accept|reject|execute|complete|expire|cancel)$")


# ==================== Helper Functions ====================

def _service(db: AsyncSession, org: Optional[Organization] = None) -> MemoryService:
    settings = OrchestrationOrgSettings.from_organization_settings(
        getattr(org, "settings", None) if org else None
    )
    return MemoryService(db, settings)


def _check_org(organization_id: UUID, auth_context: Any) -> None:
    if auth_context.organization_id != organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "Organization mismatch", "code": "FORBIDDEN"},
        )


def _fail(exc: Exception) -> None:
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
        status_code=mapping.get(getattr(exc, "code", "UNKNOWN"), status.HTTP_400_BAD_REQUEST),
        detail={"error": getattr(exc, "message", str(exc)), "code": getattr(exc, "code", "UNKNOWN")},
    )


def _dump(row: Any, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    data: Dict[str, Any] = {}
    for column in row.__table__.columns:
        value = getattr(row, column.name, None)
        if hasattr(value, "value"):
            value = value.value
        elif isinstance(value, UUID):
            value = str(value)
        elif isinstance(value, datetime):
            value = value.isoformat()
        data[column.name] = value
    if extra:
        data.update(extra)
    return data


# ==================== Memory Endpoints ====================

@router.post(
    "",
    response_model=MemoryResponse,
    status_code=status.HTTP_201_CREATED,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}},
)
async def create_memory(
    organization_id: UUID,
    payload: MemoryCreate,
    request: Request,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:create")(request, db)
    
    idempotency_key = payload.idempotency_key or request.headers.get("Idempotency-Key")
    service = _service(db)
    
    try:
        memory = await service.create_memory(
            organization_id=organization_id,
            content=payload.content,
            memory_type=MemoryType(payload.memory_type),
            scope=MemoryScope(payload.scope),
            visibility=MemoryVisibility(payload.visibility),
            agent_id=payload.agent_id,
            user_id=payload.user_id,
            team_id=payload.team_id,
            task_id=payload.task_id,
            conversation_id=payload.conversation_id,
            agent_run_id=payload.agent_run_id,
            orchestration_run_id=payload.orchestration_run_id,
            source_type=MemorySourceType(payload.source_type),
            source_id=payload.source_id,
            source_location=payload.source_location,
            structured_data=payload.structured_data,
            tags=payload.tags,
            confidence=payload.confidence,
            confidence_source=payload.confidence_source,
            importance=payload.importance,
            importance_factors=payload.importance_factors,
            expires_at=payload.expires_at,
            summary=payload.summary,
            actor=auth_context.user_id,
            idempotency_key=idempotency_key,
            metadata=payload.metadata,
        )
    except Exception as exc:
        _fail(exc)
    
    return MemoryResponse.model_validate(memory, from_attributes=True)


@router.get("", response_model=MemoryListResponse)
async def list_memories(
    organization_id: UUID,
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    memory_type: Optional[str] = Query(None),
    scope: Optional[str] = Query(None),
    agent_id: Optional[UUID] = Query(None),
    user_id: Optional[UUID] = Query(None),
    task_id: Optional[UUID] = Query(None),
    conversation_id: Optional[UUID] = Query(None),
    team_id: Optional[UUID] = Query(None),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:read")(request, db)
    
    service = _service(db)
    try:
        memories = await service.retrieve_memories(
            organization_id=organization_id,
            query="",
            scope_filter=scope,
            memory_type_filter=memory_type,
            agent_id=agent_id,
            user_id=user_id,
            task_id=task_id,
            conversation_id=conversation_id,
            team_id=team_id,
            limit=page_size,
            offset=(page - 1) * page_size,
        )
    except Exception as exc:
        _fail(exc)
    
    total = await service.memory_repo.count(organization_id=organization_id)
    total_pages = max(1, (total + page_size - 1) // page_size)
    
    return {
        "data": [MemoryResponse.model_validate(m, from_attributes=True) for m in memories],
        "meta": {
            "page": page,
            "page_size": page_size,
            "total_items": total,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_prev": page > 1,
        },
    }


@router.get("/{memory_id}", response_model=MemoryDetailResponse)
async def get_memory(
    organization_id: UUID,
    memory_id: UUID,
    request: Request,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:read")(request, db)
    
    service = _service(db)
    try:
        memory = await service.memory_repo.get_by_id_with_org(memory_id, organization_id)
        if not memory:
            raise HTTPException(status_code=404, detail={"error": "Memory not found", "code": "NOT_FOUND"})
    except Exception as exc:
        _fail(exc)
    
    # Get versions count
    versions = await service.version_repo.list_by_memory(memory_id, limit=100)
    
    # Get access logs
    access_logs = await service.access_log_repo.list_by_memory(memory_id, limit=50)
    
    # Get conflict if any
    conflict = None
    if memory.conflict_id:
        conflict_obj = await service.conflict_repo.get_by_id(memory.conflict_id)
        if conflict_obj:
            conflict = {
                "id": str(conflict_obj.id),
                "status": conflict_obj.status,
                "claims": conflict_obj.claims,
                "evidence": conflict_obj.evidence,
            }
    
    return MemoryDetailResponse(
        **MemoryResponse.model_validate(memory, from_attributes=True).model_dump(),
        versions_count=len(versions),
        latest_version=max((v.version for v in versions), default=0) if versions else None,
        conflict=conflict,
        access_logs=[{
            "id": str(log.id),
            "access_type": log.access_type,
            "accessed_by": str(log.accessed_by) if log.accessed_by else None,
            "agent_id": str(log.agent_id) if log.agent_id else None,
            "query": log.query,
            "result_count": log.result_count,
            "created_at": log.created_at.isoformat(),
        } for log in access_logs],
    )


@router.patch("/{memory_id}", response_model=MemoryResponse)
async def update_memory(
    organization_id: UUID,
    memory_id: UUID,
    payload: MemoryUpdate,
    request: Request,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:update")(request, db)
    
    service = _service(db)
    try:
        memory = await service.update_memory(
                memory_id=memory_id,
                organization_id=organization_id,
                content=payload.content,
                summary=payload.summary,
                structured_data=payload.structured_data,
                tags=payload.tags,
                confidence=payload.confidence,
                importance=payload.importance,
                importance_factors=payload.importance_factors,
                visibility=payload.visibility,
                expires_at=payload.expires_at,
                status=payload.status,
                changed_by=auth_context.user_id,
                change_reason="Manual update via API",
            )
    except Exception as exc:
        _fail(exc)
    
    return MemoryResponse.model_validate(memory, from_attributes=True)


@router.post("/{memory_id}/transition", response_model=MemoryResponse)
async def transition_memory(
    organization_id: UUID,
    memory_id: UUID,
    payload: MemoryTransition,
    request: Request,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:update")(request, db)
    
    service = _service(db)
    try:
        memory = await service.promote_memory(
            memory_id=memory_id,
            organization_id=organization_id,
            new_type=MemoryType(payload.new_type),
            new_scope=MemoryScope(payload.new_scope),
            promoted_by=payload.promoted_by,
        )
    except Exception as exc:
        _fail(exc)
    
    return MemoryResponse.model_validate(memory, from_attributes=True)


@router.post("/{memory_id}/supersede", response_model=MemoryResponse)
async def supersede_memory(
    organization_id: UUID,
    memory_id: UUID,
    request: Request,
    new_content: str = Body(..., embed=True),
    superseded_by_id: UUID = Body(..., embed=True),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:update")(request, db)
    
    service = _service(db)
    try:
        memory = await service.supersede_memory(
            memory_id=memory_id,
            organization_id=organization_id,
            new_content=new_content,
            superseded_by_id=superseded_by_id,
            changed_by=auth_context.user_id,
        )
    except Exception as exc:
        _fail(exc)
    
    return MemoryResponse.model_validate(memory, from_attributes=True)


@router.post("/{memory_id}/revoke", response_model=MemoryResponse)
async def revoke_memory(
    organization_id: UUID,
    memory_id: UUID,
    request: Request,
    reason: str = Body(..., embed=True),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:update")(request, db)
    
    service = _service(db)
    try:
        memory = await service.revoke_memory(
            memory_id=memory_id,
            organization_id=organization_id,
            reason=reason,
            revoked_by=auth_context.user_id,
        )
    except Exception as exc:
        _fail(exc)
    
    return MemoryResponse.model_validate(memory, from_attributes=True)


@router.delete("/{memory_id}")
async def delete_memory(
    organization_id: UUID,
    memory_id: UUID,
    request: Request,
    hard: bool = Query(False),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:delete")(request, db)
    
    service = _service(db)
    try:
        await service.delete_memory(
            memory_id=memory_id,
            organization_id=organization_id,
            hard=hard,
        )
    except Exception as exc:
        _fail(exc)
    
    return {"status": "deleted"}


@router.get("/search", response_model=MemorySearchResponse)
async def search_memories(
    organization_id: UUID,
    request: Request,
    payload: MemorySearch = Body(...),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:read")(request, db)
    
    service = _service(db)
    try:
        start = datetime.now()
        memories = await service.retrieve_memories(
            organization_id=organization_id,
            query=payload.query or "",
            scope_filter=payload.scope,
            memory_type_filter=payload.memory_type,
            tags=payload.tags,
            agent_id=payload.agent_id,
            user_id=payload.user_id,
            task_id=payload.task_id,
            conversation_id=payload.conversation_id,
            team_id=payload.team_id,
            limit=payload.limit,
            offset=payload.offset,
            use_vector_search=payload.use_vector_search,
            query_embedding=None,  # Would need to generate from query
            similarity_threshold=payload.similarity_threshold,
            filters=payload.filters,
        )
        search_time = (datetime.now() - start).total_seconds() * 1000
        
        total = await service.memory_repo.count(
            organization_id=organization_id,
        )
    except Exception as exc:
        _fail(exc)
    
    return MemorySearchResponse(
        memories=[MemoryResponse.model_validate(m, from_attributes=True) for m in memories],
        total=total,
        query=payload.query or "",
        search_time_ms=search_time,
    )


# ==================== Review Endpoints ====================

@router.post("/{memory_id}/review", response_model=MemoryResponse)
async def review_memory(
    organization_id: UUID,
    memory_id: UUID,
    payload: ReviewCreate,
    request: Request,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:read")(request, db)
    
    service = _service(db)
    try:
        memory = await service.submit_review(
            memory_id=memory_id,
            organization_id=organization_id,
            reviewer_id=payload.reviewer_agent_id,
            output=payload.output,
            status_override=payload.status_override,
            actor=auth_context.user_id,
        )
    except Exception as exc:
        _fail(exc)
    
    return MemoryResponse.model_validate(memory, from_attributes=True)


@router.post("/{memory_id}/correct", response_model=MemoryResponse)
async def correct_memory(
    organization_id: UUID,
    memory_id: UUID,
    corrected_content: str = Body(..., embed=True),
    reason: str = Body(..., embed=True),
    request: Request = None,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:update")(request, db)
    
    service = _service(db)
    try:
        memory = await service.correct_memory(
            memory_id=memory_id,
            organization_id=organization_id,
            corrected_content=corrected_content,
            corrected_by=auth_context.user_id,
            reason=reason,
        )
    except Exception as exc:
        _fail(exc)
    
    return MemoryResponse.model_validate(memory, from_attributes=True)


# ==================== Conflict Endpoints ====================

@router.get("/conflicts")
async def list_conflicts(
    organization_id: UUID,
    request: Request,
    status_filter: Optional[str] = Query(None, alias="status"),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:read")(request, db)
    
    service = _service(db)
    try:
        if status_filter:
            # Filter by status
            pass
        conflicts = await service.conflict_repo.list_open(organization_id)
    except Exception as exc:
        _fail(exc)
    
    return {"data": [{
        "id": str(c.id),
        "status": c.status,
        "claims": c.claims,
        "evidence": c.evidence,
        "confidence": c.confidence,
        "created_at": c.created_at.isoformat(),
    } for c in conflicts]}


@router.post("/conflicts/{conflict_id}/resolve")
async def resolve_conflict(
    organization_id: UUID,
    conflict_id: UUID,
    resolution: str = Body(..., embed=True),
    reason: str = Body("", embed=True),
    request: Request = None,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:update")(request, db)
    
    service = _service(db)
    try:
        conflict = await service.resolve_conflict(
            conflict_id=conflict_id,
            organization_id=organization_id,
            resolution=resolution,
            resolved_by=auth_context.user_id,
            reason=reason,
        )
    except Exception as exc:
        _fail(exc)
    
    return {"status": "resolved", "conflict_id": str(conflict_id)}


# ==================== Consolidation ====================

@router.post("/consolidate")
async def run_consolidation(
    organization_id: UUID,
    scope: str = Body("organization", embed=True),
    scope_id: Optional[UUID] = Body(None, embed=True),
    memory_type: Optional[str] = Body(None, embed=True),
    request: Request = None,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:create")(request, db)
    
    try:
        result = await run_consolidation_job(
            db, organization_id=str(organization_id),
            scope=scope, scope_id=str(scope_id) if scope_id else None,
            memory_type=memory_type,
        )
    except Exception as exc:
        _fail(exc)
    
    return result


# ==================== Jobs ====================

@router.post("/jobs/embeddings/generate")
async def generate_embeddings_job(
    organization_id: UUID,
    request: Request,
    batch_size: int = Query(50),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:create")(request, db)
    
    try:
        count = await run_embedding_generation_job(db)
    except Exception as exc:
        _fail(exc)
    
    return {"generated": count}


@router.post("/jobs/embeddings/retry")
async def retry_embeddings_job(
    organization_id: UUID,
    request: Request,
    max_retries: int = Query(3),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:create")(request, db)
    
    try:
        count = await run_embedding_retry_job(db)
    except Exception as exc:
        _fail(exc)
    
    return {"retried": count}


@router.post("/jobs/expiration")
async def expire_memories_job(
    organization_id: UUID,
    request: Request,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:create")(request, db)
    
    try:
        count = await run_memory_expiration_job(db)
    except Exception as exc:
        _fail(exc)
    
    return {"expired": count}


@router.post("/jobs/decay")
async def decay_memories_job(
    organization_id: UUID,
    request: Request,
    organization_id_filter: Optional[UUID] = Query(None, alias="organization_id"),
    decay_threshold_days: int = Query(90),
    decay_factor: float = Query(0.9),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:create")(request, db)
    
    try:
        count = await run_memory_decay_job(db, organization_id=str(organization_id_filter) if organization_id_filter else None)
    except Exception as exc:
        _fail(exc)
    
    return {"decayed": count}


@router.post("/jobs/consolidation")
async def consolidation_job(
    organization_id: UUID,
    request: Request,
    scope: str = Body("organization", embed=True),
    scope_id: Optional[UUID] = Body(None, embed=True),
    memory_type: Optional[str] = Body(None, embed=True),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:create")(request, db)
    
    try:
        result = await run_consolidation_job(
            db, organization_id=str(organization_id),
            scope=scope, scope_id=str(scope_id) if scope_id else None,
            memory_type=memory_type,
        )
    except Exception as exc:
        _fail(exc)
    
    return result


@router.post("/jobs/embeddings/retry")
async def retry_embeddings_job(
    organization_id: UUID,
    request: Request,
    max_retries: int = Query(3),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:create")(request, db)
    
    try:
        count = await run_embedding_retry_job(db)
    except Exception as exc:
        _fail(exc)
    
    return {"retried": count}


@router.post("/jobs/embeddings/cleanup")
async def cleanup_embeddings_job(
    organization_id: UUID,
    request: Request,
    max_age_hours: int = Query(24),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:create")(request, db)
    
    try:
        count = await run_embedding_cleanup_job(db)
    except Exception as exc:
        _fail(exc)
    
    return {"cleaned": count}


# ==================== Handoff Endpoints ====================

@router.post("/handoffs", status_code=status.HTTP_201_CREATED)
async def create_handoff(
    organization_id: UUID,
    payload: HandoffCreate,
    request: Request,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:create")(request, db)
    
    service = _service(db)
    try:
        handoff = await service.prepare_handoff(
            organization_id=organization_id,
            run_id=payload.run_id,
            task_id=payload.task_id,
            source_agent_id=payload.source_agent_id,
            target_agent_id=payload.target_agent_id,
            mode=payload.mode,
            package=payload.package,
            contract_id=payload.contract_id,
            actor=auth_context.user_id,
            idempotency_key=payload.idempotency_key,
        )
    except Exception as exc:
        _fail(exc)
    
    return _dump(handoff)


@router.get("/handoffs")
async def list_handoffs(
    organization_id: UUID,
    request: Request,
    run_id: Optional[UUID] = Query(None),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:read")(request, db)
    
    service = _service(db)
    try:
        await service.orchestrator.get_run(organization_id, run_id) if run_id else None
        handoffs = await service.handoffs.list_by_run(run_id, limit=200) if run_id else []
    except Exception as exc:
        _fail(exc)
    
    return {"data": [_dump(h) for h in handoffs]}


@router.get("/handoffs/{handoff_id}")
async def get_handoff(
    organization_id: UUID,
    handoff_id: UUID,
    request: Request,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:read")(request, db)
    
    row = await _service(db).handoffs.get_by_id_with_org(handoff_id, organization_id)
    if row is None:
        raise HTTPException(status_code=404, detail={"error": "Handoff not found", "code": "NOT_FOUND"})
    return _dump(row)


@router.post("/handoffs/{handoff_id}/{action}")
async def transition_handoff(
    organization_id: UUID,
    handoff_id: UUID,
    action: str,
    request: Request,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:create")(request, db)
    
    mapping = {
        "accept": "accepted", "reject": "rejected", "execute": "executing",
        "complete": "completed", "expire": "expired", "cancel": "cancelled",
    }
    if action not in mapping:
        raise HTTPException(status_code=422, detail={"error": "Unknown action", "code": "INVALID_ACTION"})
    
    from openagent.db.models.management import HandoffPackageStatus as DBStatus
    try:
        handoff = await _service(db).transition_handoff(
            organization_id, handoff_id, DBStatus(mapping[action]),
            actor=auth_context.user_id,
        )
    except Exception as exc:
        _fail(exc)
    
    return _dump(handoff)


# ==================== Escalation Endpoints ====================

@router.post("/escalations", status_code=status.HTTP_201_CREATED)
async def create_escalation(
    organization_id: UUID,
    payload: EscalationCreate,
    request: Request,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:create")(request, db)
    
    try:
        escalation = await _service(db).open_escalation(
            organization_id, source_agent_id=payload.source_agent_id,
            task_id=payload.task_id, run_id=payload.run_id,
            trigger=payload.trigger, reason=payload.reason,
            severity=payload.severity, recommended_action=payload.recommended_action,
            chain=payload.chain, actor=auth_context.user_id,
            idempotency_key=payload.idempotency_key,
        )
    except Exception as exc:
        _fail(exc)
    
    return _dump(escalation)


@router.get("/escalations")
async def list_escalations(
    organization_id: UUID,
    request: Request,
    open_only: bool = Query(True),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:read")(request, db)
    
    service = _service(db)
    if open_only:
        escalations = await service.escalations.list_open(organization_id)
    else:
        escalations = await service.escalations.list(organization_id, limit=200)
    
    return {"data": [_dump(e) for e in escalations]}


@router.get("/escalations/{escalation_id}")
async def get_escalation(
    organization_id: UUID,
    escalation_id: UUID,
    request: Request,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:read")(request, db)
    
    row = await _service(db).escalations.get_by_id_with_org(escalation_id, organization_id)
    if row is None:
        raise HTTPException(status_code=404, detail={"error": "Not found", "code": "NOT_FOUND"})
    return _dump(row)


@router.post("/escalations/{escalation_id}/{action}")
async def transition_escalation(
    organization_id: UUID,
    escalation_id: UUID,
    action: str,
    payload: EscalationTransition,
    request: Request,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:create")(request, db)
    
    mapping = {
        "ack": "acknowledged", "acknowledge": "acknowledged",
        "progress": "in_progress", "resolve": "resolved",
        "chain": "escalated", "close": "closed",
    }
    if action not in mapping:
        raise HTTPException(status_code=422, detail={"error": "Unknown action", "code": "INVALID_ACTION"})
    
    from openagent.db.models.management import EscalationStatus as DBStatus
    try:
        row = await _service(db).transition_escalation(
            organization_id, escalation_id, DBStatus(mapping[action]),
            note=payload.note, actor=auth_context.user_id,
        )
    except Exception as exc:
        _fail(exc)
    
    return _dump(row)


# ==================== Dynamic Teams ====================

@router.post("/teams", status_code=status.HTTP_201_CREATED)
async def create_team(
    organization_id: UUID,
    payload: TeamCreate,
    request: Request,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:create")(request, db)
    
    try:
        team = await _service(db).create_team(
            organization_id, name=payload.name,
            manager_agent_id=payload.manager_agent_id,
            team_type=payload.team_type, run_id=payload.run_id,
            task_id=payload.task_id, department_id=payload.department_id,
            charter=payload.charter, budget=payload.budget,
            actor=auth_context.user_id, idempotency_key=payload.idempotency_key,
        )
    except Exception as exc:
        _fail(exc)
    
    return _dump(team)


@router.post("/teams/form", status_code=status.HTTP_201_CREATED)
async def form_team(
    organization_id: UUID,
    payload: TeamFormRequest,
    request: Request,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:create")(request, db)
    
    try:
        result = await _service(db).form_team_from_roles(
            organization_id,
            TeamFormationRequest(
                objective=payload.objective,
                required_roles=payload.required_roles,
                max_size=payload.max_size,
                team_type=DynamicTeamType(payload.team_type),
            ),
            run_id=payload.run_id,
            manager_agent_id=payload.manager_agent_id,
            actor=auth_context.user_id,
        )
    except Exception as exc:
        _fail(exc)
    
    return result


@router.get("/teams")
async def list_teams(
    organization_id: UUID,
    request: Request,
    run_id: Optional[UUID] = Query(None),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:read")(request, db)
    
    service = _service(db)
    try:
        if run_id:
            teams = await service.teams.list_by_run(run_id)
        else:
            teams = await service.teams.list(organization_id, limit=200)
    except Exception as exc:
        _fail(exc)
    
    return {"data": [_dump(t) for t in teams]}


@router.get("/teams/{team_id}")
async def get_team(
    organization_id: UUID,
    team_id: UUID,
    request: Request,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:read")(request, db)
    
    service = _service(db)
    try:
        team = await service.teams.get_by_id_with_org(team_id, organization_id)
        if team is None:
            raise HTTPException(status_code=404, detail={"error": "Team not found", "code": "NOT_FOUND"})
        members = await service.memberships.list_by_team(team.id)
    except Exception as exc:
        _fail(exc)
    
    return {
        **_dump(team),
        "members": [{
            "agent_id": str(m.agent_id),
            "role": m.role,
            "status": m.status,
            "responsibilities": m.responsibilities,
        } for m in members],
    }


@router.post("/teams/{team_id}/{action}")
async def transition_team(
    organization_id: UUID,
    team_id: UUID,
    action: str,
    request: Request,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:create")(request, db)
    
    mapping = {"form": "forming", "activate": "active", "wind_down": "winding_down", "complete": "completed", "cancel": "cancelled"}
    if action not in mapping:
        raise HTTPException(status_code=422, detail={"error": "Unknown action", "code": "INVALID_ACTION"})
    
    from openagent.db.models.management import DynamicTeamStatus as DBStatus
    try:
        team = await _service(db).transition_team(
            organization_id, team_id, DBStatus(mapping[action]), actor=auth_context.user_id
        )
    except Exception as exc:
        _fail(exc)
    
    return _dump(team)


@router.post("/teams/{team_id}/members", status_code=status.HTTP_201_CREATED)
async def add_team_member(
    organization_id: UUID,
    team_id: UUID,
    payload: MemberAdd,
    request: Request,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:create")(request, db)
    
    try:
        row = await _service(db).add_member(
            organization_id, team_id, payload.agent_id,
            role=payload.role, responsibilities=payload.responsibilities,
            actor=auth_context.user_id,
        )
    except Exception as exc:
        _fail(exc)
    
    return _dump(row)


@router.delete("/teams/{team_id}/members/{agent_id}")
async def remove_team_member(
    organization_id: UUID,
    team_id: UUID,
    agent_id: UUID,
    request: Request,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:create")(request, db)
    
    try:
        row = await _service(db).remove_member(
            organization_id, team_id, agent_id, actor=auth_context.user_id
        )
    except Exception as exc:
        _fail(exc)
    
    return _dump(row)


# ==================== Departments ====================

@router.post("/departments", status_code=status.HTTP_201_CREATED)
async def create_department(
    organization_id: UUID,
    payload: DepartmentCreate,
    request: Request,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:create")(request, db)
    
    try:
        row = await _service(db).create_department(
            organization_id, payload.name, description=payload.description,
            actor=auth_context.user_id,
        )
    except Exception as exc:
        _fail(exc)
    
    return _dump(row)


@router.get("/departments")
async def list_departments(
    organization_id: UUID,
    request: Request,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:read")(request, db)
    
    rows = await _service(db).departments.list(organization_id, limit=100)
    return {"data": [_dump(r) for r in rows]}


# ==================== Availability / Capacity ====================

@router.put("/agents/{agent_id}/availability")
async def set_availability(
    organization_id: UUID,
    agent_id: UUID,
    payload: AvailabilitySet,
    request: Request,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:create")(request, db)
    
    try:
        row = await _service(db).set_availability(
            organization_id, agent_id, payload.state, actor=auth_context.user_id
        )
    except Exception as exc:
        _fail(exc)
    
    return _dump(row)


@router.put("/agents/{agent_id}/capacity")
async def set_capacity(
    organization_id: UUID,
    agent_id: UUID,
    payload: CapacitySet,
    request: Request,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:create")(request, db)
    
    try:
        row = await _service(db).set_capacity(
            organization_id, agent_id,
            {k: v for k, v in payload.model_dump().items() if v is not None},
            actor=auth_context.user_id,
        )
    except Exception as exc:
        _fail(exc)
    
    return _dump(row)


# ==================== Collaborations ====================

@router.post("/collaborations", status_code=status.HTTP_201_CREATED)
async def create_collaboration(
    organization_id: UUID,
    payload: CollaborationCreate,
    request: Request,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:create")(request, db)
    
    try:
        row = await _service(db).request_collaboration(
            organization_id, payload.run_id,
            from_agent_id=payload.from_agent_id,
            to_agent_id=payload.to_agent_id,
            action=payload.action,
            task_id=payload.task_id,
            payload=payload.payload,
            actor=auth_context.user_id,
        )
    except Exception as exc:
        _fail(exc)
    
    return _dump(row)


@router.post("/collaborations/{collaboration_id}/{action}")
async def transition_collaboration(
    organization_id: UUID,
    collaboration_id: UUID,
    action: str,
    request: Request,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:create")(request, db)
    
    if action not in ("accept", "decline", "complete", "cancel"):
        raise HTTPException(status_code=422, detail={"error": "Unknown action", "code": "INVALID_ACTION"})
    
    mapping = {"accept": "accepted", "decline": "declined", "complete": "completed", "cancel": "cancelled"}
    try:
        row = await _service(db).transition_collaboration(
            organization_id, collaboration_id, mapping[action], actor=auth_context.user_id
        )
    except Exception as exc:
        _fail(exc)
    
    return _dump(row)


# ==================== Progress ====================

@router.post("/runs/{run_id}/tasks/{task_id}/progress")
async def report_progress(
    organization_id: UUID,
    run_id: UUID,
    task_id: UUID,
    payload: ProgressReport,
    request: Request,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:create")(request, db)
    
    try:
        result = await _service(db).report_progress(
            organization_id, run_id, task_id,
            agent_id=payload.agent_id, report=payload.model_dump(),
        )
    except Exception as exc:
        _fail(exc)
    
    return result


# ==================== Plan Versions ====================

@router.post("/runs/{run_id}/plan-versions", status_code=status.HTTP_201_CREATED)
async def create_plan_version(
    organization_id: UUID,
    run_id: UUID,
    payload: PlanVersionCreate,
    request: Request,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:create")(request, db)
    
    try:
        row = await _service(db).record_plan_version(
            organization_id, run_id,
            reason=payload.reason, snapshot=payload.snapshot,
            changes=payload.changes, created_by_agent_id=payload.created_by_agent_id,
            actor=auth_context.user_id,
        )
    except Exception as exc:
        _fail(exc)
    
    return _dump(row)


@router.get("/runs/{run_id}/plan-versions")
async def list_plan_versions(
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
        run = await service.orchestrator.get_run(organization_id, run_id)
        rows = await service.versions.list_by_run(run.id)
    except Exception as exc:
        _fail(exc)
    
    return {"data": [_dump(r) for r in rows]}


# ==================== Decisions ====================

@router.post("/decisions", status_code=status.HTTP_201_CREATED)
async def record_decision(
    organization_id: UUID,
    payload: DecisionCreate,
    request: Request,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:create")(request, db)
    
    try:
        row = await _service(db).record_decision(
            organization_id, manager_agent_id=payload.manager_agent_id,
            run_id=payload.run_id, task_id=payload.task_id,
            decision_type=payload.decision_type, selected_action=payload.selected_action,
            alternatives=payload.alternatives, policy_basis=payload.policy_basis,
            rationale=payload.rationale, actor=auth_context.user_id,
        )
    except Exception as exc:
        _fail(exc)
    
    return _dump(row)


@router.get("/runs/{run_id}/decisions")
async def list_decisions(
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
        run = await service.orchestrator.get_run(organization_id, run_id)
        rows = await service.decisions.list_by_run(run.id)
    except Exception as exc:
        _fail(exc)
    
    return {"data": [_dump(r) for r in rows]}


# ==================== Departments ====================

@router.post("/departments", status_code=status.HTTP_201_CREATED)
async def create_department(
    organization_id: UUID,
    payload: DepartmentCreate,
    request: Request,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:create")(request, db)
    
    try:
        row = await _service(db).create_department(
            organization_id, payload.name, description=payload.description,
            actor=auth_context.user_id,
        )
    except Exception as exc:
        _fail(exc)
    
    return _dump(row)


@router.get("/departments")
async def list_departments(
    organization_id: UUID,
    request: Request,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:read")(request, db)
    
    rows = await _service(db).departments.list(organization_id, limit=100)
    return {"data": [_dump(r) for r in rows]}


# ==================== Console ====================

@router.get("/console")
async def manager_console(
    organization_id: UUID,
    request: Request,
    run_id: Optional[UUID] = Query(None),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:read")(request, db)
    
    service = _service(db)
    try:
        if run_id:
            run = await service.orchestrator.get_run(organization_id, run_id)
            tasks = await service.orchestrator.tasks.list_by_run(run.id, limit=10000)
            failed = sum(1 for t in tasks if t.status.value in ("failed", "timed_out"))
            blocked = sum(1 for t in tasks if (t.task_metadata or {}).get("blocked"))
            active = sum(1 for t in tasks if t.status.value in ("running", "assigned", "ready"))
            delegations = await service.delegations.list_by_run(run.id, limit=1000)
            pending_delegations = sum(1 for d in delegations if d.status.value == "pending")
            open_escalations = await service.escalations.list_open(organization_id)
            open_escalations = [e for e in open_escalations if not e.orchestration_run_id or e.orchestration_run_id == run.id]
        else:
            failed = blocked = active = pending_delegations = open_escalations = 0
        
        return {
            "active_teams": sum(1 for t in await _service(db).teams.list(organization_id, limit=200) if t.status.value == "active"),
            "teams": [{"id": str(t.id), "name": t.name, "status": t.status.value} for t in (await _service(db).teams.list(organization_id, limit=200))[:50]],
            "active_tasks": active,
            "blocked_tasks": blocked,
            "failed_tasks": failed,
            "pending_delegations": pending_delegations,
            "delegations": [{"id": str(d.id), "status": d.status.value} for d in delegations[:50]],
            "open_escalations": len(open_escalations),
            "escalations": [{"id": str(e.id), "severity": e.severity, "status": e.status.value} for e in open_escalations[:50]],
        }
    except Exception:
        return {"active_teams": 0, "teams": [], "active_tasks": 0, "blocked_tasks": 0, "failed_tasks": 0, "pending_delegations": 0, "delegations": [], "open_escalations": 0, "escalations": []}


# ==================== Organization Chart ====================

@router.get("/organization/chart")
async def organization_chart(
    organization_id: UUID,
    request: Request,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    _check_org(organization_id, auth_context)
    await require_permission("agent:read")(request, db)
    
    from openagent.db.models import Agent
    from openagent.db.models.management import DynamicTeamMembership, ManagerProfile
    from openagent.db.models.orchestration import AgentRelationship
    
    agents = list((await db.execute(select(Agent).where(Agent.organization_id == organization_id).limit(500))).scalars().all())
    profiles = list((await db.execute(select(ManagerProfile).where(ManagerProfile.organization_id == organization_id).limit(200))).scalars().all())
    relationships = list((await db.execute(select(AgentRelationship).where(AgentRelationship.organization_id == organization_id).limit(500))).scalars().all())
    memberships = list((await db.execute(select(DynamicTeamMembership).where(
        DynamicTeamMembership.organization_id == organization_id,
        DynamicTeamMembership.status == "active")).limit(1000)).scalars().all())
    departments = await _service(db).departments.list(organization_id, limit=100)
    
    return {
        "agents": [{"id": str(a.id), "name": a.name, "status": a.status.value} for a in agents],
        "managers": [{"agent_id": str(p.agent_id), "label": p.label, "scope": p.scope} for p in profiles],
        "relationships": [{"source": str(r.source_agent_id), "target": str(r.target_agent_id), "type": r.relationship_type.value} for r in relationships],
        "team_memberships": [{"team_id": str(m.team_id), "agent_id": str(m.agent_id), "role": m.role} for m in memberships],
        "departments": [{"id": str(d.id), "name": d.name, "slug": d.slug} for d in departments],
    }


# ==================== SSE Stream ====================

@router.get("/runs/{run_id}/stream")
async def run_event_stream(
    organization_id: UUID,
    run_id: UUID,
    request: Request,
    since: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    from openagent.api.dependencies import get_auth_context
    from openagent.db.models.orchestration import OrchestrationEvent
    from openagent.services.authorization import AuthorizationService
    
    user, _, _ = await get_auth_context(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail={"error": "Authentication required", "code": "UNAUTHORIZED"})
    
    authz = AuthorizationService(db)
    ctx = await authz.get_user_context(user.id, organization_id)
    if ctx is None:
        raise HTTPException(status_code=403, detail={"error": "Not a member", "code": "FORBIDDEN"})
    
    try:
        authz.require_permission(ctx, "agent:read")
    except Exception:
        raise HTTPException(status_code=403, detail={"error": "Access denied", "code": "FORBIDDEN"})
    
    service = _service(db)
    try:
        run = await service.orchestrator.get_run(organization_id, run_id)
    except Exception as exc:
        _fail(exc)

    async def generator():
        last_id = None
        for _ in range(150):
            if await request.is_disconnected():
                break
            
            query = select(OrchestrationEvent).where(
                OrchestrationEvent.orchestration_run_id == run.id
            )
            # We don't have a simple way to filter by last_id with our current model
            # So we'll just return recent events
            query = select(OrchestrationEvent).where(
                OrchestrationEvent.orchestration_run_id == run.id
            ).order_by(OrchestrationEvent.created_at.asc()).limit(100)
            
            rows = list((await db.execute(query)).scalars().all())
            for row in rows:
                import json
                payload = json.dumps({
                    "id": row.created_at.isoformat(), "event": row.event_type,
                    "task_id": str(row.task_id) if row.task_id else None,
                    "agent_id": str(row.agent_id) if row.agent_id else None,
                    "payload": row.payload,
                })
                yield f"id: {row.created_at.isoformat()}\nevent: {row.event_type}\ndata: {payload}\n\n"
            
            if not rows:
                yield ": heartbeat\n\n"
            
            await asyncio.sleep(2)

    return StreamingResponse(generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})