"""MCP Server API endpoints."""

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
    MCPServer,
    MCPServerVersion,
    MCPConnection,
    MCPTool,
    MCPResource,
    MCPPrompt,
    MCPHealth,
    MCPPolicy,
    MCPToolExecution,
    MCPTransport,
    MCPServerScope,
    MCPTrustLevel,
    MCPServerStatus,
    MCPConnectionState,
    Organization,
)
from openagent.db.repositories import (
    MCPServerRepository,
    MCPServerVersionRepository,
    MCPConnectionRepository,
    MCPToolRepository,
    MCPResourceRepository,
    MCPPromptRepository,
    MCPHealthRepository,
    MCPPolicyRepository,
    MCPToolExecutionRepository,
)
from openagent.schemas.base import ApiErrorResponse, PaginatedResponse
from openagent.api.dependencies import (
    get_current_org_context,
    require_permission,
    AuthorizationContext,
)
from openagent.core.config import get_settings

router = APIRouter(prefix="/organizations/{organization_id}/mcp", tags=["mcp"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class MCPServerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    display_name: Optional[str] = Field(default=None, max_length=255)
    description: Optional[str] = None
    transport: str = Field(pattern="^(stdio|streamable_http|sse|websocket)$")
    endpoint: Optional[str] = Field(default=None, max_length=500)
    command: Optional[str] = Field(default=None, max_length=500)
    args: Optional[List[str]] = None
    env: Optional[Dict[str, str]] = None
    working_directory: Optional[str] = Field(default=None, max_length=500)
    credential_id: Optional[UUID] = None
    trust_level: str = Field(default="COMMUNITY", pattern="^(CORE|VERIFIED|ORGANIZATION|COMMUNITY|UNTRUSTED)$")
    scope: str = Field(default="ORGANIZATION", pattern="^(PLATFORM|ORGANIZATION|TEAM|USER)$")
    configuration: Optional[Dict[str, Any]] = None


class MCPServerUpdate(BaseModel):
    display_name: Optional[str] = Field(default=None, max_length=255)
    description: Optional[str] = None
    endpoint: Optional[str] = Field(default=None, max_length=500)
    command: Optional[str] = Field(default=None, max_length=500)
    args: Optional[List[str]] = None
    env: Optional[Dict[str, str]] = None
    working_directory: Optional[str] = Field(default=None, max_length=500)
    credential_id: Optional[UUID] = None
    trust_level: Optional[str] = Field(default=None, pattern="^(CORE|VERIFIED|ORGANIZATION|COMMUNITY|UNTRUSTED)$")
    configuration: Optional[Dict[str, Any]] = None
    status: Optional[str] = Field(default=None, pattern="^(ACTIVE|INACTIVE|CONNECTING|ERROR|DISCONNECTED|DISABLED)$")


class MCPServerResponse(BaseModel):
    id: UUID
    organization_id: UUID
    name: str
    display_name: Optional[str] = None
    description: Optional[str] = None
    scope: str
    transport: str
    endpoint: Optional[str] = None
    command: Optional[str] = None
    args: List[str] = []
    env: Dict[str, str] = {}
    working_directory: Optional[str] = None
    credential_id: Optional[UUID] = None
    trust_level: str
    status: str
    enabled: bool
    configuration: Dict[str, Any] = {}
    metadata: Dict[str, Any] = {}
    last_connected_at: Optional[datetime] = None
    connection_error: Optional[str] = None
    capability_version: int = 0
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class MCPServerDetailResponse(MCPServerResponse):
    connections_count: int = 0
    tools_count: int = 0
    resources_count: int = 0
    prompts_count: int = 0
    health: Optional[Dict[str, Any]] = None


class MCPServerListResponse(PaginatedResponse[MCPServerResponse]):
    pass


class MCPServerInstallRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    display_name: Optional[str] = Field(default=None, max_length=255)
    description: Optional[str] = None
    transport: str = Field(pattern="^(stdio|streamable_http|sse|websocket)$")
    endpoint: Optional[str] = Field(default=None, max_length=500)
    command: Optional[str] = Field(default=None, max_length=500)
    args: Optional[List[str]] = None
    env: Optional[Dict[str, str]] = None
    working_directory: Optional[str] = Field(default=None, max_length=500)
    credential_id: Optional[UUID] = None
    trust_level: str = Field(default="COMMUNITY", pattern="^(CORE|VERIFIED|ORGANIZATION|COMMUNITY|UNTRUSTED)$")
    scope: str = Field(default="ORGANIZATION", pattern="^(PLATFORM|ORGANIZATION|TEAM|USER)$")
    configuration: Optional[Dict[str, Any]] = None


class MCPConnectionTestRequest(BaseModel):
    transport: str = Field(pattern="^(stdio|streamable_http|sse|websocket)$")
    endpoint: Optional[str] = Field(default=None, max_length=500)
    command: Optional[str] = Field(default=None, max_length=500)
    args: Optional[List[str]] = None
    env: Optional[Dict[str, str]] = None
    working_directory: Optional[str] = Field(default=None, max_length=500)
    credential_id: Optional[UUID] = None
    trust_level: str = Field(default="COMMUNITY", pattern="^(CORE|VERIFIED|ORGANIZATION|COMMUNITY|UNTRUSTED)$")
    scope: str = Field(default="ORGANIZATION", pattern="^(PLATFORM|ORGANIZATION|TEAM|USER)$")
    configuration: Optional[Dict[str, Any]] = None


class MCPConnectionTestResponse(BaseModel):
    success: bool
    server_info: Optional[Dict[str, Any]] = None
    capabilities: Optional[Dict[str, Any]] = None
    tools_count: int = 0
    resources_count: int = 0
    prompts_count: int = 0
    error: Optional[str] = None
    latency_ms: int


class MCPRefreshResponse(BaseModel):
    tools_added: List[str] = []
    tools_removed: List[str] = []
    tools_updated: List[str] = []
    resources_added: List[str] = []
    resources_removed: List[str] = []
    resources_updated: List[str] = []
    prompts_added: List[str] = []
    prompts_removed: List[str] = []
    prompts_updated: List[str] = []


class MCPHealthResponse(BaseModel):
    server_id: UUID
    status: str
    last_check: datetime
    connection_success: int
    connection_failure: int
    tool_success: int
    tool_failure: int
    resource_reads: int
    prompt_reads: int
    avg_latency_ms: float
    timeouts: int
    protocol_errors: int
    last_success: Optional[datetime] = None
    last_failure: Optional[datetime] = None


class MCPToolResponse(BaseModel):
    id: UUID
    server_id: UUID
    remote_name: str
    name: str
    display_name: Optional[str] = None
    description: Optional[str] = None
    input_schema: Dict[str, Any]
    output_schema: Optional[Dict[str, Any]] = None
    annotations: Dict[str, Any] = {}
    risk_level: str
    capabilities: List[str] = []
    trust_level: str
    status: str
    version: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class MCPToolListResponse(PaginatedResponse[MCPToolResponse]):
    pass


class MCPResourceResponse(BaseModel):
    id: UUID
    server_id: UUID
    uri: str
    name: str
    title: Optional[str] = None
    description: Optional[str] = None
    mime_type: Optional[str] = None
    size: Optional[int] = None
    metadata: Dict[str, Any] = {}
    status: str

    class Config:
        from_attributes = True


class MCPResourceListResponse(PaginatedResponse[MCPResourceResponse]):
    pass


class MCPPromptResponse(BaseModel):
    id: UUID
    server_id: UUID
    remote_name: str
    name: str
    title: Optional[str] = None
    description: Optional[str] = None
    arguments: List[Dict[str, Any]] = []
    status: str

    class Config:
        from_attributes = True


class MCPPromptListResponse(PaginatedResponse[MCPPromptResponse]):
    pass


class MCPPolicyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: Optional[str] = None
    team_id: Optional[UUID] = None
    agent_id: Optional[UUID] = None
    workflow_id: Optional[UUID] = None
    server_id: Optional[UUID] = None
    allowed_servers: List[str] = Field(default_factory=list)
    blocked_servers: List[str] = Field(default_factory=list)
    allowed_domains: List[str] = Field(default_factory=list)
    blocked_domains: List[str] = Field(default_factory=list)
    allowed_trust_levels: List[str] = Field(default_factory=list)
    max_risk_level: Optional[str] = Field(default=None, pattern="^(LOW|MEDIUM|HIGH|CRITICAL)$")
    approval_required: Dict[str, bool] = Field(default_factory=dict)
    execution_limits: Dict[str, Any] = Field(default_factory=dict)


class MCPPolicyResponse(BaseModel):
    id: UUID
    organization_id: UUID
    team_id: Optional[UUID] = None
    agent_id: Optional[UUID] = None
    workflow_id: Optional[UUID] = None
    server_id: Optional[UUID] = None
    name: str
    description: Optional[str] = None
    allowed_servers: List[str] = []
    blocked_servers: List[str] = []
    allowed_domains: List[str] = []
    blocked_domains: List[str] = []
    allowed_trust_levels: List[str] = []
    max_risk_level: Optional[str] = None
    approval_required: Dict[str, bool] = {}
    execution_limits: Dict[str, Any] = {}
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class MCPPolicyListResponse(PaginatedResponse[MCPPolicyResponse]):
    pass


class MCPToolExecutionResponse(BaseModel):
    id: UUID
    server_id: UUID
    mcp_tool_id: UUID
    organization_id: UUID
    agent_id: Optional[UUID] = None
    workflow_id: Optional[UUID] = None
    tool_execution_id: Optional[UUID] = None
    status: str
    input: Dict[str, Any]
    output: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None
    started_at: datetime
    completed_at: Optional[datetime] = None
    duration_ms: int
    retry_count: int
    is_retryable: bool

    class Config:
        from_attributes = True


class MCPToolExecutionListResponse(PaginatedResponse[MCPToolExecutionResponse]):
    pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_server_or_404(
    db: AsyncSession,
    organization_id: UUID,
    server_id: UUID,
) -> MCPServer:
    result = await db.execute(
        select(MCPServer).where(
            MCPServer.id == server_id,
            MCPServer.organization_id == organization_id,
            MCPServer.deleted_at.is_(None),
        )
    )
    server = result.scalar_one_or_none()
    if not server:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "MCP server not found", "code": "MCP_SERVER_NOT_FOUND"},
        )
    return server


