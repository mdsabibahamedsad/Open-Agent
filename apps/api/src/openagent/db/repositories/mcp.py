"""MCP repositories for database operations."""

from __future__ import annotations

from typing import Optional, List, Dict, Any
from uuid import UUID
from datetime import datetime, timezone

from sqlalchemy import select, func, and_, or_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.db.repositories.base import BaseRepository
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
    MCPServerStatus,
    MCPConnectionState,
    MCPTrustLevel,
)


class MCPServerRepository(BaseRepository[MCPServer]):
    """Repository for MCP Server operations."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, MCPServer)

    async def get_by_name_and_org(self, organization_id: UUID, name: str) -> Optional[MCPServer]:
        """Get server by name within an organization."""
        query = select(MCPServer).where(
            MCPServer.organization_id == organization_id,
            MCPServer.name == name,
            MCPServer.deleted_at.is_(None),
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def list_by_organization(
        self,
        organization_id: UUID,
        scope: Optional[str] = None,
        status_filter: Optional[str] = None,
        enabled: Optional[bool] = None,
        search: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[List[MCPServer], int]:
        """List servers with filters and pagination."""
        query = select(MCPServer).where(
            MCPServer.organization_id == organization_id,
            MCPServer.deleted_at.is_(None),
        )
        count_query = select(func.count(MCPServer.id)).where(
            MCPServer.organization_id == organization_id,
            MCPServer.deleted_at.is_(None),
        )

        if scope:
            from openagent.db.models.mcp import MCPServerScope
            query = query.where(MCPServer.scope == MCPServerScope(scope))
            count_query = count_query.where(MCPServer.scope == MCPServerScope(scope))
        if status_filter:
            from openagent.db.models.mcp import MCPServerStatus
            query = query.where(MCPServer.status == MCPServerStatus(status_filter))
            count_query = count_query.where(MCPServer.status == MCPServerStatus(status_filter))
        if enabled is not None:
            query = query.where(MCPServer.enabled == enabled)
            count_query = count_query.where(MCPServer.enabled == enabled)
        if search:
            like = f"%{search}%"
            query = query.where(or_(MCPServer.name.ilike(like), MCPServer.description.ilike(like)))
            count_query = count_query.where(or_(MCPServer.name.ilike(like), MCPServer.description.ilike(like)))

        total = (await self.session.execute(count_query)).scalar_one()
        query = query.order_by(desc(MCPServer.updated_at)).limit(page_size).offset((page - 1) * page_size)
        return list((await self.session.execute(query)).scalars().all()), total


class MCPServerVersionRepository(BaseRepository[MCPServerVersion]):
    """Repository for MCP Server Version operations."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, MCPServerVersion)

    async def list_by_server(self, server_id: UUID) -> List[MCPServerVersion]:
        """List all versions for a server."""
        query = select(MCPServerVersion).where(MCPServerVersion.server_id == server_id).order_by(desc(MCPServerVersion.created_at))
        result = await self.session.execute(query)
        return list(result.scalars().all())


