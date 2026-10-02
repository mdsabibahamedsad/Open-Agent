"""Tool API endpoints."""

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
    Tool,
    ToolVersion,
    ToolProvider,
    ToolPolicy,
    ToolExecution,
    ToolExecutionEvent,
    ToolLifecycleStatus,
    ToolCategory,
    ToolCapability,
    ToolRiskLevel,
    ToolExecutionMode,
    ToolTrustLevel,
    ToolProviderType,
)
from openagent.db.repositories import (
    ToolRepository,
    ToolVersionRepository,
    ToolProviderRepository,
    ToolPolicyRepository,
    ToolExecutionRepository,
    ToolExecutionEventRepository,
)
from openagent.schemas.base import ApiErrorResponse, PaginatedResponse
from openagent.api.dependencies import (
    get_current_org_context,
    require_permission,
)
from openagent.core.config import get_settings

router = APIRouter(prefix="/organizations/{organization_id}/tools", tags=["tools"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ToolCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: Optional[str] = Field(default=None, min_length=1, max_length=100, pattern="^[a-z0-9-]+$")
    description: Optional[str] = None
    tool_type: str = Field(default="custom", pattern="^(builtin|custom|mcp|api|community)$")
    category: str = Field(default="utility", pattern="^(communication|web|browser|http|database|filesystem|code|shell|search|documents|media|calendar|email|messaging|crm|analytics|finance|developer|system|ai|utility|custom)$")
    display_name: Optional[str] = None
    icon: Optional[str] = None
    documentation_url: Optional[str] = None
    provider: str = Field(default="builtin", max_length=100)
    provider_type: str = Field(default="BUILTIN", pattern="^(BUILTIN|HTTP_API|PYTHON_PACKAGE|JAVASCRIPT_PACKAGE|EXTERNAL_SERVICE|MCP|MARKETPLACE|BROWSER|CODING_RUNTIME|CUSTOM)$")
    version: str = Field(default="1.0.0", pattern="^v?\d+\.\d+\.\d+$")
    capabilities: List[str] = Field(default_factory=list)
    risk_level: str = Field(default="LOW", pattern="^(LOW|MEDIUM|HIGH|CRITICAL)$")
    execution_mode: str = Field(default="SYNC", pattern="^(SYNC|ASYNC|STREAMING|BACKGROUND|WAITING)$")
    timeout: int = Field(default=30000, ge=100, le=300000)
    retry_policy: Optional[Dict[str, Any]] = None
    supports_streaming: bool = False
    supports_cancellation: bool = True
    supports_idempotency: bool = False
    trust_level: str = Field(default="ORGANIZATION", pattern="^(CORE|VERIFIED|ORGANIZATION|COMMUNITY|UNTRUSTED)$")
    input_schema: Dict[str, Any] = Field(default_factory=dict)
    output_schema: Optional[Dict[str, Any]] = None
    configuration: Optional[Dict[str, Any]] = None
    tags: List[str] = Field(default_factory=list)


class ToolUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    display_name: Optional[str] = None
    icon: Optional[str] = None
    documentation_url: Optional[str] = None
    status: Optional[str] = Field(default=None, pattern="^(DRAFT|ACTIVE|DISABLED|DEPRECATED|REVOKED)$")
    capabilities: Optional[List[str]] = None
    risk_level: Optional[str] = Field(default=None, pattern="^(LOW|MEDIUM|HIGH|CRITICAL)$")
    execution_mode: Optional[str] = Field(default=None, pattern="^(SYNC|ASYNC|STREAMING|BACKGROUND|WAITING)$")
    timeout: Optional[int] = Field(default=None, ge=100, le=300000)
    retry_policy: Optional[Dict[str, Any]] = None
    supports_streaming: Optional[bool] = None
    supports_cancellation: Optional[bool] = None
    supports_idempotency: Optional[bool] = None
    trust_level: Optional[str] = Field(default=None, pattern="^(CORE|VERIFIED|ORGANIZATION|COMMUNITY|UNTRUSTED)$")
    input_schema: Optional[Dict[str, Any]] = None
    output_schema: Optional[Dict[str, Any]] = None
    configuration: Optional[Dict[str, Any]] = None
    tags: Optional[List[str]] = None


class ToolResponse(BaseModel):
    id: UUID
    organization_id: Optional[UUID] = None
    name: str
    slug: str
    description: Optional[str] = None
    tool_type: str
    category: str
    status: str
    display_name: Optional[str] = None
    icon: Optional[str] = None
    documentation_url: Optional[str] = None
    provider: str
    provider_type: str
    version: str
    capabilities: List[str]
    risk_level: str
    execution_mode: str
    timeout: int
    retry_policy: Dict[str, Any]
    supports_streaming: bool
    supports_cancellation: bool
    supports_idempotency: bool
    trust_level: str
    input_schema: Dict[str, Any]
    output_schema: Optional[Dict[str, Any]] = None
    configuration: Dict[str, Any]
    metadata: Dict[str, Any]
    tags: List[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ToolListResponse(PaginatedResponse[ToolResponse]):
    pass


class ToolVersionResponse(BaseModel):
    id: UUID
    tool_id: UUID
    version: str
    display_name: Optional[str] = None
    description: Optional[str] = None
    capabilities: List[str]
    risk_level: str
    execution_mode: str
    timeout: int
    retry_policy: Dict[str, Any]
    supports_streaming: bool
    supports_cancellation: bool
    supports_idempotency: bool
    trust_level: str
    input_schema: Dict[str, Any]
    output_schema: Optional[Dict[str, Any]] = None
    configuration: Dict[str, Any]
    metadata: Dict[str, Any]
    status: str
    checksum: str
    published_at: Optional[datetime] = None
    deprecated_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ToolVersionListResponse(PaginatedResponse[ToolVersionResponse]):
    pass


class ToolVersionCreate(BaseModel):
    version: str = Field(min_length=1, max_length=50, pattern="^v?\d+\.\d+\.\d+$")
    display_name: Optional[str] = None
    description: Optional[str] = None
    capabilities: List[str] = Field(default_factory=list)
    risk_level: str = Field(default="LOW", pattern="^(LOW|MEDIUM|HIGH|CRITICAL)$")
    execution_mode: str = Field(default="SYNC", pattern="^(SYNC|ASYNC|STREAMING|BACKGROUND|WAITING)$")
    timeout: int = Field(default=30000, ge=100, le=300000)
    retry_policy: Optional[Dict[str, Any]] = None
    supports_streaming: bool = False
    supports_cancellation: bool = True
    supports_idempotency: bool = False
    trust_level: str = Field(default="ORGANIZATION", pattern="^(CORE|VERIFIED|ORGANIZATION|COMMUNITY|UNTRUSTED)$")
    input_schema: Dict[str, Any] = Field(default_factory=dict)
    output_schema: Optional[Dict[str, Any]] = None
    configuration: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None
    checksum: str = Field(min_length=64, max_length=64)


class ToolExecutionRequest(BaseModel):
    tool_id: UUID
    tool_version: str = "1.0.0"
    input: Dict[str, Any] = Field(default_factory=dict)
    timeout: Optional[int] = Field(default=None, ge=100, le=300000)
    idempotency_key: Optional[str] = Field(default=None, max_length=100)
    approval_id: Optional[UUID] = Field(default=None,
                                        description="Persisted approval authorizing this exact action")


class ToolExecutionResponse(BaseModel):
    execution_id: UUID
    tool_id: UUID
    tool_version: str
    status: str
    output: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None
    duration_ms: int
    retryable: bool
    truncated: bool
    artifacts: List[Dict[str, Any]] = []
    metadata: Dict[str, Any] = {}


class ToolPolicyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: Optional[str] = None
    team_id: Optional[UUID] = None
    agent_id: Optional[UUID] = None
    workflow_id: Optional[UUID] = None
    tool_id: Optional[UUID] = None
    priority: int = 0
    allowed_tools: List[str] = Field(default_factory=list)
    blocked_tools: List[str] = Field(default_factory=list)
    allowed_categories: List[str] = Field(default_factory=list)
    blocked_categories: List[str] = Field(default_factory=list)
    allowed_risk_levels: List[str] = Field(default_factory=list)
    max_risk_level: Optional[str] = Field(default=None, pattern="^(LOW|MEDIUM|HIGH|CRITICAL)$")
    allowed_capabilities: List[str] = Field(default_factory=list)
    blocked_capabilities: List[str] = Field(default_factory=list)
    allowed_domains: List[str] = Field(default_factory=list)
    blocked_domains: List[str] = Field(default_factory=list)
    allowed_organizations: List[str] = Field(default_factory=list)
    approval_required: Dict[str, bool] = Field(default_factory=dict)
    execution_limits: Dict[str, Any] = Field(default_factory=dict)


class ToolPolicyResponse(BaseModel):
    id: UUID
    organization_id: Optional[UUID] = None
    team_id: Optional[UUID] = None
    agent_id: Optional[UUID] = None
    workflow_id: Optional[UUID] = None
    tool_id: Optional[UUID] = None
    name: str
    description: Optional[str] = None
    priority: int
    allowed_tools: List[str]
    blocked_tools: List[str]
    allowed_categories: List[str]
    blocked_categories: List[str]
    allowed_risk_levels: List[str]
    max_risk_level: Optional[str] = None
    allowed_capabilities: List[str]
    blocked_capabilities: List[str]
    allowed_domains: List[str]
    blocked_domains: List[str]
    allowed_organizations: List[str]
    approval_required: Dict[str, bool]
    execution_limits: Dict[str, Any]
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ToolPolicyListResponse(PaginatedResponse[ToolPolicyResponse]):
    pass


class ToolExecutionRecordResponse(BaseModel):
    id: UUID
    tool_id: UUID
    tool_version_id: UUID
    organization_id: UUID
    agent_id: Optional[UUID] = None
    workflow_id: Optional[UUID] = None
    user_id: Optional[UUID] = None
    node_execution_id: Optional[UUID] = None
    status: str
    input: Dict[str, Any]
    output: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None
    started_at: datetime
    completed_at: Optional[datetime] = None
    duration_ms: int
    retry_count: int
    estimated_cost: Optional[float] = None
    actual_cost: Optional[float] = None
    metadata: Dict[str, Any]
    idempotency_key: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ToolExecutionListResponse(PaginatedResponse[ToolExecutionRecordResponse]):
    pass


class ToolEventResponse(BaseModel):
    id: UUID
    execution_id: UUID
    event_type: str
    payload: Dict[str, Any]
    sequence: int
    timestamp: datetime

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_tool_or_404(
    db: AsyncSession,
    organization_id: UUID,
    tool_id: UUID,
    repo: ToolRepository
) -> Tool:
    tool = await repo.get(tool_id)
    if not tool or tool.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Tool not found", "code": "TOOL_NOT_FOUND"},
        )
    if tool.organization_id and tool.organization_id != organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Tool not found", "code": "TOOL_NOT_FOUND"},
        )
    return tool


def _to_tool_response(tool: Tool) -> ToolResponse:
    return ToolResponse(
        id=tool.id,
        organization_id=tool.organization_id,
        name=tool.name,
        slug=tool.slug,
        description=tool.description,
        tool_type=tool.tool_type.value,
        category=tool.category.value,
        status=tool.status.value,
        display_name=tool.display_name,
        icon=tool.icon,
        documentation_url=tool.documentation_url,
        provider=tool.provider,
        provider_type=tool.provider_type.value,
        version=tool.version,
        capabilities=[c.value for c in tool.capabilities],
        risk_level=tool.risk_level.value,
        execution_mode=tool.execution_mode.value,
        timeout=tool.timeout,
        retry_policy=tool.retry_policy,
        supports_streaming=tool.supports_streaming,
        supports_cancellation=tool.supports_cancellation,
        supports_idempotency=tool.supports_idempotency,
        trust_level=tool.trust_level.value,
        input_schema=tool.input_schema,
        output_schema=tool.output_schema,
        configuration=tool.configuration,
        metadata=tool.metadata,
        tags=tool.tags,
        created_at=tool.created_at,
        updated_at=tool.updated_at,
    )


def _to_tool_version_response(version: ToolVersion) -> ToolVersionResponse:
    return ToolVersionResponse(
        id=version.id,
        tool_id=version.tool_id,
        version=version.version,
        display_name=version.display_name,
        description=version.description,
        capabilities=[c.value for c in version.capabilities],
        risk_level=version.risk_level.value,
        execution_mode=version.execution_mode.value,
        timeout=version.timeout,
        retry_policy=version.retry_policy,
        supports_streaming=version.supports_streaming,
        supports_cancellation=version.supports_cancellation,
        supports_idempotency=version.supports_idempotency,
        trust_level=version.trust_level.value,
        input_schema=version.input_schema,
        output_schema=version.output_schema,
        configuration=version.configuration,
        metadata=version.metadata,
        status=version.status.value,
        checksum=version.checksum,
        published_at=version.published_at,
        deprecated_at=version.deprecated_at,
        created_at=version.created_at,
        updated_at=version.updated_at,
    )


def _to_tool_policy_response(policy: ToolPolicy) -> ToolPolicyResponse:
    return ToolPolicyResponse(
        id=policy.id,
        organization_id=policy.organization_id,
        team_id=policy.team_id,
        agent_id=policy.agent_id,
        workflow_id=policy.workflow_id,
        tool_id=policy.tool_id,
        name=policy.name,
        description=policy.description,
        priority=policy.priority,
        allowed_tools=policy.allowed_tools,
        blocked_tools=policy.blocked_tools,
        allowed_categories=[c.value for c in policy.allowed_categories],
        blocked_categories=[c.value for c in policy.blocked_categories],
        allowed_risk_levels=[r.value for r in policy.allowed_risk_levels],
        max_risk_level=policy.max_risk_level.value if policy.max_risk_level else None,
        allowed_capabilities=[c.value for c in policy.allowed_capabilities],
        blocked_capabilities=[c.value for c in policy.blocked_capabilities],
        allowed_domains=policy.allowed_domains,
        blocked_domains=policy.blocked_domains,
        allowed_organizations=policy.allowed_organizations,
        approval_required=policy.approval_required,
        execution_limits=policy.execution_limits,
        is_active=policy.is_active,
        created_at=policy.created_at,
        updated_at=policy.updated_at,
    )


def _to_tool_execution_response(execution: ToolExecution) -> ToolExecutionRecordResponse:
    return ToolExecutionRecordResponse(
        id=execution.id,
        tool_id=execution.tool_id,
        tool_version_id=execution.tool_version_id,
        organization_id=execution.organization_id,
        agent_id=execution.agent_id,
        workflow_id=execution.workflow_id,
        user_id=execution.user_id,
        node_execution_id=execution.node_execution_id,
        status=execution.status,
        input=execution.input,
        output=execution.output,
        error=execution.error,
        started_at=execution.started_at,
        completed_at=execution.completed_at,
        duration_ms=execution.duration_ms,
        retry_count=execution.retry_count,
        estimated_cost=execution.estimated_cost,
        actual_cost=execution.actual_cost,
        metadata=execution.metadata,
        idempotency_key=execution.idempotency_key,
        created_at=execution.created_at,
    )


# ---------------------------------------------------------------------------
# Tool CRUD
# ---------------------------------------------------------------------------

@router.get(
    "",
    response_model=ToolListResponse,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}},
)
async def list_tools(
    request: Request,
    organization_id: UUID,
    category: Optional[str] = Query(None),
    risk_level: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    provider: Optional[str] = Query(None),
    trust_level: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    tags: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """List tools in the organization."""
    await require_permission("tool:read")(request, db)

    repo = ToolRepository(db)
    tool_category = ToolCategory(category) if category else None
    tool_risk = ToolRiskLevel(risk_level) if risk_level else None
    tool_status = ToolLifecycleStatus(status) if status else None
    tool_trust = ToolTrustLevel(trust_level) if trust_level else None
    tag_list = tags.split(",") if tags else None

    # For now, use basic filtering
    query = select(Tool).where(
        Tool.deleted_at.is_(None),
        or_(
            Tool.organization_id == organization_id,
            Tool.organization_id.is_(None),
        ),
    )
    count_query = select(func.count(Tool.id)).where(
        Tool.deleted_at.is_(None),
        or_(
            Tool.organization_id == organization_id,
            Tool.organization_id.is_(None),
        ),
    )

    if tool_category:
        query = query.where(Tool.category == tool_category)
        count_query = count_query.where(Tool.category == tool_category)
    if tool_risk:
        query = query.where(Tool.risk_level == tool_risk)
        count_query = count_query.where(Tool.risk_level == tool_risk)
    if tool_status:
        query = query.where(Tool.status == tool_status)
        count_query = count_query.where(Tool.status == tool_status)
    if provider:
        query = query.where(Tool.provider == provider)
        count_query = count_query.where(Tool.provider == provider)
    if tool_trust:
        query = query.where(Tool.trust_level == tool_trust)
        count_query = count_query.where(Tool.trust_level == tool_trust)
    if search:
        like = f"%{search}%"
        query = query.where(or_(Tool.name.ilike(like), Tool.slug.ilike(like), Tool.description.ilike(like)))
        count_query = count_query.where(or_(Tool.name.ilike(like), Tool.slug.ilike(like), Tool.description.ilike(like)))

    total = (await db.execute(count_query)).scalar_one()
    query = query.order_by(Tool.name).limit(page_size).offset((page - 1) * page_size)
    tools = list((await db.execute(query)).scalars().all())

    items = [_to_tool_response(t) for t in tools]

    from openagent.db.pagination import create_pagination_meta
    return ToolListResponse(data=items, meta=create_pagination_meta(page, page_size, total))


@router.post(
    "",
    response_model=ToolResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"model": ApiErrorResponse},
        401: {"model": ApiErrorResponse},
        403: {"model": ApiErrorResponse},
        409: {"model": ApiErrorResponse},
    },
)
async def create_tool(
    request: Request,
    organization_id: UUID,
    data: ToolCreate,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Create a new tool."""
    await require_permission("tool:create")(request, db)

    slug = data.slug or data.name.lower().replace(" ", "-").replace("_", "-")
    slug = "".join(c for c in slug if c.isalnum() or c == "-")
    slug = "-".join(filter(None, slug.split("-")))[:100]

    repo = ToolRepository(db)
    existing = await repo.get_by_slug_and_version(organization_id, slug, data.version)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": f"A tool with slug '{slug}' and version '{data.version}' already exists", "code": "TOOL_EXISTS"},
        )

    # Validate capabilities
    valid_capabilities = set(c.value for c in ToolCapability)
    for cap in data.capabilities:
        if cap not in valid_capabilities:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": f"Invalid capability: {cap}", "code": "INVALID_CAPABILITY"},
            )

    tool = Tool(
        organization_id=organization_id,
        name=data.name,
        slug=slug,
        description=data.description,
        tool_type=ToolType(data.tool_type),
        category=ToolCategory(data.category),
        status=ToolLifecycleStatus.DRAFT,
        display_name=data.display_name,
        icon=data.icon,
        documentation_url=data.documentation_url,
        provider=data.provider,
        provider_type=ToolProviderType(data.provider_type),
        version=data.version,
        capabilities=[ToolCapability(c) for c in data.capabilities],
        risk_level=ToolRiskLevel(data.risk_level),
        execution_mode=ToolExecutionMode(data.execution_mode),
        timeout=data.timeout,
        retry_policy=data.retry_policy or {},
        supports_streaming=data.supports_streaming,
        supports_cancellation=data.supports_cancellation,
        supports_idempotency=data.supports_idempotency,
        trust_level=ToolTrustLevel(data.trust_level),
        input_schema=data.input_schema,
        output_schema=data.output_schema,
        configuration=data.configuration or {},
        tags=data.tags,
    )

    db.add(tool)
    await db.flush()

    # Create initial version
    version = ToolVersion(
        tool_id=tool.id,
        version=data.version,
        display_name=data.display_name,
        description=data.description,
        capabilities=[ToolCapability(c) for c in data.capabilities],
        risk_level=ToolRiskLevel(data.risk_level),
        execution_mode=ToolExecutionMode(data.execution_mode),
        timeout=data.timeout,
        retry_policy=data.retry_policy or {},
        supports_streaming=data.supports_streaming,
        supports_cancellation=data.supports_cancellation,
        supports_idempotency=data.supports_idempotency,
        trust_level=ToolTrustLevel(data.trust_level),
        input_schema=data.input_schema,
        output_schema=data.output_schema,
        configuration=data.configuration or {},
        metadata={},
        status=ToolLifecycleStatus.DRAFT,
        checksum="",  # TODO: compute checksum
    )
    db.add(version)
    await db.commit()
    await db.refresh(tool)

    return _to_tool_response(tool)


@router.get(
    "/{tool_id}",
    response_model=ToolResponse,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def get_tool(
    request: Request,
    organization_id: UUID,
    tool_id: UUID,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Get tool details."""
    await require_permission("tool:read")(request, db)
    repo = ToolRepository(db)
    tool = await _get_tool_or_404(db, organization_id, tool_id, repo)
    return _to_tool_response(tool)


@router.patch(
    "/{tool_id}",
    response_model=ToolResponse,
    responses={
        400: {"model": ApiErrorResponse},
        401: {"model": ApiErrorResponse},
        403: {"model": ApiErrorResponse},
        404: {"model": ApiErrorResponse},
        409: {"model": ApiErrorResponse},
    },
)
async def update_tool(
    request: Request,
    organization_id: UUID,
    tool_id: UUID,
    data: ToolUpdate,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Update a tool."""
    await require_permission("tool:update")(request, db)
    repo = ToolRepository(db)
    tool = await _get_tool_or_404(db, organization_id, tool_id, repo)

    if data.name is not None:
        tool.name = data.name
    if data.description is not None:
        tool.description = data.description
    if data.display_name is not None:
        tool.display_name = data.display_name
    if data.icon is not None:
        tool.icon = data.icon
    if data.documentation_url is not None:
        tool.documentation_url = data.documentation_url
    if data.status is not None:
        tool.status = ToolLifecycleStatus(data.status)
    if data.capabilities is not None:
        for cap in data.capabilities:
            if cap not in (c.value for c in ToolCapability):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={"error": f"Invalid capability: {cap}", "code": "INVALID_CAPABILITY"},
                )
        tool.capabilities = [ToolCapability(c) for c in data.capabilities]
    if data.risk_level is not None:
        tool.risk_level = ToolRiskLevel(data.risk_level)
    if data.execution_mode is not None:
        tool.execution_mode = ToolExecutionMode(data.execution_mode)
    if data.timeout is not None:
        tool.timeout = data.timeout
    if data.retry_policy is not None:
        tool.retry_policy = data.retry_policy
    if data.supports_streaming is not None:
        tool.supports_streaming = data.supports_streaming
    if data.supports_cancellation is not None:
        tool.supports_cancellation = data.supports_cancellation
    if data.supports_idempotency is not None:
        tool.supports_idempotency = data.supports_idempotency
    if data.trust_level is not None:
        tool.trust_level = ToolTrustLevel(data.trust_level)
    if data.input_schema is not None:
        tool.input_schema = data.input_schema
    if data.output_schema is not None:
        tool.output_schema = data.output_schema
    if data.configuration is not None:
        tool.configuration = data.configuration
    if data.tags is not None:
        tool.tags = data.tags

    await db.commit()
    await db.refresh(tool)
    return _to_tool_response(tool)


@router.delete(
    "/{tool_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def delete_tool(
    request: Request,
    organization_id: UUID,
    tool_id: UUID,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete a tool."""
    await require_permission("tool:delete")(request, db)
    repo = ToolRepository(db)
    tool = await _get_tool_or_404(db, organization_id, tool_id, repo)

    tool.deleted_at = datetime.now(timezone.utc)
    tool.status = ToolLifecycleStatus.REVOKED
    await db.commit()


# ---------------------------------------------------------------------------
# Tool Versions
# ---------------------------------------------------------------------------

@router.get(
    "/{tool_id}/versions",
    response_model=ToolVersionListResponse,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def list_tool_versions(
    request: Request,
    organization_id: UUID,
    tool_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """List versions for a tool."""
    await require_permission("tool:read")(request, db)
    repo = ToolRepository(db)
    tool = await _get_tool_or_404(db, organization_id, tool_id, repo)

    version_repo = ToolVersionRepository(db)
    total = (await db.execute(
        select(func.count(ToolVersion.id)).where(ToolVersion.tool_id == tool_id)
    )).scalar_one()

    versions = await version_repo.list_versions(tool_id)
    paginated = versions[(page - 1) * page_size: page * page_size]

    items = [_to_tool_version_response(v) for v in paginated]

    from openagent.db.pagination import create_pagination_meta
    return ToolVersionListResponse(data=items, meta=create_pagination_meta(page, page_size, total))


@router.post(
    "/{tool_id}/versions",
    response_model=ToolVersionResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"model": ApiErrorResponse},
        401: {"model": ApiErrorResponse},
        403: {"model": ApiErrorResponse},
        404: {"model": ApiErrorResponse},
        409: {"model": ApiErrorResponse},
    },
)
async def create_tool_version(
    request: Request,
    organization_id: UUID,
    tool_id: UUID,
    data: ToolVersionCreate,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Create a new version of a tool."""
    await require_permission("tool:update")(request, db)
    repo = ToolRepository(db)
    tool = await _get_tool_or_404(db, organization_id, tool_id, repo)

    version_repo = ToolVersionRepository(db)
    existing = await version_repo.get_by_tool_and_version(tool_id, data.version)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": f"Version {data.version} already exists", "code": "VERSION_EXISTS"},
        )

    version = ToolVersion(
        tool_id=tool_id,
        version=data.version,
        display_name=data.display_name,
        description=data.description,
        capabilities=[ToolCapability(c) for c in data.capabilities],
        risk_level=ToolRiskLevel(data.risk_level),
        execution_mode=ToolExecutionMode(data.execution_mode),
        timeout=data.timeout,
        retry_policy=data.retry_policy or {},
        supports_streaming=data.supports_streaming,
        supports_cancellation=data.supports_cancellation,
        supports_idempotency=data.supports_idempotency,
        trust_level=ToolTrustLevel(data.trust_level),
        input_schema=data.input_schema,
        output_schema=data.output_schema,
        configuration=data.configuration or {},
        metadata=data.metadata or {},
        status=ToolLifecycleStatus.DRAFT,
        checksum=data.checksum,
    )
    db.add(version)
    await db.commit()
    await db.refresh(version)
    return _to_tool_version_response(version)


@router.post(
    "/{tool_id}/versions/{version}/publish",
    response_model=ToolVersionResponse,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def publish_tool_version(
    request: Request,
    organization_id: UUID,
    tool_id: UUID,
    version: str,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Publish a tool version."""
    await require_permission("tool:update")(request, db)
    repo = ToolRepository(db)
    tool = await _get_tool_or_404(db, organization_id, tool_id, repo)

    version_repo = ToolVersionRepository(db)
    version_obj = await version_repo.get_by_tool_and_version(tool_id, version)
    if not version_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Version not found", "code": "VERSION_NOT_FOUND"},
        )

    version_obj.status = ToolLifecycleStatus.ACTIVE
    version_obj.published_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(version_obj)
    return _to_tool_version_response(version_obj)


@router.post(
    "/{tool_id}/versions/{version}/deprecate",
    response_model=ToolVersionResponse,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def deprecate_tool_version(
    request: Request,
    organization_id: UUID,
    tool_id: UUID,
    version: str,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Deprecate a tool version."""
    await require_permission("tool:update")(request, db)
    repo = ToolRepository(db)
    tool = await _get_tool_or_404(db, organization_id, tool_id, repo)

    version_repo = ToolVersionRepository(db)
    version_obj = await version_repo.get_by_tool_and_version(tool_id, version)
    if not version_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Version not found", "code": "VERSION_NOT_FOUND"},
        )

    version_obj.status = ToolLifecycleStatus.DEPRECATED
    version_obj.deprecated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(version_obj)
    return _to_tool_version_response(version_obj)


# ---------------------------------------------------------------------------
# Tool Execution
# ---------------------------------------------------------------------------

async def _execute_connector_tool(request, organization_id, data,
                                  auth_context, db, tool):
    """Route connector tools through ConnectorEngine (single gate).

    Requires connector:execute; resolves the caller's connection for the
    connector (most-recent connected, sharing-checked) or an explicit
    connection_id in input.
    """
    from openagent.connectors.engine import ConnectorEngine, ConnectorError
    from openagent.connectors.types import ConnectorExecutionContext
    from openagent.db.models.connector import (
        ConnectorConnection, ConnectionStatus,
    )
    tool_metadata = tool.metadata or {}
    connector_id = tool_metadata.get("connector")
    action_id = tool_metadata.get("action", tool.slug)
    if not connector_id:
        raise HTTPException(status_code=500,
                            detail={"error": "Connector tool misconfigured",
                                    "code": "CONNECTOR_MISCONFIGURED"})
    await require_permission("connector:execute")(request, db)
    tool_input = dict(data.input or {})
    explicit_connection = tool_input.pop("connection_id", None)
    connection = None
    if explicit_connection:
        try:
            connection = await ConnectorEngine(db).get_connection(
                UUID(str(explicit_connection)), organization_id)
        except Exception:
            connection = None
    if connection is None:
        result = await db.execute(
            select(ConnectorConnection).where(
                ConnectorConnection.organization_id == organization_id,
                ConnectorConnection.connector_id == connector_id,
                ConnectorConnection.status == ConnectionStatus.CONNECTED).order_by(
                    ConnectorConnection.last_used_at.desc().nullslast()).limit(10))
        for candidate in result.scalars().all():
            try:
                ConnectorEngine(db).check_sharing(
                    candidate, user_id=auth_context.user_id)
                connection = candidate
                break
            except Exception:
                continue
    if connection is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": f"No accessible connected '{connector_id}' connection",
                    "code": "NO_CONNECTION"})
    engine = ConnectorEngine(db)
    try:
        # Resolve the caller's teams so TEAM-shared connections work here too.
        team_ids: list[str] = []
        if auth_context.user_id is not None:
            try:
                from openagent.db.models.team import TeamMembership
                memberships = (await db.execute(select(TeamMembership).where(
                    TeamMembership.user_id == auth_context.user_id).limit(100))
                               ).scalars().all()
                team_ids = [str(m.team_id) for m in memberships]
            except Exception:
                team_ids = []
        outcome = await engine.execute_action(
            connector_id=connector_id, action_id=action_id,
            connection_id=connection.id, organization_id=organization_id,
            arguments={k: v for k, v in tool_input.items()
                       if k != "connection_id"},
            context=ConnectorExecutionContext(
                organization_id=str(organization_id),
                user_id=str(auth_context.user_id) if auth_context.user_id else "",
                agent_id=str(tool_input.get("agent_id", "")),
                tool_id=str(tool.id), connector_id=connector_id,
                connection_id=str(connection.id),
                policy_context={"team_ids": team_ids}),
            approval_id=data.approval_id,
            idempotency_key=data.idempotency_key or "")
        await db.commit()
    except ConnectorError as exc:
        await db.rollback()
        code_map = {"NOT_FOUND": 404, "CONNECTION_MISMATCH": 400,
                    "SHARING_DENIED": 403, "CAPABILITY_DENIED": 403,
                    "POLICY_DENIED": 403, "INVALID_APPROVAL": 409,
                    "VALIDATION_ERROR": 400, "NO_CREDENTIAL": 409,
                    "CREDENTIAL_INACTIVE": 409}
        raise HTTPException(status_code=code_map.get(exc.code, 502),
                            detail={"error": str(exc), "code": exc.code})
    if outcome.get("status") == "WAITING_FOR_APPROVAL":
        exec_repo = ToolExecutionRepository(db)
        execution = await exec_repo.create_execution(
            tool_id=tool.id, tool_version_id=tool.id,
            organization_id=organization_id, input_data=data.input,
            user_id=auth_context.user_id, idempotency_key=data.idempotency_key)
        await exec_repo.update_status(
            execution_id=execution.id, status="WAITING", output=None,
            error={"code": "APPROVAL_REQUIRED",
                   "approval_id": outcome.get("approval_id")}, duration_ms=0)
        await db.commit()
        return ToolExecutionResponse(
            execution_id=execution.id, tool_id=execution.tool_id,
            tool_version=tool.version, status="WAITING", output=None,
            error={"code": "APPROVAL_REQUIRED",
                   "approval_id": outcome.get("approval_id")},
            duration_ms=0, retryable=False, truncated=False, artifacts=[],
            metadata={"approval_id": outcome.get("approval_id")})
    exec_repo = ToolExecutionRepository(db)
    execution = await exec_repo.create_execution(
        tool_id=tool.id, tool_version_id=tool.id,
        organization_id=organization_id, input_data=data.input,
        user_id=auth_context.user_id, idempotency_key=data.idempotency_key)
    await exec_repo.update_status(
        execution_id=execution.id, status="SUCCEEDED",
        output=outcome.get("result"), error=None, duration_ms=0)
    await db.commit()
    return ToolExecutionResponse(
        execution_id=execution.id, tool_id=execution.tool_id,
        tool_version=tool.version, status="SUCCEEDED",
        output=outcome.get("result"), error=None, duration_ms=0,
        retryable=False, truncated=False, artifacts=[],
        metadata={"connector": connector_id, "action": action_id})


@router.post(
    "/execute",
    response_model=ToolExecutionResponse,
    responses={
        400: {"model": ApiErrorResponse},
        401: {"model": ApiErrorResponse},
        403: {"model": ApiErrorResponse},
        404: {"model": ApiErrorResponse},
    },
)
async def execute_tool(
    request: Request,
    organization_id: UUID,
    data: ToolExecutionRequest,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Execute a tool synchronously."""
    await require_permission("tool:execute")(request, db)

    repo = ToolRepository(db)
    tool = await repo.get(data.tool_id)
    if not tool or tool.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Tool not found", "code": "TOOL_NOT_FOUND"},
        )

    if tool.status != ToolLifecycleStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": f"Tool is not active (status: {tool.status.value})", "code": "TOOL_NOT_ACTIVE"},
        )

    # MP21: connector-backed tools delegate to the ConnectorEngine, which owns
    # the single policy -> risk -> approval gate for connector actions.
    tool_metadata = tool.metadata or {}
    if tool_metadata.get("connector_action") and tool.provider.startswith("connector:"):
        return await _execute_connector_tool(
            request, organization_id, data, auth_context, db, tool)

    # MP19 central guard: policy -> risk -> approval. No tool executes a
    # high-risk action outside this chain.
    from openagent.approvals.integrations import (
        consume_approval, load_org_policies, park_for_approval, tool_action_context,
    )
    from openagent.approvals.policy import evaluate_policies
    from openagent.approvals.risk import evaluate_risk
    from openagent.approvals.types import ApprovalKind, PolicyDecision

    tool_category = tool.category.value if hasattr(tool.category, "value") else str(tool.category)
    tool_risk = tool.risk_level.value if hasattr(tool.risk_level, "value") else str(tool.risk_level)
    tool_trust = tool.trust_level.value if hasattr(tool.trust_level, "value") else str(tool.trust_level)
    tool_type_val = tool.tool_type.value if hasattr(tool.tool_type, "value") else str(tool.tool_type)
    # MCP tools funnel through this same gate; MCP server trust influences
    # risk (an MCP server can never override platform policy).
    mcp_trust = "ORGANIZATION"
    if tool_type_val == "mcp" and tool_trust not in ("CORE", "VERIFIED"):
        mcp_trust = "UNTRUSTED"
    guard_ctx = tool_action_context(
        tool_name=tool.slug, tool_category=tool_category, risk_level=tool_risk,
        trust_level=tool_trust, tool_arguments=data.input,
        organization_id=organization_id, environment="development",
        mcp_trust=mcp_trust)
    guard_policies = await load_org_policies(db, organization_id)
    guard_risk = evaluate_risk(guard_ctx)
    guard_eval = evaluate_policies(ctx=guard_ctx, risk=guard_risk,
                                   policies_by_level=guard_policies)
    guard_approval = None
    if guard_eval.decision == PolicyDecision.DENY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "Action denied by guardrail policy", "code": "POLICY_DENIED",
                    "reasons": guard_risk.reasons + guard_eval.reasons,
                    "risk_level": guard_risk.risk_level.value},
        )
    if guard_eval.decision in (PolicyDecision.REQUIRE_APPROVAL,
                               PolicyDecision.REQUIRE_MULTI_APPROVAL,
                               PolicyDecision.REQUIRE_ESCALATION):
        if data.approval_id is None:
            guard_approval = await park_for_approval(
                db, organization_id=organization_id, action_type=tool.slug,
                action_category=guard_ctx.action_category, target_type="tool",
                target_id=tool.slug, params=data.input, environment="development",
                requester_type="user", requester_id=str(auth_context.user_id),
                risk=guard_risk, evaluation=guard_eval,
                approval_kind=(ApprovalKind.MULTI if guard_eval.decision
                                == PolicyDecision.REQUIRE_MULTI_APPROVAL
                                else ApprovalKind.SINGLE),
                required_approvals=guard_eval.required_approvals,
                required_role=guard_eval.required_role)
            exec_repo = ToolExecutionRepository(db)
            execution = await exec_repo.create_execution(
                tool_id=tool.id, tool_version_id=tool.id,
                organization_id=organization_id, input_data=data.input,
                user_id=auth_context.user_id, idempotency_key=data.idempotency_key)
            await exec_repo.update_status(
                execution_id=execution.id, status="WAITING",
                output=None,
                error={"code": "APPROVAL_REQUIRED",
                       "message": "Human approval required",
                       "approval_id": str(guard_approval.id) if guard_approval else None,
                       "risk_level": guard_risk.risk_level.value},
                duration_ms=0)
            await db.commit()
            return ToolExecutionResponse(
                execution_id=execution.id, tool_id=execution.tool_id,
                tool_version=tool.version, status="WAITING",
                output=None,
                error={"code": "APPROVAL_REQUIRED",
                       "approval_id": str(guard_approval.id) if guard_approval else None,
                       "risk_level": guard_risk.risk_level.value},
                duration_ms=0, retryable=False, truncated=False, artifacts=[],
                metadata={"approval_id": str(guard_approval.id) if guard_approval else None,
                          "risk_level": guard_risk.risk_level.value,
                          "policy_decision": guard_eval.decision.value})
        ok, reason = await consume_approval(
            db, approval_id=data.approval_id, organization_id=organization_id,
            action_type=tool.slug, action_category=guard_ctx.action_category,
            target_type="tool", target_id=tool.slug, params=data.input,
            environment="development")
        if not ok:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"error": f"Approval invalid: {reason}", "code": "INVALID_APPROVAL"})

    # Check idempotency
    if data.idempotency_key:
        exec_repo = ToolExecutionRepository(db)
        existing = await exec_repo.get_by_idempotency_key(organization_id, data.idempotency_key)
        if existing:
            return ToolExecutionResponse(
                execution_id=existing.id,
                tool_id=existing.tool_id,
                tool_version=existing.tool_version_id,
                status=existing.status,
                output=existing.output,
                error=existing.error,
                duration_ms=existing.duration_ms,
                retryable=False,
                truncated=False,
                artifacts=[],
                metadata=existing.metadata,
            )

    # Import and use the tool execution runtime
    from openagent.runtime.tools import ToolExecutionManager, tool_registry, tool_executor_registry
    from openagent.runtime.tools import ToolDefinition as RuntimeToolDefinition

    # Convert to runtime tool definition
    runtime_tool = RuntimeToolDefinition(
        id=str(tool.id),
        name=tool.slug,
        description=tool.description or "",
        input_schema=tool.input_schema,
        output_schema=tool.output_schema,
        capabilities=[c.value for c in tool.capabilities],
        risk_level=tool.risk_level.value.lower(),
        executor_id=tool.provider,
        version=tool.version,
        metadata=tool.metadata,
    )
    tool_registry.register(runtime_tool)

    # TODO: Register appropriate executor based on tool.provider
    # For now, use built-in adapter

    manager = ToolExecutionManager(
        executor_registry=tool_executor_registry,
        tool_registry=tool_registry,
        default_timeout=data.timeout or tool.timeout,
    )

    context = {
        "organization_id": str(organization_id),
        "user_id": str(auth_context.user_id) if auth_context.user_id else None,
        "agent_id": None,
        "workflow_id": None,
        "db": db,
    }

    result = await manager.execute_tool(
        tool_name=tool.slug,
        arguments=data.input,
        context=context,
    )

    # Record execution
    exec_repo = ToolExecutionRepository(db)
    execution = await exec_repo.create_execution(
        tool_id=tool.id,
        tool_version_id=tool.id,  # Simplified
        organization_id=organization_id,
        input_data=data.input,
        user_id=auth_context.user_id,
        idempotency_key=data.idempotency_key,
    )
    await exec_repo.update_status(
        execution_id=execution.id,
        status="SUCCEEDED" if result.status == "success" else "FAILED",
        output=result.output,
        error={"code": result.error_code, "message": result.error} if result.error else None,
        duration_ms=result.duration_ms,
    )
    await db.commit()

    return ToolExecutionResponse(
        execution_id=execution.id,
        tool_id=execution.tool_id,
        tool_version=tool.version,
        status=execution.status,
        output=execution.output,
        error=execution.error,
        duration_ms=execution.duration_ms,
        retryable=result.error_code in ("TOOL_TIMEOUT", "TOOL_RATE_LIMITED", "TOOL_UNAVAILABLE", "PROVIDER_ERROR") if result.error else False,
        truncated=False,
        artifacts=[],
        metadata=execution.metadata,
    )


