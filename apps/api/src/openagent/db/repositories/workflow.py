from typing import Optional, List
from uuid import UUID
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.db.repositories.base import BaseRepository
from openagent.db.models.workflow import Workflow, WorkflowVersion, WorkflowStatus
from openagent.db.models.workflow_execution import WorkflowExecution, WorkflowExecutionStatus


class WorkflowRepository(BaseRepository[Workflow]):
    def __init__(self, session: AsyncSession):
        super().__init__(Workflow, session)

    async def get_by_slug(self, organization_id: UUID, slug: str) -> Optional[Workflow]:
        result = await self.session.execute(
            select(Workflow).where(
                Workflow.organization_id == organization_id,
                Workflow.slug == slug
            )
        )
        return result.scalar_one_or_none()

    async def list_by_status(self, organization_id: UUID, status: WorkflowStatus, limit: int = 20, offset: int = 0) -> List[Workflow]:
        result = await self.session.execute(
            select(Workflow)
            .where(Workflow.organization_id == organization_id, Workflow.status == status)
            .order_by(Workflow.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())


class WorkflowVersionRepository(BaseRepository[WorkflowVersion]):
    def __init__(self, session: AsyncSession):
        super().__init__(WorkflowVersion, session)

    async def get_by_workflow_and_version(self, workflow_id: UUID, version: str) -> Optional[WorkflowVersion]:
        result = await self.session.execute(
            select(WorkflowVersion).where(
                WorkflowVersion.workflow_id == workflow_id,
                WorkflowVersion.version == version
            )
        )
        return result.scalar_one_or_none()

    async def list_by_workflow(self, workflow_id: UUID, limit: int = 20, offset: int = 0) -> List[WorkflowVersion]:
        result = await self.session.execute(
            select(WorkflowVersion)
            .where(WorkflowVersion.workflow_id == workflow_id)
            .order_by(WorkflowVersion.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())


class WorkflowExecutionRepository(BaseRepository[WorkflowExecution]):
    def __init__(self, session: AsyncSession):
        super().__init__(WorkflowExecution, session)

    async def list_by_workflow(self, workflow_id: UUID, limit: int = 20, offset: int = 0) -> List[WorkflowExecution]:
        result = await self.session.execute(
            select(WorkflowExecution)
            .where(WorkflowExecution.workflow_id == workflow_id)
            .order_by(WorkflowExecution.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def list_by_status(self, organization_id: UUID, status: WorkflowExecutionStatus, limit: int = 20, offset: int = 0) -> List[WorkflowExecution]:
        result = await self.session.execute(
            select(WorkflowExecution)
            .where(WorkflowExecution.organization_id == organization_id, WorkflowExecution.status == status)
            .order_by(WorkflowExecution.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def get_running_count(self, organization_id: UUID) -> int:
        result = await self.session.execute(
            select(func.count(WorkflowExecution.id)).where(
                WorkflowExecution.organization_id == organization_id,
                WorkflowExecution.status.in_([
                    WorkflowExecutionStatus.QUEUED,
                    WorkflowExecutionStatus.RUNNING,
                    WorkflowExecutionStatus.PAUSED,
                    WorkflowExecutionStatus.WAITING
                ])
            )
        )
        return result.scalar_one()