"""Agent and Agent Run API endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Optional, List, Dict, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request, HTTPException, status, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.db.session import get_db
from openagent.db.models import (
    Agent,
    AgentVersion,
    AgentRun,
    AgentRunStatus,
)
from openagent.db.repositories import AgentRepository, AgentVersionRepository
from openagent.schemas.base import ApiErrorResponse, PaginatedResponse
from openagent.api.dependencies import (
    get_current_org_context,
    require_permission,
)
from openagent.services.workflow_definition import validate_definition

router = APIRouter(prefix="/organizations/{organization_id}/agents", tags=["agents"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: Optional[str] = Field(default=None, min_length=1, max_length=100, pattern="^[a-z0-9-]+$")
    description: Optional[str] = None
    agent_type: str = Field(default="workflow", pattern="^(chat|workflow|autonomous|assistant)$")
    configuration: Optional[Dict[str, Any]] = None


class AgentUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    status: Optional[str] = Field(default=None, pattern="^(draft|active|archived|deprecated)$")
    configuration: Optional[Dict[str, Any]] = None


class AgentResponse(BaseModel):
    id: UUID
    organization_id: UUID
    name: str
    slug: str
    description: Optional[str] = None
    status: str
    agent_type: str
    metadata: Dict[str, Any] = {}
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AgentDetailResponse(AgentResponse):
    versions_count: int = 0
    latest_version: Optional[str] = None


class AgentListResponse(PaginatedResponse[AgentResponse]):
    pass


class AgentVersionResponse(BaseModel):
    id: UUID
    agent_id: UUID
    version: str
    name: str
    instructions: Optional[str] = None
    configuration: Dict[str, Any] = {}
    status: str
    created_by: Optional[UUID] = None
    created_at: datetime

    class Config:
        from_attributes = True


class VersionListResponse(PaginatedResponse[AgentVersionResponse]):
    pass


class AgentRunResponse(BaseModel):
    id: UUID
    organization_id: UUID
    agent_id: UUID
    agent_version_id: Optional[UUID] = None
    workflow_execution_id: Optional[UUID] = None
    status: str
    input: Dict[str, Any] = {}
    output: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    error_code: Optional[str] = None
    step_count: int = 0
    total_tokens: int = 0
    duration_seconds: float = 0.0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class AgentRunDetailResponse(AgentRunResponse):
    steps: List[Dict[str, Any]] = []
    events: List[Dict[str, Any]] = []


class AgentRunListResponse(PaginatedResponse[AgentRunResponse]):
    pass


class AgentRunCreate(BaseModel):
    agent_id: UUID
    version: Optional[str] = None
    input: Optional[Dict[str, Any]] = None
    idempotency_key: Optional[str] = Field(default=None, max_length=100)


class ExecuteResponse(BaseModel):
    run_id: str
    status: str
    message: str = "Agent execution started"


class CancelResponse(BaseModel):
    status: str
    message: str


class RestoreRequest(BaseModel):
    version: str = Field(min_length=1, max_length=50)


class ImportRequest(BaseModel):
    payload: Dict[str, Any]
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    slug: Optional[str] = Field(default=None, min_length=1, max_length=100, pattern="^[a-z0-9-]+$")
    description: Optional[str] = None


class ExportResponse(BaseModel):
    format: str
    schema_version: str
    exported_at: str
    workflow: Dict[str, Any]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_agent_or_404(db: AsyncSession, organization_id: UUID, agent_id: UUID) -> Agent:
    result = await db.execute(
        select(Agent).where(
            Agent.id == agent_id,
            Agent.organization_id == organization_id,
            Agent.deleted_at.is_(None),
        )
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Agent not found", "code": "AGENT_NOT_FOUND"},
        )
    return agent


async def _get_agent_version_or_404(
    db: AsyncSession,
    organization_id: UUID,
    agent_id: UUID,
    version_id: UUID,
) -> AgentVersion:
    result = await db.execute(
        select(AgentVersion).where(
            AgentVersion.id == version_id,
            AgentVersion.agent_id == agent_id,
        )
    )
    version = result.scalar_one_or_none()
    if not version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Version not found", "code": "VERSION_NOT_FOUND"},
        )
    return version


async def _get_agent_run_or_404(db: AsyncSession, organization_id: UUID, run_id: UUID) -> AgentRun:
    result = await db.execute(
        select(AgentRun).where(
            AgentRun.id == run_id,
            AgentRun.organization_id == organization_id,
        )
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Agent run not found", "code": "RUN_NOT_FOUND"},
        )
    return run


def _to_agent_response(agent: Agent, versions_count: int = 0, latest_version: str = None) -> AgentResponse:
    return AgentResponse(
        id=agent.id,
        organization_id=agent.organization_id,
        name=agent.name,
        slug=agent.slug,
        description=agent.description,
        status=agent.status.value if hasattr(agent.status, "value") else str(agent.status),
        agent_type=agent.agent_type.value if hasattr(agent.agent_type, "value") else str(agent.agent_type),
        metadata=agent.metadata or {},
        created_at=agent.created_at,
        updated_at=agent.updated_at,
    )


# ---------------------------------------------------------------------------
# List / create agents
# ---------------------------------------------------------------------------

@router.get(
    "",
    response_model=AgentListResponse,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}},
)
async def list_agents(
    request: Request,
    organization_id: UUID,
    search: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status", pattern="^(draft|active|archived|deprecated)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """List agents in the organization."""
    await require_permission("agent:read")(request, db)

    query = select(Agent).where(
        Agent.organization_id == organization_id,
        Agent.deleted_at.is_(None),
    )
    count_query = select(func.count(Agent.id)).where(
        Agent.organization_id == organization_id,
        Agent.deleted_at.is_(None),
    )
    
    if status_filter:
        from openagent.db.models.agent import AgentStatus
        query = query.where(Agent.status == AgentStatus(status_filter))
        count_query = count_query.where(Agent.status == AgentStatus(status_filter))
    
    if search:
        like = f"%{search}%"
        query = query.where(or_(Agent.name.ilike(like), Agent.slug.ilike(like)))
        count_query = count_query.where(or_(Agent.name.ilike(like), Agent.slug.ilike(like)))

    total = (await db.execute(count_query)).scalar_one()
    query = query.order_by(Agent.updated_at.desc()).limit(page_size).offset((page - 1) * page_size)
    agents = list((await db.execute(query)).scalars().all())

    # Get version counts
    agent_ids = [a.id for a in agents]
    version_counts = {}
    latest_versions = {}
    if agent_ids:
        version_results = await db.execute(
            select(AgentVersion.agent_id, func.count(AgentVersion.id), func.max(AgentVersion.version))
            .where(AgentVersion.agent_id.in_(agent_ids))
            .group_by(AgentVersion.agent_id)
        )
        for agent_id, count, latest in version_results.all():
            version_counts[agent_id] = count
            latest_versions[agent_id] = latest

    items = []
    for agent in agents:
        base = _to_agent_response(agent)
        # Add version info
        base_dict = base.model_dump()
        base_dict["versions_count"] = version_counts.get(agent.id, 0)
        base_dict["latest_version"] = latest_versions.get(agent.id)
        items.append(AgentDetailResponse(**base_dict))

    from openagent.db.pagination import create_pagination_meta
    return AgentListResponse(data=items, meta=create_pagination_meta(page, page_size, total))


@router.post(
    "",
    response_model=AgentDetailResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"model": ApiErrorResponse},
        401: {"model": ApiErrorResponse},
        403: {"model": ApiErrorResponse},
        409: {"model": ApiErrorResponse},
    },
)
async def create_agent(
    request: Request,
    organization_id: UUID,
    data: AgentCreate,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Create a new agent."""
    await require_permission("agent:create")(request, db)

    slug = data.slug or slugify(data.name)
    existing = await db.execute(
        select(Agent).where(
            Agent.organization_id == organization_id,
            Agent.slug == slug,
            Agent.deleted_at.is_(None),
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": f"An agent with slug '{slug}' already exists", "code": "AGENT_SLUG_EXISTS"},
        )

    repo = AgentRepository(db)
    agent = await repo.create(
        organization_id=organization_id,
        name=data.name,
        slug=slug,
        description=data.description,
        status="draft",
        agent_type=data.agent_type,
        metadata=data.configuration or {},
    )
    await db.commit()
    await db.refresh(agent)
    
    # Create initial version if definition provided
    if data.configuration:
        from openagent.services.workflow_definition import empty_definition
        version = await AgentVersionRepository(db).create(
            agent_id=agent.id,
            version="v1",
            name=data.name,
            configuration=data.configuration,
            status="draft",
            created_by=auth_context.user_id,
        )
        await db.commit()

    return AgentDetailResponse(
        **_to_agent_response(agent).model_dump(),
        versions_count=1,
        latest_version="v1",
    )


# ---------------------------------------------------------------------------
# Detail / update / delete
# ---------------------------------------------------------------------------

@router.get(
    "/{agent_id}",
    response_model=AgentDetailResponse,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def get_agent(
    request: Request,
    organization_id: UUID,
    agent_id: UUID,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Get agent with version info."""
    await require_permission("agent:read")(request, db)
    agent = await _get_agent_or_404(db, organization_id, agent_id)
    
    # Get version info
    version_count = (await db.execute(
        select(func.count(AgentVersion.id)).where(AgentVersion.agent_id == agent_id)
    )).scalar_one()
    
    latest = await db.execute(
        select(AgentVersion.version)
        .where(AgentVersion.agent_id == agent_id)
        .order_by(AgentVersion.created_at.desc())
        .limit(1)
    )
    latest_version = latest.scalar_one_or_none()
    
    return AgentDetailResponse(
        **_to_agent_response(agent).model_dump(),
        versions_count=version_count,
        latest_version=latest_version,
    )


@router.patch(
    "/{agent_id}",
    response_model=AgentDetailResponse,
    responses={
        400: {"model": ApiErrorResponse},
        401: {"model": ApiErrorResponse},
        403: {"model": ApiErrorResponse},
        404: {"model": ApiErrorResponse},
        409: {"model": ApiErrorResponse},
    },
)
async def update_agent(
    request: Request,
    organization_id: UUID,
    agent_id: UUID,
    data: AgentUpdate,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Update an agent."""
    await require_permission("agent:update")(request, db)
    agent = await _get_agent_or_404(db, organization_id, agent_id)

    if data.name is not None:
        agent.name = data.name
    if data.description is not None:
        agent.description = data.description
    if data.status is not None:
        agent.status = data.status
    if data.configuration is not None:
        agent.metadata = {**(agent.metadata or {}), "configuration": data.configuration}

    await db.commit()
    await db.refresh(agent)
    
    return AgentDetailResponse(**_to_agent_response(agent).model_dump())


@router.delete(
    "/{agent_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def delete_agent(
    request: Request,
    organization_id: UUID,
    agent_id: UUID,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete an agent."""
    await require_permission("agent:delete")(request, db)
    agent = await _get_agent_or_404(db, organization_id, agent_id)
    
    from datetime import datetime, timezone
    agent.deleted_at = datetime.now(timezone.utc)
    await db.commit()


# ---------------------------------------------------------------------------
# Version management
# ---------------------------------------------------------------------------

@router.get(
    "/{agent_id}/versions",
    response_model=VersionListResponse,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def list_versions(
    request: Request,
    organization_id: UUID,
    agent_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """List versions for an agent."""
    await require_permission("agent:read")(request, db)
    await _get_agent_or_404(db, organization_id, agent_id)

    total = (await db.execute(
        select(func.count(AgentVersion.id)).where(AgentVersion.agent_id == agent_id)
    )).scalar_one()
    
    result = await db.execute(
        select(AgentVersion)
        .where(AgentVersion.agent_id == agent_id)
        .order_by(AgentVersion.created_at.desc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    versions = list(result.scalars().all())
    
    items = [AgentVersionResponse.model_validate(v) for v in versions]
    
    from openagent.db.pagination import create_pagination_meta
    return VersionListResponse(data=items, meta=create_pagination_meta(page, page_size, total))


@router.post(
    "/{agent_id}/versions",
    response_model=AgentVersionResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"model": ApiErrorResponse},
        401: {"model": ApiErrorResponse},
        403: {"model": ApiErrorResponse},
        404: {"model": ApiErrorResponse},
        409: {"model": ApiErrorResponse},
    },
)
async def create_version(
    request: Request,
    organization_id: UUID,
    agent_id: UUID,
    data: Dict[str, Any],  # version, name, instructions, configuration
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Create a new version of an agent."""
    await require_permission("agent:update")(request, db)
    agent = await _get_agent_or_404(db, organization_id, agent_id)
    
    version = data.get("version")
    if not version:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "Version is required", "code": "VERSION_REQUIRED"},
        )
    
    # Check if version already exists
    existing = await db.execute(
        select(AgentVersion).where(
            AgentVersion.agent_id == agent_id,
            AgentVersion.version == version,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": f"Version {version} already exists", "code": "VERSION_EXISTS"},
        )
    
    repo = AgentVersionRepository(db)
    version_obj = await repo.create(
        agent_id=agent_id,
        version=version,
        name=data.get("name") or f"Version {version}",
        instructions=data.get("instructions"),
        definition=data.get("configuration"),
        status="draft",
        created_by=auth_context.user_id,
    )
    
    await db.commit()
    await db.refresh(version_obj)
    return AgentVersionResponse.model_validate(version_obj)


@router.post(
    "/{agent_id}/versions/{version}/publish",
    response_model=AgentVersionResponse,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}, 422: {"model": ApiErrorResponse}},
)
async def publish_version(
    request: Request,
    organization_id: UUID,
    agent_id: UUID,
    version: str,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Publish a version (validate and activate)."""
    await require_permission("agent:update")(request, db)
    agent = await _get_agent_or_404(db, organization_id, agent_id)
    
    repo = AgentVersionRepository(db)
    row = await repo.get_by_version(agent_id, version)
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Version not found", "code": "VERSION_NOT_FOUND"},
        )
    
    # Validate definition
    if row.definition:
        result = validate_definition(row.definition)
        if not result.valid:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "error": "Definition is invalid",
                    "code": "INVALID_DEFINITION",
                    "details": [e.model_dump() for e in result.errors],
                },
            )
    
    row.status = "published"
    await db.commit()
    await db.refresh(row)
    return AgentVersionResponse.model_validate(row)


@router.post(
    "/{agent_id}/versions/{version}/unpublish",
    response_model=AgentVersionResponse,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def unpublish_version(
    request: Request,
    organization_id: UUID,
    agent_id: UUID,
    version: str,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Unpublish a version (return to draft)."""
    await require_permission("agent:update")(request, db)
    agent = await _get_agent_or_404(db, organization_id, agent_id)
    
    repo = AgentVersionRepository(db)
    row = await repo.get_by_version(agent_id, version)
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Version not found", "code": "VERSION_NOT_FOUND"},
        )
    
    if row.status == "published":
        row.status = "draft"
        await db.commit()
        await db.refresh(row)
    
    return AgentVersionResponse.model_validate(row)


@router.post(
    "/{agent_id}/versions/{version}/restore",
    response_model=AgentVersionResponse,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def restore_version(
    request: Request,
    organization_id: UUID,
    agent_id: UUID,
    version: str,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Restore a version as a new draft."""
    await require_permission("agent:update")(request, db)
    agent = await _get_agent_or_404(db, organization_id, agent_id)
    
    repo = AgentVersionRepository(db)
    snapshot = await repo.get_by_version(agent_id, version)
    if not snapshot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Version not found", "code": "VERSION_NOT_FOUND"},
        )
    
    # Count existing versions
    count = (await db.execute(
        select(func.count(AgentVersion.id)).where(AgentVersion.agent_id == agent_id)
    )).scalar_one()
    
    new_version = f"v{count + 1}"
    new_version_obj = await repo.create(
        agent_id=agent_id,
        version=new_version,
        name=snapshot.name,
        instructions=snapshot.instructions,
        definition=dict(snapshot.configuration) if snapshot.configuration else {},
        status="draft",
        created_by=auth_context.user_id,
    )
    
    await db.commit()
    await db.refresh(new_version_obj)
    return AgentVersionResponse.model_validate(new_version_obj)


# ---------------------------------------------------------------------------
# Agent Runs
# ---------------------------------------------------------------------------

@router.post(
    "/{agent_id}/runs",
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
async def run_agent(
    request: Request,
    organization_id: UUID,
    agent_id: UUID,
    data: AgentRunCreate,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Execute an agent (async)."""
    await require_permission("agent:execute")(request, db)
    
    # Verify workflow execution exists if provided
    if data.workflow_execution_id:
        from openagent.db.models import WorkflowExecution
        result = await db.execute(
            select(WorkflowExecution).where(
                WorkflowExecution.id == data.workflow_execution_id,
                WorkflowExecution.organization_id == organization_id,
            )
        )
        if not result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "Workflow execution not found", "code": "WORKFLOW_EXECUTION_NOT_FOUND"},
            )
    
    # Create run
    repo = AgentRunRepository(db)
    run = await repo.create(
        agent_id=agent_id,
        agent_version_id=data.version_id,
        workflow_execution_id=data.workflow_execution_id,
        input_data=data.input,
    )
    await db.commit()
    
    # Enqueue execution job
    from openagent.worker.queue import JobQueue, Job, RetryPolicy
    from openagent.worker.config import WorkerSettings
    import redis.asyncio as redis
    
    settings = WorkerSettings()
    redis_client = redis.from_url(settings.REDIS_URL, encoding="utf-8", decode_responses=True)
    queue = JobQueue(redis_client, "agent_run", RetryPolicy())
    
    await queue.enqueue(Job(
        type="agent_run",
        payload={
            "run_id": str(run.id),
            "organization_id": str(organization_id),
        },
    ))
    
    return ExecuteResponse(
        run_id=str(run.id),
        status="queued",
        message="Agent execution queued",
    )


@router.get(
    "/{agent_id}/runs",
    response_model=AgentRunListResponse,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def list_runs(
    request: Request,
    organization_id: UUID,
    agent_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """List agent runs."""
    await require_permission("agent:read")(request, db)
    await _get_agent_or_404(db, organization_id, agent_id)
    
    query = select(AgentRun).where(
        AgentRun.agent_id == agent_id,
        AgentRun.organization_id == organization_id,
    )
    count_query = select(func.count(AgentRun.id)).where(
        AgentRun.agent_id == agent_id,
        AgentRun.organization_id == organization_id,
    )
    
    if status_filter:
        try:
            status_enum = AgentRunStatus(status_filter)
            query = query.where(AgentRun.status == status_enum)
            count_query = count_query.where(AgentRun.status == status_enum)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": f"Invalid status: {status_filter}", "code": "INVALID_STATUS"},
            )
    
    total = (await db.execute(count_query)).scalar_one()
    query = query.order_by(AgentRun.created_at.desc()).limit(page_size).offset((page - 1) * page_size)
    runs = list((await db.execute(query)).scalars().all())
    
    items = [AgentRunResponse.model_validate(r) for r in runs]
    
    from openagent.db.pagination import create_pagination_meta
    return AgentRunListResponse(data=items, meta=create_pagination_meta(page, page_size, total))


@router.get(
    "/{agent_id}/runs/{run_id}",
    response_model=AgentRunDetailResponse,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def get_run(
    request: Request,
    organization_id: UUID,
    agent_id: UUID,
    run_id: UUID,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Get agent run detail with steps and events."""
    await require_permission("execution:read")(request, db)
    run = await _get_agent_run_or_404(db, organization_id, run_id)
    
    if run.agent_id != agent_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Run not found for this agent", "code": "RUN_NOT_FOUND"},
        )
    
    # Get steps from metadata
    steps = []
    if run.metadata and "steps" in run.metadata:
        for step in run.metadata["steps"]:
            steps.append({
                "step_number": step.get("step_number"),
                "status": step.get("status"),
                "model_request": step.get("model_request"),
                "model_response": step.get("model_response"),
                "tool_calls": step.get("tool_calls", []),
                "tool_results": step.get("tool_results", []),
                "error": step.get("error"),
                "started_at": step.get("started_at"),
                "completed_at": step.get("completed_at"),
            })
    
    # Get events
    from openagent.db.models import ExecutionEvent
    events_result = await db.execute(
        select(ExecutionEvent)
        .where(ExecutionEvent.run_id == run_id)
        .order_by(ExecutionEvent.sequence)
    )
    events = [
        {
            "event_type": e.event_type,
            "node_id": str(e.node_id) if e.node_id else None,
            "sequence": e.sequence,
            "timestamp": e.timestamp,
            "payload": e.payload,
        }
        for e in events_result.scalars().all()
    ]
    
    return AgentRunDetailResponse(
        **AgentRunResponse.model_validate(run).model_dump(),
        steps=steps,
        events=events,
    )


@router.post(
    "/{agent_id}/runs/{run_id}/cancel",
    response_model=CancelResponse,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def cancel_run(
    request: Request,
    organization_id: UUID,
    agent_id: UUID,
    run_id: UUID,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Cancel a running agent run."""
    await require_permission("agent:cancel")(request, db)
    run = await _get_agent_run_or_404(db, organization_id, run_id)
    
    if run.agent_id != agent_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Run not found for this agent", "code": "RUN_NOT_FOUND"},
        )
    
    if run.status in [AgentRunStatus.COMPLETED, AgentRunStatus.FAILED, AgentRunStatus.CANCELLED, AgentRunStatus.TIMED_OUT]:
        return CancelResponse(status="already_terminal", message=f"Run is already in terminal state: {run.status.value}")
    
    run.status = AgentRunStatus.CANCELLED
    run.completed_at = datetime.now(timezone.utc)
    await db.commit()
    
    return CancelResponse(status="cancelled", message="Run cancelled")


class RunEvaluateRequest(BaseModel):
    evaluation_type: str = Field(default="GOAL_COMPLETION", max_length=64)
    criteria: Any = None
    goal: str = Field(default="", max_length=4000)
    quality_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    checks: list[Dict[str, Any]] = Field(default_factory=list)


@router.post(
    "/{agent_id}/runs/{run_id}/evaluate",
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def evaluate_run(
    request: Request,
    organization_id: UUID,
    agent_id: UUID,
    run_id: UUID,
    data: RunEvaluateRequest = RunEvaluateRequest(),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Completion verification for a finished agent run.

    The agent's own success claim is never proof: the run output is treated
    as MODEL_GENERATED evidence and verified against criteria/checks.
    """
    await require_permission("evaluation:create")(request, db)
    run = await _get_agent_run_or_404(db, organization_id, run_id)

    if run.agent_id != agent_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Run not found for this agent", "code": "RUN_NOT_FOUND"},
        )

    if run.status not in [AgentRunStatus.COMPLETED, AgentRunStatus.FAILED,
                           AgentRunStatus.TIMED_OUT]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": f"Run is {run.status.value}; only finished runs can be evaluated",
                    "code": "RUN_NOT_FINISHED"},
        )

    from openagent.evaluator.integrations import evaluate_agent_run
    from openagent.evaluator.metrics import inc as metrics_inc
    from openagent.evaluator.types import is_known_evaluation_type
    if not is_known_evaluation_type(data.evaluation_type):
        raise HTTPException(status_code=400,
                            detail="Unknown evaluation type")
    steps = (run.metadata or {}).get("steps", []) if run.metadata else []
    tool_results = []
    for step in steps if isinstance(steps, list) else []:
        for tr in (step.get("tool_results", []) if isinstance(step, dict) else []):
            if isinstance(tr, dict):
                tool_results.append(tr)
    outcome = await evaluate_agent_run(
        db, organization_id=organization_id, agent_id=agent_id,
        agent_run_id=run_id, output=run.output, tool_results=tool_results,
        criteria=data.criteria, goal=data.goal,
        evaluation_type=data.evaluation_type.upper(),
        quality_threshold=data.quality_threshold, checks=data.checks)
    await db.commit()
    metrics_inc("evaluations_total")
    return outcome


@router.post(
    "/{agent_id}/runs/{run_id}/retry",
    response_model=ExecuteResponse,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def retry_run(
    request: Request,
    organization_id: UUID,
    agent_id: UUID,
    run_id: UUID,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Retry a failed execution."""
    await require_permission("agent:execute")(request, db)
    run = await _get_agent_run_or_404(db, organization_id, run_id)
    
    if run.agent_id != agent_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Run not found for this agent", "code": "RUN_NOT_FOUND"},
        )
    
    if run.status not in [AgentRunStatus.FAILED, AgentRunStatus.CANCELLED, AgentRunStatus.TIMED_OUT]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "Only failed, cancelled, or timed out runs can be retried", "code": "NOT_RETRYABLE"},
        )
    
    # Create new run with same input
    from openagent.db.repositories import AgentRunRepository
    repo = AgentRunRepository(db)
    new_run = await repo.create(
        agent_id=run.agent_id,
        agent_version_id=run.agent_version_id,
        workflow_execution_id=run.workflow_execution_id,
        input_data=run.input,
    )
    await db.commit()
    
    return ExecuteResponse(
        run_id=str(new_run.id),
        status="queued",
        message="Run re-queued for retry",
    )


# ---------------------------------------------------------------------------
# Import / Export
# ---------------------------------------------------------------------------

@router.post(
    "/import",
    response_model=AgentDetailResponse,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ApiErrorResponse}, 401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 409: {"model": ApiErrorResponse}},
)
async def import_agent(
    request: Request,
    organization_id: UUID,
    data: ImportRequest,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Import a workflow from an export envelope or raw definition."""
    await require_permission("workflow:import")(request, db)
    
    from openagent.services.workflow_definition import parse_envelope
    
    parsed, parse_error = parse_envelope(data.payload)
    if parse_error or not parsed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": parse_error or "Invalid import payload", "code": "INVALID_IMPORT"},
        )
    
    meta = parsed["meta"] or {}
    definition = parsed["definition"]
    
    name = data.name or meta.get("name") or "Imported Agent"
    if not name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "Import requires a workflow name", "code": "INVALID_IMPORT"},
        )
    
    slug = data.slug or (meta.get("slug") if isinstance(meta.get("slug"), str) else None) or slugify(name)
    
    # Check slug conflict
    existing = await db.execute(
        select(Agent).where(
            Agent.organization_id == organization_id,
            Agent.slug == slug,
            Agent.deleted_at.is_(None),
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": f"A agent with slug '{slug}' already exists", "code": "AGENT_SLUG_EXISTS"},
        )
    
    repo = AgentRepository(db)
    workflow = await repo.create(
        organization_id=organization_id,
        name=name.strip()[:255],
        slug=slug,
        description=meta.get("description"),
        status="draft",
        metadata={"tags": [t[:50] for t in (meta.get("tags") or []) if isinstance(t, str)][:20], "imported": True},
    )
    await db.commit()
    await db.refresh(workflow)
    
    # Create version
    from openagent.services.workflow_definition import empty_definition
    from openagent.db.repositories import AgentVersionRepository
    version_repo = AgentVersionRepository(db)
    await version_repo.create(
        workflow_id=workflow.id,
        version="v1",
        name="Initial version",
        definition=definition,
        status="draft",
        created_by=auth_context.user_id,
    )
    await db.commit()
    await db.refresh(workflow)
    
    return AgentDetailResponse(**_to_agent_response(workflow).model_dump(), versions_count=1, latest_version="v1")


@router.get(
    "/{agent_id}/export",
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def export_agent(
    request: Request,
    organization_id: UUID,
    agent_id: UUID,
    version: Optional[str] = Query(None),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Export a workflow as a portable envelope."""
    from openagent.services.workflow_definition import build_envelope
    
    await require_permission("workflow:read")(request, db)
    workflow = await _get_workflow_or_404(db, organization_id, workflow_id)
    
    if version:
        repo = AgentVersionRepository(db)
        snapshot = await repo.get_by_version(workflow.id, version)
        if not snapshot:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "Version not found", "code": "VERSION_NOT_FOUND"},
            )
        definition = snapshot.definition
    else:
        latest = await db.execute(
            select(AgentVersion)
            .where(AgentVersion.agent_id == agent_id)
            .order_by(AgentVersion.created_at.desc())
            .limit(1)
        )
        latest_version = latest.scalars().first()
        definition = latest_version.definition if latest_version else empty_definition()
    
    return build_envelope(
        workflow.name,
        workflow.slug,
        workflow.description,
        workflow.tags if hasattr(workflow, 'tags') else [],
        definition,
    )