class ToolVerifyRequest(BaseModel):
    tool_name: str = Field(min_length=1, max_length=255)
    result: Dict[str, Any] = Field(default_factory=dict)
    expected_contains: List[str] = Field(default_factory=list)
    independently_verified: bool = False
    independent_state: Optional[Dict[str, Any]] = None


@router.post(
    "/verify",
    responses={
        400: {"model": ApiErrorResponse},
        401: {"model": ApiErrorResponse},
        403: {"model": ApiErrorResponse},
    },
)
async def verify_tool_result(
    request: Request,
    organization_id: UUID,
    data: ToolVerifyRequest,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Verify a critical tool result: provider response + side effect.

    A provider success claim alone never passes without independent
    verification of the side effect.
    """
    await require_permission("evaluation:create")(request, db)

    from openagent.evaluator.integrations import verify_mcp_result, verify_tool_call
    from openagent.evaluator.metrics import inc as metrics_inc

    if data.tool_name.lower().startswith("mcp."):
        # MCP server claims are not proof of external state: independent
        # state is required to pass.
        parts = data.tool_name.split(".")
        outcome = await verify_mcp_result(
            db, organization_id=organization_id,
            server=parts[1] if len(parts) > 1 else "",
            tool=".".join(parts[2:]) if len(parts) > 2 else data.tool_name,
            result=data.result, independent_state=data.independent_state)
    else:
        outcome = await verify_tool_call(
            db, organization_id=organization_id, tool_name=data.tool_name,
            result=data.result,
            expected={"contains": data.expected_contains} if data.expected_contains else None,
            independently_verified=data.independently_verified)
    await db.commit()
    metrics_inc("evaluations_total")
    return outcome


# ---------------------------------------------------------------------------
# Tool Policies
# ---------------------------------------------------------------------------

@router.get(
    "/policies",
    response_model=ToolPolicyListResponse,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}},
)
async def list_tool_policies(
    request: Request,
    organization_id: UUID,
    team_id: Optional[UUID] = Query(None),
    agent_id: Optional[UUID] = Query(None),
    workflow_id: Optional[UUID] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """List tool policies."""
    await require_permission("tool:read")(request, db)

    repo = ToolPolicyRepository(db)
    policies = await repo.get_effective_policies(organization_id, team_id, agent_id, workflow_id)

    items = [_to_tool_policy_response(p) for p in policies]

    from openagent.db.pagination import create_pagination_meta
    return ToolPolicyListResponse(data=items, meta=create_pagination_meta(page, page_size, len(items)))


@router.post(
    "/policies",
    response_model=ToolPolicyResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"model": ApiErrorResponse},
        401: {"model": ApiErrorResponse},
        403: {"model": ApiErrorResponse},
    },
)
async def create_tool_policy(
    request: Request,
    organization_id: UUID,
    data: ToolPolicyCreate,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Create a tool policy."""
    await require_permission("tool:manage")(request, db)

    policy = ToolPolicy(
        organization_id=organization_id,
        team_id=data.team_id,
        agent_id=data.agent_id,
        workflow_id=data.workflow_id,
        tool_id=data.tool_id,
        name=data.name,
        description=data.description,
        priority=data.priority,
        allowed_tools=data.allowed_tools,
        blocked_tools=data.blocked_tools,
        allowed_categories=[ToolCategory(c) for c in data.allowed_categories] if data.allowed_categories else [],
        blocked_categories=[ToolCategory(c) for c in data.blocked_categories] if data.blocked_categories else [],
        allowed_risk_levels=[ToolRiskLevel(r) for r in data.allowed_risk_levels] if data.allowed_risk_levels else [],
        max_risk_level=ToolRiskLevel(data.max_risk_level) if data.max_risk_level else None,
        allowed_capabilities=[ToolCapability(c) for c in data.allowed_capabilities] if data.allowed_capabilities else [],
        blocked_capabilities=[ToolCapability(c) for c in data.blocked_capabilities] if data.blocked_capabilities else [],
        allowed_domains=data.allowed_domains,
        blocked_domains=data.blocked_domains,
        allowed_organizations=data.allowed_organizations,
        approval_required=data.approval_required,
        execution_limits=data.execution_limits,
        is_active=True,
    )
    db.add(policy)
    await db.commit()
    await db.refresh(policy)
    return _to_tool_policy_response(policy)


# ---------------------------------------------------------------------------
# Tool Executions
# ---------------------------------------------------------------------------

@router.get(
    "/executions",
    response_model=ToolExecutionListResponse,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}},
)
async def list_tool_executions(
    request: Request,
    organization_id: UUID,
    tool_id: Optional[UUID] = Query(None),
    agent_id: Optional[UUID] = Query(None),
    workflow_id: Optional[UUID] = Query(None),
    status: Optional[str] = Query(None),
    from_date: Optional[datetime] = Query(None),
    to_date: Optional[datetime] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """List tool executions."""
    await require_permission("tool:read")(request, db)

    exec_repo = ToolExecutionRepository(db)
    executions, total = await exec_repo.list_by_organization(
        organization_id=organization_id,
        tool_id=tool_id,
        agent_id=agent_id,
        workflow_id=workflow_id,
        status=status,
        from_date=from_date,
        to_date=to_date,
        page=page,
        page_size=page_size,
    )

    items = [_to_tool_execution_response(e) for e in executions]

    from openagent.db.pagination import create_pagination_meta
    return ToolExecutionListResponse(data=items, meta=create_pagination_meta(page, page_size, total))


@router.get(
    "/executions/{execution_id}",
    response_model=ToolExecutionRecordResponse,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def get_tool_execution(
    request: Request,
    organization_id: UUID,
    execution_id: UUID,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Get tool execution details with events."""
    await require_permission("tool:read")(request, db)

    exec_repo = ToolExecutionRepository(db)
    execution = await exec_repo.get(execution_id)
    if not execution or execution.organization_id != organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Execution not found", "code": "EXECUTION_NOT_FOUND"},
        )

    return _to_tool_execution_response(execution)


@router.get(
    "/executions/{execution_id}/events",
    response_model=List[ToolEventResponse],
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def get_tool_execution_events(
    request: Request,
    organization_id: UUID,
    execution_id: UUID,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Get events for a tool execution."""
    await require_permission("tool:read")(request, db)

    exec_repo = ToolExecutionRepository(db)
    execution = await exec_repo.get(execution_id)
    if not execution or execution.organization_id != organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Execution not found", "code": "EXECUTION_NOT_FOUND"},
        )

    event_repo = ToolExecutionEventRepository(db)
    events = await event_repo.get_events(execution_id)

    return [
        ToolEventResponse(
            id=e.id,
            execution_id=e.execution_id,
            event_type=e.event_type,
            payload=e.payload,
            sequence=e.sequence,
            timestamp=e.created_at,
        )
        for e in events
    ]


# ---------------------------------------------------------------------------
# Tool Catalog / Discovery
# ---------------------------------------------------------------------------

@router.get(
    "/categories",
    response_model=List[str],
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}},
)
async def list_tool_categories(
    request: Request,
    organization_id: UUID,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """List available tool categories."""
    await require_permission("tool:read")(request, db)
    return [c.value for c in ToolCategory]


@router.get(
    "/capabilities",
    response_model=List[str],
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}},
)
async def list_tool_capabilities(
    request: Request,
    organization_id: UUID,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """List available tool capabilities."""
    await require_permission("tool:read")(request, db)
    return [c.value for c in ToolCapability]


@router.get(
    "/risk-levels",
    response_model=List[str],
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}},
)
async def list_tool_risk_levels(
    request: Request,
    organization_id: UUID,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """List available tool risk levels."""
    await require_permission("tool:read")(request, db)
    return [r.value for r in ToolRiskLevel]


@router.get(
    "/search",
    response_model=ToolListResponse,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}},
)
async def search_tools(
    request: Request,
    organization_id: UUID,
    q: str = Query(..., min_length=1, description="Search query"),
    category: Optional[str] = Query(None),
    capability: Optional[str] = Query(None),
    risk_level: Optional[str] = Query(None),
    tags: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Search tools."""
    await require_permission("tool:read")(request, db)

    repo = ToolRepository(db)
    tool_category = ToolCategory(category) if category else None
    tool_risk = ToolRiskLevel(risk_level) if risk_level else None
    tag_list = tags.split(",") if tags else None

    tools = await repo.search(
        organization_id=organization_id,
        query_text=q,
        category=tool_category,
        risk_level=tool_risk,
        tags=tag_list,
    )

    paginated = tools[(page - 1) * page_size: page * page_size]
    items = [_to_tool_response(t) for t in paginated]

    from openagent.db.pagination import create_pagination_meta
    return ToolListResponse(data=items, meta=create_pagination_meta(page, page_size, len(tools)))


from datetime import timezone