class MCPConnectionRepository(BaseRepository[MCPConnection]):
    """Repository for MCP Connection operations."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, MCPConnection)

    async def get_active_connection(self, server_id: UUID) -> Optional[MCPConnection]:
        """Get the active connection for a server."""
        query = select(MCPConnection).where(
            MCPConnection.server_id == server_id,
            MCPConnection.state.in_(["CONNECTING", "CONNECTED", "DEGRADED"]),
        ).order_by(desc(MCPConnection.last_activity))
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def list_by_server(self, server_id: UUID) -> List[MCPConnection]:
        """List all connections for a server."""
        query = select(MCPConnection).where(MCPConnection.server_id == server_id).order_by(desc(MCPConnection.created_at))
        result = await self.session.execute(query)
        return list(result.scalars().all())


class MCPToolRepository(BaseRepository[MCPTool]):
    """Repository for MCP Tool operations."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, MCPTool)

    async def get_by_server_and_name(self, server_id: UUID, remote_name: str) -> Optional[MCPTool]:
        """Get tool by server and remote name."""
        query = select(MCPTool).where(
            MCPTool.server_id == server_id,
            MCPTool.remote_name == remote_name,
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def list_by_server(
        self,
        server_id: UUID,
        status_filter: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[List[MCPTool], int]:
        """List tools for a server with pagination."""
        query = select(MCPTool).where(MCPTool.server_id == server_id)
        count_query = select(func.count(MCPTool.id)).where(MCPTool.server_id == server_id)

        if status_filter:
            query = query.where(MCPTool.status == status_filter)
            count_query = count_query.where(MCPTool.status == status_filter)

        total = (await self.session.execute(count_query)).scalar_one()
        query = query.order_by(MCPTool.name).limit(page_size).offset((page - 1) * page_size)
        return list((await self.session.execute(query)).scalars().all()), total


class MCPResourceRepository(BaseRepository[MCPResource]):
    """Repository for MCP Resource operations."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, MCPResource)

    async def get_by_server_and_uri(self, server_id: UUID, uri: str) -> Optional[MCPResource]:
        """Get resource by server and URI."""
        query = select(MCPResource).where(
            MCPResource.server_id == server_id,
            MCPResource.uri == uri,
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def list_by_server(
        self,
        server_id: UUID,
        mime_type: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[List[MCPResource], int]:
        """List resources for a server with pagination."""
        query = select(MCPResource).where(MCPResource.server_id == server_id)
        count_query = select(func.count(MCPResource.id)).where(MCPResource.server_id == server_id)

        if mime_type:
            query = query.where(MCPResource.mime_type == mime_type)
            count_query = count_query.where(MCPResource.mime_type == mime_type)

        total = (await self.session.execute(count_query)).scalar_one()
        query = query.order_by(MCPResource.name).limit(page_size).offset((page - 1) * page_size)
        return list((await self.session.execute(query)).scalars().all()), total


class MCPPromptRepository(BaseRepository[MCPPrompt]):
    """Repository for MCP Prompt operations."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, MCPPrompt)

    async def get_by_server_and_name(self, server_id: UUID, remote_name: str) -> Optional[MCPPrompt]:
        """Get prompt by server and remote name."""
        query = select(MCPPrompt).where(
            MCPPrompt.server_id == server_id,
            MCPPrompt.remote_name == remote_name,
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def list_by_server(
        self,
        server_id: UUID,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[List[MCPPrompt], int]:
        """List prompts for a server with pagination."""
        query = select(MCPPrompt).where(MCPPrompt.server_id == server_id)
        count_query = select(func.count(MCPPrompt.id)).where(MCPPrompt.server_id == server_id)

        total = (await self.session.execute(count_query)).scalar_one()
        query = query.order_by(MCPPrompt.name).limit(page_size).offset((page - 1) * page_size)
        return list((await self.session.execute(query)).scalars().all()), total


class MCPHealthRepository(BaseRepository[MCPHealth]):
    """Repository for MCP Health operations."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, MCPHealth)

    async def get_latest(self, server_id: UUID) -> Optional[MCPHealth]:
        """Get latest health record for a server."""
        query = select(MCPHealth).where(MCPHealth.server_id == server_id).order_by(desc(MCPHealth.last_check)).limit(1)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def record_health(
        self,
        server_id: UUID,
        status: str,
        connection_success: int = 0,
        connection_failure: int = 0,
        tool_success: int = 0,
        tool_failure: int = 0,
        resource_reads: int = 0,
        prompt_reads: int = 0,
        avg_latency_ms: float = 0.0,
        timeouts: int = 0,
        protocol_errors: int = 0,
    ) -> MCPHealth:
        """Record health metrics for a server."""
        health = MCPHealth(
            server_id=server_id,
            status=status,
            last_check=datetime.now(timezone.utc),
            connection_success=connection_success,
            connection_failure=connection_failure,
            tool_success=tool_success,
            tool_failure=tool_failure,
            resource_reads=resource_reads,
            prompt_reads=prompt_reads,
            avg_latency_ms=avg_latency_ms,
            timeouts=timeouts,
            protocol_errors=protocol_errors,
            last_success=datetime.now(timezone.utc) if status == "HEALTHY" else None,
            last_failure=datetime.now(timezone.utc) if status == "UNAVAILABLE" else None,
        )
        self.session.add(health)
        await self.session.flush()
        return health


class MCPPolicyRepository(BaseRepository[MCPPolicy]):
    """Repository for MCP Policy operations."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, MCPPolicy)

    async def get_effective_policies(
        self,
        organization_id: UUID,
        team_id: Optional[UUID] = None,
        agent_id: Optional[UUID] = None,
        workflow_id: Optional[UUID] = None,
    ) -> List[MCPPolicy]:
        """Get all effective policies for a context."""
        query = select(MCPPolicy).where(
            MCPPolicy.organization_id == organization_id,
            MCPPolicy.is_active == True,
        )
        if team_id:
            query = query.where(
                or_(MCPPolicy.team_id == team_id, MCPPolicy.team_id.is_(None))
            )
        if agent_id:
            query = query.where(
                or_(MCPPolicy.agent_id == agent_id, MCPPolicy.agent_id.is_(None))
            )
        if workflow_id:
            query = query.where(
                or_(MCPPolicy.workflow_id == workflow_id, MCPPolicy.workflow_id.is_(None))
            )
        query = query.order_by(desc(MCPPolicy.priority) if hasattr(MCPPolicy, 'priority') else MCPPolicy.created_at)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_server_policies(self, server_id: UUID) -> List[MCPPolicy]:
        """Get policies specific to a server."""
        query = select(MCPPolicy).where(
            MCPPolicy.server_id == server_id,
            MCPPolicy.is_active == True,
        ).order_by(desc(MCPPolicy.created_at))
        result = await self.session.execute(query)
        return list(result.scalars().all())


class MCPToolExecutionRepository(BaseRepository[MCPToolExecution]):
    """Repository for MCP Tool Execution operations."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, MCPToolExecution)

    async def create_execution(
        self,
        server_id: UUID,
        mcp_tool_id: UUID,
        organization_id: UUID,
        input_data: Dict[str, Any],
        agent_id: Optional[UUID] = None,
        workflow_id: Optional[UUID] = None,
        tool_execution_id: Optional[UUID] = None,
    ) -> MCPToolExecution:
        """Create a new tool execution record."""
        execution = MCPToolExecution(
            server_id=server_id,
            mcp_tool_id=mcp_tool_id,
            organization_id=organization_id,
            agent_id=agent_id,
            workflow_id=workflow_id,
            tool_execution_id=tool_execution_id,
            status="QUEUED",
            input=input_data,
            started_at=datetime.now(timezone.utc),
        )
        self.session.add(execution)
        await self.session.flush()
        return execution

    async def update_status(
        self,
        execution_id: UUID,
        status: str,
        output: Optional[Dict[str, Any]] = None,
        error: Optional[Dict[str, Any]] = None,
        duration_ms: Optional[int] = None,
        retry_count: Optional[int] = None,
        is_retryable: Optional[bool] = None,
    ) -> Optional[MCPToolExecution]:
        """Update execution status and result."""
        execution = await self.get(execution_id)
        if not execution:
            return None

        execution.status = status
        if output is not None:
            execution.output = output
        if error is not None:
            execution.error = error
        if duration_ms is not None:
            execution.duration_ms = duration_ms
        if retry_count is not None:
            execution.retry_count = retry_count
        if is_retryable is not None:
            execution.is_retryable = is_retryable
        if status in ("SUCCEEDED", "FAILED", "CANCELLED", "TIMED_OUT"):
            execution.completed_at = datetime.now(timezone.utc)

        await self.session.flush()
        return execution

    async def list_by_organization(
        self,
        organization_id: UUID,
        server_id: Optional[UUID] = None,
        agent_id: Optional[UUID] = None,
        workflow_id: Optional[UUID] = None,
        status_filter: Optional[str] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[List[MCPToolExecution], int]:
        """List executions with filters and pagination."""
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

        total = (await self.session.execute(count_query)).scalar_one()
        query = query.order_by(desc(MCPToolExecution.started_at)).limit(page_size).offset((page - 1) * page_size)
        return list((await self.session.execute(query)).scalars().all()), total


from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from uuid import UUID
from openagent.db.repositories.base import BaseRepository
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
)