def _to_server_response(server: MCPServer) -> MCPServerResponse:
    return MCPServerResponse(
        id=server.id,
        organization_id=server.organization_id,
        name=server.name,
        display_name=server.display_name,
        description=server.description,
        scope=server.scope.value,
        transport=server.transport.value,
        endpoint=server.endpoint,
        command=server.command,
        args=server.args or [],
        env=server.env or {},
        working_directory=server.working_directory,
        credential_id=server.credential_id,
        trust_level=server.trust_level.value,
        status=server.status.value,
        enabled=server.enabled,
        configuration=server.configuration or {},
        metadata=server.metadata or {},
        last_connected_at=server.last_connected_at,
        connection_error=server.connection_error,
        capability_version=server.capability_version,
        created_at=server.created_at,
        updated_at=server.updated_at,
    )


def _to_tool_response(tool: MCPTool) -> MCPToolResponse:
    return MCPToolResponse(
        id=tool.id,
        server_id=tool.server_id,
        remote_name=tool.remote_name,
        name=tool.name,
        display_name=tool.display_name,
        description=tool.description,
        input_schema=tool.input_schema,
        output_schema=tool.output_schema,
        annotations=tool.annotations or {},
        risk_level=tool.risk_level,
        capabilities=tool.capabilities or [],
        trust_level=tool.trust_level.value,
        status=tool.status,
        version=tool.version,
        created_at=tool.created_at,
        updated_at=tool.updated_at,
    )


