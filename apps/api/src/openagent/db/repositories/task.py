from typing import Optional, List
from uuid import UUID
from datetime import datetime, timezone
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.db.repositories.base import BaseRepository
from openagent.db.models.task import Task, TaskStatus, TaskPriority


class TaskRepository(BaseRepository[Task]):
    def __init__(self, session: AsyncSession):
        super().__init__(Task, session)

    async def list_by_status(self, organization_id: UUID, status: TaskStatus, limit: int = 20, offset: int = 0) -> List[Task]:
        result = await self.session.execute(
            select(Task)
            .where(Task.organization_id == organization_id, Task.status == status)
            .order_by(Task.priority.desc(), Task.available_at.asc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def list_pending_tasks(self, organization_id: UUID, limit: int = 100) -> List[Task]:
        now = datetime.now(timezone.utc)
        result = await self.session.execute(
            select(Task)
            .where(
                Task.organization_id == organization_id,
                Task.status.in_([TaskStatus.PENDING, TaskStatus.QUEUED]),
                Task.available_at <= now
            )
            .order_by(Task.priority.desc(), Task.available_at.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def claim_task(self, task_id: UUID) -> Optional[Task]:
        now = datetime.now(timezone.utc)
        result = await self.session.execute(
            update(Task)
            .where(Task.id == task_id, Task.status.in_([TaskStatus.PENDING, TaskStatus.QUEUED]))
            .values(status=TaskStatus.RUNNING, started_at=now, attempts=Task.attempts + 1)
            .returning(Task)
        )
        return result.scalar_one_or_none()

    async def complete_task(self, task_id: UUID, result: dict) -> Optional[Task]:
        now = datetime.now(timezone.utc)
        result_obj = await self.session.execute(
            update(Task)
            .where(Task.id == task_id)
            .values(status=TaskStatus.COMPLETED, completed_at=now, result=result)
            .returning(Task)
        )
        return result_obj.scalar_one_or_none()

    async def fail_task(self, task_id: UUID, error: str) -> Optional[Task]:
        now = datetime.now(timezone.utc)
        result_obj = await self.session.execute(
            update(Task)
            .where(Task.id == task_id)
            .values(status=TaskStatus.FAILED, completed_at=now, error=error)
            .returning(Task)
        )
        return result_obj.scalar_one_or_none()

    async def retry_task(self, task_id: UUID) -> Optional[Task]:
        result_obj = await self.session.execute(
            update(Task)
            .where(Task.id == task_id, Task.attempts < Task.max_attempts)
            .values(status=TaskStatus.RETRYING, error=None)
            .returning(Task)
        )
        return result_obj.scalar_one_or_none()