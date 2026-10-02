"""Tool repositories for database operations."""

from __future__ import annotations

from typing import Optional, List, Dict, Any
from uuid import UUID
from datetime import datetime, timezone

from sqlalchemy import select, func, and_, or_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.db.repositories.base import BaseRepository
from openagent.db.models import (
    Tool,
    ToolVersion,
    ToolProvider,
    ToolPolicy,
    ToolExecution,
    ToolExecutionEvent,
    ToolHealth,
    ToolUsage,
    ToolLifecycleStatus,
    ToolCategory,
    ToolRiskLevel,
)


class ToolRepository(BaseRepository[Tool]):
    """Repository for Tool operations."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, Tool)

    async def get_by_slug_and_version(
        self, organization_id: Optional[UUID], slug: str, version: str = "1.0.0"
    ) -> Optional[Tool]:
        """Get tool by slug and version within an organization."""
        query = select(Tool).where(
            Tool.slug == slug,
            Tool.version == version,
            Tool.deleted_at.is_(None),
        )
        if organization_id:
            query = query.where(Tool.organization_id == organization_id)
        else:
            query = query.where(Tool.organization_id.is_(None))
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_latest_version(
        self, organization_id: Optional[UUID], slug: str
    ) -> Optional[Tool]:
        """Get the latest active version of a tool."""
        query = (
            select(Tool)
            .where(
                Tool.slug == slug,
                Tool.status == ToolLifecycleStatus.ACTIVE,
                Tool.deleted_at.is_(None),
            )
            .order_by(desc(Tool.version))
        )
        if organization_id:
            query = query.where(Tool.organization_id == organization_id)
        else:
            query = query.where(Tool.organization_id.is_(None))
        result = await self.session.execute(query.limit(1))
        return result.scalar_one_or_none()

    async def list_by_category(
        self, organization_id: Optional[UUID], category: ToolCategory, status: Optional[ToolLifecycleStatus] = None
    ) -> List[Tool]:
        """List tools by category."""
        query = select(Tool).where(
            Tool.category == category,
            Tool.deleted_at.is_(None),
        )
        if organization_id:
            query = query.where(Tool.organization_id == organization_id)
        else:
            query = query.where(Tool.organization_id.is_(None))
        if status:
            query = query.where(Tool.status == status)
        result = await self.session.execute(query.order_by(Tool.name))
        return list(result.scalars().all())

    async def list_by_risk_level(
        self, organization_id: Optional[UUID], risk_level: ToolRiskLevel
    ) -> List[Tool]:
        """List tools by risk level."""
        query = select(Tool).where(
            Tool.risk_level == risk_level,
            Tool.deleted_at.is_(None),
        )
        if organization_id:
            query = query.where(Tool.organization_id == organization_id)
        else:
            query = query.where(Tool.organization_id.is_(None))
        result = await self.session.execute(query.order_by(Tool.name))
        return list(result.scalars().all())

    async def search(
        self,
        organization_id: Optional[UUID],
        query_text: str,
        category: Optional[ToolCategory] = None,
        capability: Optional[str] = None,
        risk_level: Optional[ToolRiskLevel] = None,
        status: Optional[ToolLifecycleStatus] = None,
        tags: Optional[List[str]] = None,
    ) -> List[Tool]:
        """Search tools by various criteria."""
        query = select(Tool).where(
            Tool.deleted_at.is_(None),
            or_(
                Tool.name.ilike(f"%{query_text}%"),
                Tool.slug.ilike(f"%{query_text}%"),
                Tool.description.ilike(f"%{query_text}%"),
            ),
        )
        if organization_id:
            query = query.where(Tool.organization_id == organization_id)
        else:
            query = query.where(Tool.organization_id.is_(None))
        if category:
            query = query.where(Tool.category == category)
        if risk_level:
            query = query.where(Tool.risk_level == risk_level)
        if status:
            query = query.where(Tool.status == status)
        if tags:
            for tag in tags:
                query = query.where(Tool.tags.contains([tag]))
        result = await self.session.execute(query.order_by(Tool.name).limit(50))
        return list(result.scalars().all())


class ToolVersionRepository(BaseRepository[ToolVersion]):
    """Repository for ToolVersion operations."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, ToolVersion)

    async def get_by_tool_and_version(self, tool_id: UUID, version: str) -> Optional[ToolVersion]:
        """Get a specific version of a tool."""
        query = select(ToolVersion).where(
            ToolVersion.tool_id == tool_id,
            ToolVersion.version == version,
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_latest_published(self, tool_id: UUID) -> Optional[ToolVersion]:
        """Get the latest published version of a tool."""
        query = (
            select(ToolVersion)
            .where(
                ToolVersion.tool_id == tool_id,
                ToolVersion.status == ToolLifecycleStatus.ACTIVE,
            )
            .order_by(desc(ToolVersion.published_at))
            .limit(1)
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def list_versions(self, tool_id: UUID) -> List[ToolVersion]:
        """List all versions of a tool."""
        query = (
            select(ToolVersion)
            .where(ToolVersion.tool_id == tool_id)
            .order_by(desc(ToolVersion.created_at))
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())


class ToolProviderRepository(BaseRepository[ToolProvider]):
    """Repository for ToolProvider operations."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, ToolProvider)

    async def get_by_type(self, provider_type: str) -> List[ToolProvider]:
        """Get providers by type."""
        query = select(ToolProvider).where(
            ToolProvider.provider_type == provider_type,
            ToolProvider.is_active == True,
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_active_providers(self) -> List[ToolProvider]:
        """Get all active providers."""
        query = select(ToolProvider).where(ToolProvider.is_active == True)
        result = await self.session.execute(query)
        return list(result.scalars().all())


class ToolPolicyRepository(BaseRepository[ToolPolicy]):
    """Repository for ToolPolicy operations."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, ToolPolicy)

    async def get_effective_policies(
        self,
        organization_id: UUID,
        team_id: Optional[UUID] = None,
        agent_id: Optional[UUID] = None,
        workflow_id: Optional[UUID] = None,
    ) -> List[ToolPolicy]:
        """Get all effective policies for a context, ordered by priority."""
        query = select(ToolPolicy).where(
            ToolPolicy.is_active == True,
            or_(
                ToolPolicy.organization_id == organization_id,
                ToolPolicy.organization_id.is_(None),
            ),
        )
        if team_id:
            query = query.where(
                or_(ToolPolicy.team_id == team_id, ToolPolicy.team_id.is_(None))
            )
        if agent_id:
            query = query.where(
                or_(ToolPolicy.agent_id == agent_id, ToolPolicy.agent_id.is_(None))
            )
        if workflow_id:
            query = query.where(
                or_(ToolPolicy.workflow_id == workflow_id, ToolPolicy.workflow_id.is_(None))
            )
        query = query.order_by(desc(ToolPolicy.priority))
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_tool_specific_policies(self, tool_id: UUID) -> List[ToolPolicy]:
        """Get policies specific to a tool."""
        query = select(ToolPolicy).where(
            ToolPolicy.tool_id == tool_id,
            ToolPolicy.is_active == True,
        ).order_by(desc(ToolPolicy.priority))
        result = await self.session.execute(query)
        return list(result.scalars().all())


class ToolExecutionRepository(BaseRepository[ToolExecution]):
    """Repository for ToolExecution operations."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, ToolExecution)

    async def create_execution(
        self,
        tool_id: UUID,
        tool_version_id: UUID,
        organization_id: UUID,
        input_data: Dict[str, Any],
        agent_id: Optional[UUID] = None,
        workflow_id: Optional[UUID] = None,
        user_id: Optional[UUID] = None,
        node_execution_id: Optional[UUID] = None,
        idempotency_key: Optional[str] = None,
    ) -> ToolExecution:
        """Create a new tool execution record."""
        execution = ToolExecution(
            tool_id=tool_id,
            tool_version_id=tool_version_id,
            organization_id=organization_id,
            agent_id=agent_id,
            workflow_id=workflow_id,
            user_id=user_id,
            node_execution_id=node_execution_id,
            status="QUEUED",
            input=input_data,
            started_at=datetime.now(timezone.utc),
            idempotency_key=idempotency_key,
        )
        self.session.add(execution)
        await self.session.flush()
        return execution

    async def get_by_idempotency_key(
        self, organization_id: UUID, idempotency_key: str
    ) -> Optional[ToolExecution]:
        """Get execution by idempotency key."""
        query = select(ToolExecution).where(
            ToolExecution.organization_id == organization_id,
            ToolExecution.idempotency_key == idempotency_key,
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def update_status(
        self,
        execution_id: UUID,
        status: str,
        output: Optional[Dict[str, Any]] = None,
        error: Optional[Dict[str, Any]] = None,
        duration_ms: Optional[int] = None,
        completed_at: Optional[datetime] = None,
    ) -> Optional[ToolExecution]:
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
        if completed_at is not None:
            execution.completed_at = completed_at
        else:
            execution.completed_at = datetime.now(timezone.utc)

        await self.session.flush()
        return execution

    async def increment_retry_count(self, execution_id: UUID) -> Optional[ToolExecution]:
        """Increment the retry count for an execution."""
        execution = await self.get(execution_id)
        if not execution:
            return None
        execution.retry_count += 1
        await self.session.flush()
        return execution

    async def list_by_organization(
        self,
        organization_id: UUID,
        tool_id: Optional[UUID] = None,
        agent_id: Optional[UUID] = None,
        workflow_id: Optional[UUID] = None,
        status: Optional[str] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[List[ToolExecution], int]:
        """List executions with filters and pagination."""
        query = select(ToolExecution).where(
            ToolExecution.organization_id == organization_id
        )
        count_query = select(func.count(ToolExecution.id)).where(
            ToolExecution.organization_id == organization_id
        )

        if tool_id:
            query = query.where(ToolExecution.tool_id == tool_id)
            count_query = count_query.where(ToolExecution.tool_id == tool_id)
        if agent_id:
            query = query.where(ToolExecution.agent_id == agent_id)
            count_query = count_query.where(ToolExecution.agent_id == agent_id)
        if workflow_id:
            query = query.where(ToolExecution.workflow_id == workflow_id)
            count_query = count_query.where(ToolExecution.workflow_id == workflow_id)
        if status:
            query = query.where(ToolExecution.status == status)
            count_query = count_query.where(ToolExecution.status == status)
        if from_date:
            query = query.where(ToolExecution.started_at >= from_date)
            count_query = count_query.where(ToolExecution.started_at >= from_date)
        if to_date:
            query = query.where(ToolExecution.started_at <= to_date)
            count_query = count_query.where(ToolExecution.started_at <= to_date)

        total = (await self.session.execute(count_query)).scalar_one()

        query = query.order_by(desc(ToolExecution.started_at)).limit(page_size).offset((page - 1) * page_size)
        result = await self.session.execute(query)
        return list(result.scalars().all()), total


class ToolExecutionEventRepository(BaseRepository[ToolExecutionEvent]):
    """Repository for ToolExecutionEvent operations."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, ToolExecutionEvent)

    async def add_event(
        self,
        execution_id: UUID,
        event_type: str,
        payload: Dict[str, Any],
        sequence: int,
    ) -> ToolExecutionEvent:
        """Add an event to an execution."""
        event = ToolExecutionEvent(
            execution_id=execution_id,
            event_type=event_type,
            payload=payload,
            sequence=sequence,
        )
        self.session.add(event)
        await self.session.flush()
        return event

    async def get_events(self, execution_id: UUID) -> List[ToolExecutionEvent]:
        """Get all events for an execution."""
        query = (
            select(ToolExecutionEvent)
            .where(ToolExecutionEvent.execution_id == execution_id)
            .order_by(ToolExecutionEvent.sequence)
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())


class ToolHealthRepository(BaseRepository[ToolHealth]):
    """Repository for ToolHealth operations."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, ToolHealth)

    async def update_health(
        self,
        tool_id: UUID,
        status: str,
        success: bool,
        latency_ms: float,
    ) -> ToolHealth:
        """Update tool health metrics."""
        health = await self.get_by_tool_id(tool_id)
        if not health:
            health = ToolHealth(
                tool_id=tool_id,
                status=status,
                last_check=datetime.now(timezone.utc),
                success_count=1 if success else 0,
                failure_count=0 if success else 1,
                avg_latency_ms=latency_ms,
                last_success=datetime.now(timezone.utc) if success else None,
                last_failure=datetime.now(timezone.utc) if not success else None,
                error_rate=0.0 if success else 1.0,
            )
            self.session.add(health)
        else:
            health.status = status
            health.last_check = datetime.now(timezone.utc)
            if success:
                health.success_count += 1
                health.last_success = datetime.now(timezone.utc)
            else:
                health.failure_count += 1
                health.last_failure = datetime.now(timezone.utc)

            total = health.success_count + health.failure_count
            health.error_rate = health.failure_count / total if total > 0 else 0.0

            # Update rolling average latency
            health.avg_latency_ms = (
                health.avg_latency_ms * (total - 1) + latency_ms
            ) / total

        await self.session.flush()
        return health

    async def get_by_tool_id(self, tool_id: UUID) -> Optional[ToolHealth]:
        """Get health record for a tool."""
        query = select(ToolHealth).where(ToolHealth.tool_id == tool_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()


class ToolUsageRepository(BaseRepository[ToolUsage]):
    """Repository for ToolUsage operations."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, ToolUsage)

    async def record_usage(
        self,
        tool_id: UUID,
        organization_id: UUID,
        duration_ms: int,
        cost: float,
        success: bool,
    ) -> ToolUsage:
        """Record tool usage for analytics."""
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

        query = select(ToolUsage).where(
            ToolUsage.tool_id == tool_id,
            ToolUsage.organization_id == organization_id,
            ToolUsage.date == today,
        )
        result = await self.session.execute(query)
        usage = result.scalar_one_or_none()

        if not usage:
            usage = ToolUsage(
                tool_id=tool_id,
                organization_id=organization_id,
                date=today,
                execution_count=0,
                success_count=0,
                failure_count=0,
                total_duration_ms=0,
                total_cost=0.0,
            )
            self.session.add(usage)

        usage.execution_count += 1
        if success:
            usage.success_count += 1
        else:
            usage.failure_count += 1
        usage.total_duration_ms += duration_ms
        usage.total_cost += cost

        await self.session.flush()
        return usage

    async def get_usage_stats(
        self,
        organization_id: UUID,
        tool_id: Optional[UUID] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
    ) -> List[ToolUsage]:
        """Get usage statistics."""
        query = select(ToolUsage).where(ToolUsage.organization_id == organization_id)
        if tool_id:
            query = query.where(ToolUsage.tool_id == tool_id)
        if from_date:
            query = query.where(ToolUsage.date >= from_date)
        if to_date:
            query = query.where(ToolUsage.date <= to_date)
        query = query.order_by(desc(ToolUsage.date))
        result = await self.session.execute(query)
        return list(result.scalars().all())