def _to_resource_response(resource: MCPResource) -> MCPResourceResponse:
    return MCPResourceResponse(
        id=resource.id,
        server_id=resource.server_id,
        uri=resource.uri,
        name=resource.name,
        title=resource.title,
        description=resource.description,
        mime_type=resource.mime_type,
        size=resource.size,
        metadata=resource.metadata or {},
        status=resource.status,
    )


def _to_prompt_response(prompt: MCPPrompt) -> MCPPromptResponse:
    return MCPPromptResponse(
        id=prompt.id,
        server_id=prompt.server_id,
        remote_name=prompt.remote_name,
        name=prompt.name,
        title=prompt.title,
        description=prompt.description,
        arguments=prompt.arguments or [],
        status=prompt.status,
    )


def _to_policy_response(policy: MCPPolicy) -> MCPPolicyResponse:
    return MCPPolicyResponse(
        id=policy.id,
        organization_id=policy.organization_id,
        team_id=policy.team_id,
        agent_id=policy.agent_id,
        workflow_id=policy.workflow_id,
        server_id=policy.server_id,
        name=policy.name,
        description=policy.description,
        allowed_servers=policy.allowed_servers or [],
        blocked_servers=policy.blocked_servers or [],
        allowed_domains=policy.allowed_domains or [],
        blocked_domains=policy.blocked_domains or [],
        allowed_trust_levels=[t.value for t in policy.allowed_trust_levels],
        max_risk_level=policy.max_risk_level,
        approval_required=policy.approval_required or {},
        execution_limits=policy.execution_limits or {},
        is_active=policy.is_active,
        created_at=policy.created_at,
        updated_at=policy.updated_at,
    )