# Helper functions
def slugify(name: str) -> str:
    import re
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    return slug[:100] or "workflow"


def _to_agent_response(agent: Agent) -> AgentResponse:
    return AgentResponse(
        id=agent.id,
        organization_id=agent.organization_id,
        name=agent.name,
        slug=agent.slug,
        description=agent.description,
        status=agent.status.value if hasattr(agent.status, "value") else str(agent.status),
        agent_type=agent.agent_type.value if hasattr(agent.agent_type, "value") else str(agent.agent_type),
        metadata=agent.metadata or {},
        created_at=agent.created_at,
        updated_at=agent.updated_at,
    )


async def _get_agent_or_404(db: AsyncSession, organization_id: UUID, agent_id: UUID) -> Agent:
    result = await db.execute(
        select(Agent).where(
            Agent.id == agent_id,
            Agent.organization_id == organization_id,
            Agent.deleted_at.is_(None),
        )
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Agent not found", "code": "AGENT_NOT_FOUND"},
        )
    return agent


# Need to add imports
from fastapi import APIRouter, Depends, Request, HTTPException, status, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from datetime import datetime, timezone
import re

from openagent.db.session import get_db
from openagent.db.models import Agent, AgentVersion, AgentRun, AgentRunStatus
from openagent.db.repositories import AgentRepository, AgentVersionRepository
from openagent.schemas.base import ApiErrorResponse, PaginatedResponse, PaginationParams, PaginationMeta
from openagent.api.dependencies import get_current_org_context, require_permission
from openagent.services.workflow_definition import validate_definition, empty_definition, slugify
from openagent.services.workflow_definition import parse_envelope, build_envelope, migrate_definition
from openagent.api.dependencies import get_current_org_context, require_permission
from openagent.schemas.base import ApiErrorResponse, PaginatedResponse
from openagent.api.dependencies import get_current_org_context, require_permission
from openagent.db.pagination import create_pagination_meta

router = APIRouter(prefix="/organizations/{organization_id}/agents", tags=["agents"])

# Need to add AgentRunRepository
from openagent.db.repositories import AgentRunRepository