"""Repositories for orchestration tables (thin wrappers over BaseRepository)."""

from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.db.models.orchestration import (
    AgentCapability,
    AgentConflict,
    AgentHandoff,
    AgentMessage,
    AgentRelationship,
    OrchestrationBudgetLedger,
    OrchestrationEvent,
    OrchestrationRun,
    OrchestrationTask,
    OrchestrationTaskAttempt,
    OrchestrationTaskDependency,
)
from openagent.db.repositories.base import BaseRepository


class OrchestrationRunRepository(BaseRepository[OrchestrationRun]):
    def __init__(self, session: AsyncSession):
        super().__init__(OrchestrationRun, session)

    async def get_by_idempotency_key(
        self, organization_id: UUID, key: str
    ) -> Optional[OrchestrationRun]:
        result = await self.session.execute(
            select(OrchestrationRun).where(
                OrchestrationRun.organization_id == organization_id,
                OrchestrationRun.idempotency_key == key,
            )
        )
        return result.scalar_one_or_none()


class OrchestrationTaskRepository(BaseRepository[OrchestrationTask]):
    def __init__(self, session: AsyncSession):
        super().__init__(OrchestrationTask, session)

    async def list_by_run(
        self, orchestration_run_id: UUID, limit: int = 200, offset: int = 0
    ) -> List[OrchestrationTask]:
        result = await self.session.execute(
            select(OrchestrationTask)
            .where(OrchestrationTask.orchestration_run_id == orchestration_run_id)
            .order_by(OrchestrationTask.created_at.asc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def get_by_external_id(
        self, orchestration_run_id: UUID, external_task_id: str
    ) -> Optional[OrchestrationTask]:
        result = await self.session.execute(
            select(OrchestrationTask).where(
                OrchestrationTask.orchestration_run_id == orchestration_run_id,
                OrchestrationTask.external_task_id == external_task_id,
            )
        )
        return result.scalar_one_or_none()


class OrchestrationTaskDependencyRepository(BaseRepository[OrchestrationTaskDependency]):
    def __init__(self, session: AsyncSession):
        super().__init__(OrchestrationTaskDependency, session)

    async def list_by_run(self, orchestration_run_id: UUID) -> List[OrchestrationTaskDependency]:
        result = await self.session.execute(
            select(OrchestrationTaskDependency).where(
                OrchestrationTaskDependency.orchestration_run_id == orchestration_run_id
            )
        )
        return list(result.scalars().all())


class AgentRelationshipRepository(BaseRepository[AgentRelationship]):
    def __init__(self, session: AsyncSession):
        super().__init__(AgentRelationship, session)

    async def list_for_agent(self, organization_id: UUID, agent_id: UUID) -> List[AgentRelationship]:
        from sqlalchemy import or_

        result = await self.session.execute(
            select(AgentRelationship).where(
                AgentRelationship.organization_id == organization_id,
                or_(
                    AgentRelationship.source_agent_id == agent_id,
                    AgentRelationship.target_agent_id == agent_id,
                ),
            )
        )
        return list(result.scalars().all())


class AgentCapabilityRepository(BaseRepository[AgentCapability]):
    def __init__(self, session: AsyncSession):
        super().__init__(AgentCapability, session)

    async def list_for_agent(self, agent_id: UUID) -> List[AgentCapability]:
        result = await self.session.execute(
            select(AgentCapability).where(AgentCapability.agent_id == agent_id)
        )
        return list(result.scalars().all())


class AgentMessageRepository(BaseRepository[AgentMessage]):
    def __init__(self, session: AsyncSession):
        super().__init__(AgentMessage, session)

    async def list_by_run(
        self, orchestration_run_id: UUID, limit: int = 200, offset: int = 0
    ) -> List[AgentMessage]:
        result = await self.session.execute(
            select(AgentMessage)
            .where(AgentMessage.orchestration_run_id == orchestration_run_id)
            .order_by(AgentMessage.created_at.asc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())


class AgentHandoffRepository(BaseRepository[AgentHandoff]):
    def __init__(self, session: AsyncSession):
        super().__init__(AgentHandoff, session)


class OrchestrationTaskAttemptRepository(BaseRepository[OrchestrationTaskAttempt]):
    def __init__(self, session: AsyncSession):
        super().__init__(OrchestrationTaskAttempt, session)

    async def list_by_task(self, task_id: UUID) -> List[OrchestrationTaskAttempt]:
        result = await self.session.execute(
            select(OrchestrationTaskAttempt)
            .where(OrchestrationTaskAttempt.task_id == task_id)
            .order_by(OrchestrationTaskAttempt.attempt_number.asc())
        )
        return list(result.scalars().all())


class OrchestrationBudgetLedgerRepository(BaseRepository[OrchestrationBudgetLedger]):
    def __init__(self, session: AsyncSession):
        super().__init__(OrchestrationBudgetLedger, session)

    async def get_by_run(self, orchestration_run_id: UUID) -> Optional[OrchestrationBudgetLedger]:
        result = await self.session.execute(
            select(OrchestrationBudgetLedger).where(
                OrchestrationBudgetLedger.orchestration_run_id == orchestration_run_id
            )
        )
        return result.scalar_one_or_none()


class OrchestrationEventRepository(BaseRepository[OrchestrationEvent]):
    def __init__(self, session: AsyncSession):
        super().__init__(OrchestrationEvent, session)

    async def list_by_run(
        self, orchestration_run_id: UUID, limit: int = 200, offset: int = 0
    ) -> List[OrchestrationEvent]:
        result = await self.session.execute(
            select(OrchestrationEvent)
            .where(OrchestrationEvent.orchestration_run_id == orchestration_run_id)
            .order_by(OrchestrationEvent.created_at.asc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())


class AgentConflictRepository(BaseRepository[AgentConflict]):
    def __init__(self, session: AsyncSession):
        super().__init__(AgentConflict, session)