def _to_health_response(health: MCPHealth) -> MCPHealthResponse:
    return MCPHealthResponse(
        server_id=health.server_id,
        status=health.status,
        last_check=health.last_check,
        connection_success=health.connection_success,
        connection_failure=health.connection_failure,
        tool_success=health.tool_success,
        tool_failure=health.tool_failure,
        resource_reads=health.resource_reads,
        prompt_reads=health.prompt_reads,
        avg_latency_ms=health.avg_latency_ms,
        timeouts=health.timeouts,
        protocol_errors=health.protocol_errors,
        last_success=health.last_success,
        last_failure=health.last_failure,
    )


def _to_execution_response(execution: MCPToolExecution) -> MCPToolExecutionResponse:
    return MCPToolExecutionResponse(
        id=execution.id,
        server_id=execution.server_id,
        mcp_tool_id=execution.mcp_tool_id,
        organization_id=execution.organization_id,
        agent_id=execution.agent_id,
        workflow_id=execution.workflow_id,
        tool_execution_id=execution.tool_execution_id,
        status=execution.status,
        input=execution.input,
        output=execution.output,
        error=execution.error,
        started_at=execution.started_at,
        completed_at=execution.completed_at,
        duration_ms=execution.duration_ms,
        retry_count=execution.retry_count,
        is_retryable=execution.is_retryable,
    )


# ---------------------------------------------------------------------------
# MCP Server CRUD
# ---------------------------------------------------------------------------

@router.post(
    "/servers/install",
    response_model=MCPServerDetailResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"model": ApiErrorResponse},
        401: {"model": ApiErrorResponse},
        403: {"model": ApiErrorResponse},
        409: {"model": ApiErrorResponse},
    },
)
async def install_mcp_server(
    request: Request,
    organization_id: UUID,
    data: MCPServerInstallRequest,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Install a new MCP server."""
    await require_permission("mcp:create")(request, db)

    # Check if server name already exists
    existing = await db.execute(
        select(MCPServer).where(
            MCPServer.organization_id == organization_id,
            MCPServer.name == data.name,
            MCPServer.deleted_at.is_(None),
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": f"MCP server with name '{data.name}' already exists", "code": "MCP_SERVER_EXISTS"},
        )

    # Validate credential if provided
    if data.credential_id:
        from openagent.db.models import Credential
        cred_result = await db.execute(
            select(Credential).where(
                Credential.id == data.credential_id,
                Credential.organization_id == organization_id,
                Credential.deleted_at.is_(None),
            )
        )
        if not cred_result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "Credential not found", "code": "CREDENTIAL_NOT_FOUND"},
            )

    # Create server record
    from openagent.runtime.mcp.registry import MCPServerRegistry
    from openagent.runtime.tools import ToolRegistry, ToolExecutionRuntime
    from openagent.runtime.mcp.registry import createMCPServerRegistry
    from openagent.runtime.tools import createToolSystem, defaultExecutionOptions
    from openagent.runtime.mcp.client import MCPClientManager
    from openagent.runtime.tools import ToolRegistry as RuntimeToolRegistry
    from openagent.runtime.tools import ToolExecutionRuntime as RuntimeToolExecutionRuntime
    from openagent.runtime.tools import ToolExecutionOptions

    # For now, we'll use a simplified approach without full runtime
    server = MCPServer(
        organization_id=organization_id,
        name=data.name,
        display_name=data.display_name,
        description=data.description,
        scope=MCPServerScope(data.scope),
        transport=MCPTransport(data.transport),
        endpoint=data.endpoint,
        command=data.command,
        args=data.args or [],
        env=data.env or {},
        working_directory=data.working_directory,
        credential_id=data.credential_id,
        trust_level=MCPTrustLevel(data.trust_level),
        enabled=False,
        configuration=data.configuration or {},
        capability_version=0,
    )
    db.add(server)
    await db.commit()
    await db.refresh(server)

    return MCPServerDetailResponse(
        **_to_server_response(server).model_dump(),
        connections_count=0,
        tools_count=0,
        resources_count=0,
        prompts_count=0,
    )


@router.post(
    "/servers/test-connection",
    response_model=MCPConnectionTestResponse,
    responses={
        400: {"model": ApiErrorResponse},
        401: {"model": ApiErrorResponse},
        403: {"model": ApiErrorResponse},
    },
)
async def test_mcp_connection(
    request: Request,
    organization_id: UUID,
    data: MCPConnectionTestRequest,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Test connection to an MCP server without installing."""
    await require_permission("mcp:read")(request, db)

    # This would use the MCP client to test connection
    # For now, return a placeholder response
    return MCPConnectionTestResponse(
        success=False,
        error="Connection test not fully implemented",
        tools_count=0,
        resources_count=0,
        prompts_count=0,
        latency_ms=0,
    )


@router.get(
    "/servers",
    response_model=MCPServerListResponse,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}},
)
async def list_mcp_servers(
    request: Request,
    organization_id: UUID,
    scope: Optional[str] = Query(None, pattern="^(PLATFORM|ORGANIZATION|TEAM|USER)$"),
    status_filter: Optional[str] = Query(None, alias="status", pattern="^(ACTIVE|INACTIVE|CONNECTING|ERROR|DISCONNECTED|DISABLED)$"),
    enabled: Optional[bool] = None,
    search: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """List MCP servers in the organization."""
    await require_permission("mcp:read")(request, db)

    query = select(MCPServer).where(
        MCPServer.organization_id == organization_id,
        MCPServer.deleted_at.is_(None),
    )
    count_query = select(func.count(MCPServer.id)).where(
        MCPServer.organization_id == organization_id,
        MCPServer.deleted_at.is_(None),
    )

    if scope:
        query = query.where(MCPServer.scope == MCPServerScope(scope))
        count_query = count_query.where(MCPServer.scope == MCPServerScope(scope))

    if status_filter:
        query = query.where(MCPServer.status == MCPServerStatus(status_filter))
        count_query = count_query.where(MCPServer.status == MCPServerStatus(status_filter))

    if enabled is not None:
        query = query.where(MCPServer.enabled == enabled)
        count_query = count_query.where(MCPServer.enabled == enabled)

    if search:
        like = f"%{search}%"
        query = query.where(or_(MCPServer.name.ilike(like), MCPServer.description.ilike(like)))
        count_query = count_query.where(or_(MCPServer.name.ilike(like), MCPServer.description.ilike(like)))

    total = (await db.execute(count_query)).scalar_one()
    query = query.order_by(MCPServer.updated_at.desc()).limit(page_size).offset((page - 1) * page_size)
    servers = list((await db.execute(query)).scalars().all())

    items = [_to_server_response(s) for s in servers]

    from openagent.db.pagination import create_pagination_meta
    return MCPServerListResponse(data=items, meta=create_pagination_meta(page, page_size, total))


@router.get(
    "/servers/{server_id}",
    response_model=MCPServerDetailResponse,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def get_mcp_server(
    request: Request,
    organization_id: UUID,
    server_id: UUID,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Get MCP server details with related counts."""
    await require_permission("mcp:read")(request, db)
    server = await _get_server_or_404(db, organization_id, server_id)

    # Get related counts
    connections_count = (await db.execute(
        select(func.count(MCPConnection.id)).where(MCPConnection.server_id == server_id)
    )).scalar_one()

    tools_count = (await db.execute(
        select(func.count(MCPTool.id)).where(MCPTool.server_id == server_id)
    )).scalar_one()

    resources_count = (await db.execute(
        select(func.count(MCPResource.id)).where(MCPResource.server_id == server_id)
    )).scalar_one()

    prompts_count = (await db.execute(
        select(func.count(MCPPrompt.id)).where(MCPPrompt.server_id == server_id)
    )).scalar_one()

    # Get latest health
    health_result = await db.execute(
        select(MCPHealth)
        .where(MCPHealth.server_id == server_id)
        .order_by(MCPHealth.last_check.desc())
        .limit(1)
    )
    health = health_result.scalar_one_or_none()

    return MCPServerDetailResponse(
        **_to_server_response(server).model_dump(),
        connections_count=connections_count,
        tools_count=tools_count,
        resources_count=resources_count,
        prompts_count=prompts_count,
        health=health.__dict__ if health else None,
    )


@router.patch(
    "/servers/{server_id}",
    response_model=MCPServerDetailResponse,
    responses={
        400: {"model": ApiErrorResponse},
        401: {"model": ApiErrorResponse},
        403: {"model": ApiErrorResponse},
        404: {"model": ApiErrorResponse},
        409: {"model": ApiErrorResponse},
    },
)
async def update_mcp_server(
    request: Request,
    organization_id: UUID,
    server_id: UUID,
    data: MCPServerUpdate,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Update an MCP server."""
    await require_permission("mcp:update")(request, db)
    server = await _get_server_or_404(db, organization_id, server_id)

    if data.display_name is not None:
        server.display_name = data.display_name
    if data.description is not None:
        server.description = data.description
    if data.endpoint is not None:
        server.endpoint = data.endpoint
    if data.command is not None:
        server.command = data.command
    if data.args is not None:
        server.args = data.args
    if data.env is not None:
        server.env = data.env
    if data.working_directory is not None:
        server.working_directory = data.working_directory
    if data.credential_id is not None:
        server.credential_id = data.credential_id
    if data.trust_level is not None:
        server.trust_level = MCPTrustLevel(data.trust_level)
    if data.configuration is not None:
        server.configuration = {**server.configuration, **data.configuration}
    if data.status is not None:
        server.status = MCPServerStatus(data.status)

    server.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(server)

    return MCPServerDetailResponse(**_to_server_response(server).model_dump(), connections_count=0, tools_count=0, resources_count=0, prompts_count=0)


@router.post(
    "/servers/{server_id}/activate",
    response_model=MCPServerDetailResponse,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def activate_mcp_server(
    request: Request,
    organization_id: UUID,
    server_id: UUID,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Activate (connect) an MCP server."""
    await require_permission("mcp:update")(request, db)
    server = await _get_server_or_404(db, organization_id, server_id)

    if server.enabled:
        return MCPServerDetailResponse(**_to_server_response(server).model_dump(), connections_count=0, tools_count=0, resources_count=0, prompts_count=0)

    server.enabled = True
    server.status = MCPServerStatus.CONNECTING
    server.updated_at = datetime.utcnow()
    await db.commit()

    # In a real implementation, this would connect to the MCP server
    # and register its tools with the tool registry
    server.status = MCPServerStatus.ACTIVE
    server.last_connected_at = datetime.utcnow()
    server.connection_error = None
    await db.commit()

    return MCPServerDetailResponse(**_to_server_response(server).model_dump(), connections_count=0, tools_count=0, resources_count=0, prompts_count=0)


@router.post(
    "/servers/{server_id}/deactivate",
    response_model=MCPServerDetailResponse,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def deactivate_mcp_server(
    request: Request,
    organization_id: UUID,
    server_id: UUID,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Deactivate (disconnect) an MCP server."""
    await require_permission("mcp:update")(request, db)
    server = await _get_server_or_404(db, organization_id, server_id)

    if not server.enabled:
        return MCPServerDetailResponse(**_to_server_response(server).model_dump(), connections_count=0, tools_count=0, resources_count=0, prompts_count=0)

    server.enabled = False
    server.status = MCPServerStatus.DISCONNECTED
    server.updated_at = datetime.utcnow()
    await db.commit()

    return MCPServerDetailResponse(**_to_server_response(server).model_dump(), connections_count=0, tools_count=0, resources_count=0, prompts_count=0)


@router.post(
    "/servers/{server_id}/refresh",
    response_model=MCPRefreshResponse,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def refresh_mcp_server(
    request: Request,
    organization_id: UUID,
    server_id: UUID,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Refresh MCP server capabilities."""
    await require_permission("mcp:update")(request, db)
    server = await _get_server_or_404(db, organization_id, server_id)

    if not server.enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "Server is not active", "code": "SERVER_NOT_ACTIVE"},
        )

    server.capability_version += 1
    server.updated_at = datetime.utcnow()
    await db.commit()

    return MCPRefreshResponse(
        tools_added=[],
        tools_removed=[],
        tools_updated=[],
        resources_added=[],
        resources_removed=[],
        resources_updated=[],
        prompts_added=[],
        prompts_removed=[],
        prompts_updated=[],
    )


@router.post(
    "/servers/{server_id}/health-check",
    response_model=MCPHealthResponse,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def health_check_mcp_server(
    request: Request,
    organization_id: UUID,
    server_id: UUID,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Perform health check on MCP server."""
    await require_permission("mcp:read")(request, db)
    server = await _get_server_or_404(db, organization_id, server_id)

    health = MCPHealth(
        server_id=server_id,
        status="HEALTHY" if server.enabled else "UNAVAILABLE",
        last_check=datetime.utcnow(),
    )
    db.add(health)
    await db.commit()
    await db.refresh(health)

    return _to_health_response(health)


@router.delete(
    "/servers/{server_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def delete_mcp_server(
    request: Request,
    organization_id: UUID,
    server_id: UUID,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Delete (soft-delete) an MCP server."""
    await require_permission("mcp:delete")(request, db)
    server = await _get_server_or_404(db, organization_id, server_id)

    server.deleted_at = datetime.utcnow()
    server.enabled = False
    server.status = MCPServerStatus.DISABLED
    await db.commit()


# ---------------------------------------------------------------------------
# MCP Tools
# ---------------------------------------------------------------------------

@router.get(
    "/servers/{server_id}/tools",
    response_model=MCPToolListResponse,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def list_mcp_tools(
    request: Request,
    organization_id: UUID,
    server_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """List tools from an MCP server."""
    await require_permission("mcp:read")(request, db)
    await _get_server_or_404(db, organization_id, server_id)

    total = (await db.execute(
        select(func.count(MCPTool.id)).where(MCPTool.server_id == server_id)
    )).scalar_one()

    query = select(MCPTool).where(MCPTool.server_id == server_id).order_by(MCPTool.name).limit(page_size).offset((page - 1) * page_size)
    tools = list((await db.execute(query)).scalars().all())

    items = [_to_tool_response(t) for t in tools]

    from openagent.db.pagination import create_pagination_meta
    return MCPToolListResponse(data=items, meta=create_pagination_meta(page, page_size, total))


# ---------------------------------------------------------------------------
# MCP Resources
# ---------------------------------------------------------------------------

@router.get(
    "/servers/{server_id}/resources",
    response_model=MCPResourceListResponse,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def list_mcp_resources(
    request: Request,
    organization_id: UUID,
    server_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """List resources from an MCP server."""
    await require_permission("mcp:read")(request, db)
    await _get_server_or_404(db, organization_id, server_id)

    total = (await db.execute(
        select(func.count(MCPResource.id)).where(MCPResource.server_id == server_id)
    )).scalar_one()

    query = select(MCPResource).where(MCPResource.server_id == server_id).order_by(MCPResource.name).limit(page_size).offset((page - 1) * page_size)
    resources = list((await db.execute(query)).scalars().all())

    items = [_to_resource_response(r) for r in resources]

    from openagent.db.pagination import create_pagination_meta
    return MCPResourceListResponse(data=items, meta=create_pagination_meta(page, page_size, total))


# ---------------------------------------------------------------------------
# MCP Prompts
# ---------------------------------------------------------------------------

@router.get(
    "/servers/{server_id}/prompts",
    response_model=MCPPromptListResponse,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
async def list_mcp_prompts(
    request: Request,
    organization_id: UUID,
    server_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """List prompts from an MCP server."""
    await require_permission("mcp:read")(request, db)
    await _get_server_or_404(db, organization_id, server_id)

    total = (await db.execute(
        select(func.count(MCPPrompt.id)).where(MCPPrompt.server_id == server_id)
    )).scalar_one()

    query = select(MCPPrompt).where(MCPPrompt.server_id == server_id).order_by(MCPPrompt.name).limit(page_size).offset((page - 1) * page_size)
    prompts = list((await db.execute(query)).scalars().all())

    items = [_to_prompt_response(p) for p in prompts]

    from openagent.db.pagination import create_pagination_meta
    return MCPPromptListResponse(data=items, meta=create_pagination_meta(page, page_size, total))


# ---------------------------------------------------------------------------
# MCP Policies
# ---------------------------------------------------------------------------

@router.get(
    "/policies",
    response_model=MCPPolicyListResponse,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}},
)
async def list_mcp_policies(
    request: Request,
    organization_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """List MCP policies."""
    await require_permission("mcp:read")(request, db)

    query = select(MCPPolicy).where(
        MCPPolicy.organization_id == organization_id,
    ).order_by(MCPPolicy.created_at.desc())
    count_query = select(func.count(MCPPolicy.id)).where(MCPPolicy.organization_id == organization_id)

    total = (await db.execute(count_query)).scalar_one()
    query = query.limit(page_size).offset((page - 1) * page_size)
    policies = list((await db.execute(query)).scalars().all())

    items = [_to_policy_response(p) for p in policies]

    from openagent.db.pagination import create_pagination_meta
    return MCPPolicyListResponse(data=items, meta=create_pagination_meta(page, page_size, total))


@router.post(
    "/policies",
    response_model=MCPPolicyResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"model": ApiErrorResponse},
        401: {"model": ApiErrorResponse},
        403: {"model": ApiErrorResponse},
    },
)
async def create_mcp_policy(
    request: Request,
    organization_id: UUID,
    data: MCPPolicyCreate,
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Create an MCP policy."""
    await require_permission("mcp:manage")(request, db)

    policy = MCPPolicy(
        organization_id=organization_id,
        team_id=data.team_id,
        agent_id=data.agent_id,
        workflow_id=data.workflow_id,
        server_id=data.server_id,
        name=data.name,
        description=data.description,
        allowed_servers=data.allowed_servers,
        blocked_servers=data.blocked_servers,
        allowed_domains=data.allowed_domains,
        blocked_domains=data.blocked_domains,
        allowed_trust_levels=[MCPTrustLevel(t) for t in data.allowed_trust_levels],
        max_risk_level=data.max_risk_level,
        approval_required=data.approval_required,
        execution_limits=data.execution_limits,
        is_active=True,
    )
    db.add(policy)
    await db.commit()
    await db.refresh(policy)
    return _to_policy_response(policy)


# ---------------------------------------------------------------------------
# MCP Tool Executions
# ---------------------------------------------------------------------------

@router.get(
    "/executions",
    response_model=MCPToolExecutionListResponse,
    responses={401: {"model": ApiErrorResponse}, 403: {"model": ApiErrorResponse}},
)
async def list_mcp_executions(
    request: Request,
    organization_id: UUID,
    server_id: Optional[UUID] = Query(None),
    agent_id: Optional[UUID] = Query(None),
    workflow_id: Optional[UUID] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    from_date: Optional[datetime] = Query(None),
    to_date: Optional[datetime] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    auth_context=Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    """List MCP tool executions."""
    await require_permission("mcp:read")(request, db)

    query = select(MCPToolExecution).where(
        MCPToolExecution.organization_id == organization_id
    )
    count_query = select(func.count(MCPToolExecution.id)).where(
        MCPToolExecution.organization_id == organization_id
    )

    if server_id:
        query = query.where(MCPToolExecution.server_id == server_id)
        count_query = count_query.where(MCPToolExecution.server_id == server_id)
    if agent_id:
        query = query.where(MCPToolExecution.agent_id == agent_id)
        count_query = count_query.where(MCPToolExecution.agent_id == agent_id)
    if workflow_id:
        query = query.where(MCPToolExecution.workflow_id == workflow_id)
        count_query = count_query.where(MCPToolExecution.workflow_id == workflow_id)
    if status_filter:
        query = query.where(MCPToolExecution.status == status_filter)
        count_query = count_query.where(MCPToolExecution.status == status_filter)
    if from_date:
        query = query.where(MCPToolExecution.started_at >= from_date)
        count_query = count_query.where(MCPToolExecution.started_at >= from_date)
    if to_date:
        query = query.where(MCPToolExecution.started_at <= to_date)
        count_query = count_query.where(MCPToolExecution.started_at <= to_date)

    total = (await db.execute(count_query)).scalar_one()
    query = query.order_by(MCPToolExecution.started_at.desc()).limit(page_size).offset((page - 1) * page_size)
    executions = list((await db.execute(query)).scalars().all())

    items = [_to_execution_response(e) for e in executions]

    from openagent.db.pagination import create_pagination_meta
    return MCPToolExecutionListResponse(data=items, meta=create_pagination_meta(page, page_size, total))


from datetime import datetime
from sqlalchemy import func
from uuid import UUID
from fastapi import APIRouter, Depends, Request, HTTPException, status, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List, Dict, Any