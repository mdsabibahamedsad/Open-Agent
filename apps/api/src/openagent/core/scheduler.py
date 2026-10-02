import asyncio
import uuid
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Any, Callable, Awaitable, Dict, List, Optional, Set
from dataclasses import dataclass, field
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager

from sqlalchemy import String, Text, ForeignKey, Index, Enum as SQLEnum, DateTime, JSON, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete

from openagent.db.models.base import Base, TimestampMixin, UUIDMixin
from openagent.core.config import get_settings
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openagent.db.session import get_db as _get_db_impl

def _get_db() -> AsyncSession:
    """Lazy import to avoid circular dependency with db.session."""
    from openagent.db.session import get_db as _get_db_impl
    return _get_db_impl()


class ScheduleStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    DELETED = "deleted"


class ScheduleTriggerType(str, Enum):
    CRON = "cron"
    INTERVAL = "interval"
    ONE_TIME = "one_time"
    EVENT = "event"


@dataclass
class ScheduleConfig:
    """Configuration for a scheduled job."""
    trigger_type: ScheduleTriggerType
    # Cron expression for cron triggers
    cron_expression: Optional[str] = None
    # Interval in seconds for interval triggers
    interval_seconds: Optional[int] = None
    # One-time execution time
    run_at: Optional[datetime] = None
    # Timezone for cron expressions
    timezone: str = "UTC"
    # Maximum concurrent executions
    max_concurrent: int = 1
    # Timeout for job execution
    timeout_seconds: int = 300
    # Retry policy
    max_retries: int = 3
    retry_delay_seconds: int = 60


class ScheduledJob(Base, TimestampMixin):
    """Scheduled job definition."""
    
    __tablename__ = "scheduled_jobs"
    
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    job_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    trigger_type: Mapped[str] = mapped_column(
        SQLEnum(ScheduleTriggerType.CRON, ScheduleTriggerType.INTERVAL, ScheduleTriggerType.ONE_TIME, ScheduleTriggerType.EVENT,
                name="schedule_trigger_type", create_constraint=True),
        nullable=False
    )
    cron_expression: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    interval_seconds: Mapped[Optional[int]] = mapped_column(nullable=True)
    run_at: Mapped[Optional[datetime]] = mapped_column(nullable=True, index=True)
    timezone: Mapped[str] = mapped_column(String(50), default="UTC", nullable=False)
    status: Mapped[str] = mapped_column(
        SQLEnum(ScheduleStatus.ACTIVE, ScheduleStatus.PAUSED, ScheduleStatus.COMPLETED, ScheduleStatus.FAILED, ScheduleStatus.DELETED,
                name="schedule_status", create_constraint=True),
        default=ScheduleStatus.ACTIVE,
        nullable=False,
        index=True
    )
    max_concurrent: Mapped[int] = mapped_column(default=1, nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(default=300, nullable=False)
    max_retries: Mapped[int] = mapped_column(default=3, nullable=False)
    retry_delay_seconds: Mapped[int] = mapped_column(default=60, nullable=False)
    last_run_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    next_run_at: Mapped[Optional[datetime]] = mapped_column(nullable=True, index=True)
    run_count: Mapped[int] = mapped_column(default=0, nullable=False)
    failure_count: Mapped[int] = mapped_column(default=0, nullable=False)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metadata: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    
    __table_args__ = (
        Index("ix_scheduled_jobs_org_status", "organization_id", "status"),
        Index("ix_scheduled_jobs_next_run", "next_run_at"),
        Index("ix_scheduled_jobs_status_type", "status", "job_type"),
    )


class ScheduledJobRun(Base, TimestampMixin):
    """Execution record for a scheduled job."""
    
    __tablename__ = "scheduled_job_runs"
    
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scheduled_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(
        SQLEnum(ScheduleStatus.ACTIVE, ScheduleStatus.PAUSED, ScheduleStatus.COMPLETED, ScheduleStatus.FAILED, ScheduleStatus.DELETED,
                name="schedule_run_status", create_constraint=True),
        nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    result: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    attempt: Mapped[int] = mapped_column(default=1, nullable=False)
    
    __table_args__ = (
        Index("ix_scheduled_job_runs_job_status", "job_id", "status"),
        Index("ix_scheduled_job_runs_started", "started_at"),
    )


class SchedulerService:
    """Service for managing scheduled jobs."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.settings = get_settings()
        self._running = False
        self._scheduler_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        self._job_handlers: Dict[str, Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]] = {}
    
    def register_handler(self, job_type: str, handler: Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]) -> None:
        """Register a job handler."""
        self._job_handlers[job_type] = handler
    
    async def start(self) -> None:
        """Start the scheduler."""
        if self._running:
            return
        self._running = True
        self._scheduler_task = asyncio.create_task(self._scheduler_loop())
    
    async def stop(self) -> None:
        """Stop the scheduler."""
        self._running = False
        if self._scheduler_task:
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except asyncio.CancelledError:
                pass
    
    async def create_job(
        self,
        organization_id: uuid.UUID,
        name: str,
        job_type: str,
        payload: Dict[str, Any],
        config: ScheduleConfig,
        description: Optional[str] = None,
    ) -> ScheduledJob:
        """Create a new scheduled job."""
        # Calculate next run time
        next_run = self._calculate_next_run(config)
        
        job = ScheduledJob(
            organization_id=organization_id,
            name=name,
            description=description,
            job_type=job_type,
            payload=payload,
            trigger_type=config.trigger_type,
            cron_expression=config.cron_expression,
            interval_seconds=config.interval_seconds,
            run_at=config.run_at,
            timezone=config.timezone,
            status=ScheduleStatus.ACTIVE,
            max_concurrent=config.max_concurrent,
            timeout_seconds=config.timeout_seconds,
            max_retries=config.max_retries,
            retry_delay_seconds=config.retry_delay_seconds,
            next_run_at=next_run,
        )
        self.db.add(job)
        await self.db.flush()
        return job
    
    async def update_job(
        self,
        job_id: uuid.UUID,
        organization_id: uuid.UUID,
        config: Optional[ScheduleConfig] = None,
        status: Optional[ScheduleStatus] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Optional[ScheduledJob]:
        """Update a scheduled job."""
        result = await self.db.execute(
            select(ScheduledJob).where(
                ScheduledJob.id == job_id,
                ScheduledJob.organization_id == organization_id,
            )
        )
        job = result.scalar_one_or_none()
        
        if not job:
            return None
        
        if config:
            if config.trigger_type:
                job.trigger_type = config.trigger_type
            if config.cron_expression is not None:
                job.cron_expression = config.cron_expression
            if config.interval_seconds is not None:
                job.interval_seconds = config.interval_seconds
            if config.run_at is not None:
                job.run_at = config.run_at
            if config.timezone:
                job.timezone = config.timezone
            if config.max_concurrent:
                job.max_concurrent = config.max_concurrent
            if config.timeout_seconds:
                job.timeout_seconds = config.timeout_seconds
            if config.max_retries:
                job.max_retries = config.max_retries
            if config.retry_delay_seconds:
                job.retry_delay_seconds = config.retry_delay_seconds
            
            # Recalculate next run
            job.next_run_at = self._calculate_next_run_for_job(job)
        
        if status:
            job.status = status
        if name:
            job.name = name
        if description is not None:
            job.description = description
        
        await self.db.flush()
        return job
    
    async def delete_job(self, job_id: uuid.UUID, organization_id: uuid.UUID) -> bool:
        """Delete a scheduled job."""
        result = await self.db.execute(
            select(ScheduledJob).where(
                ScheduledJob.id == job_id,
                ScheduledJob.organization_id == organization_id,
            )
        )
        job = result.scalar_one_or_none()
        
        if not job:
            return False
        
        job.status = ScheduleStatus.DELETED
        await self.db.flush()
        return True
    
    async def get_job(self, job_id: uuid.UUID, organization_id: uuid.UUID) -> Optional[ScheduledJob]:
        result = await self.db.execute(
            select(ScheduledJob).where(
                ScheduledJob.id == job_id,
                ScheduledJob.organization_id == organization_id,
            )
        )
        return result.scalar_one_or_none()
    
    async def list_jobs(
        self,
        organization_id: uuid.UUID,
        status: Optional[ScheduleStatus] = None,
        job_type: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[ScheduledJob]:
        query = select(ScheduledJob).where(ScheduledJob.organization_id == organization_id)
        
        if status:
            query = query.where(ScheduledJob.status == status)
        if job_type:
            query = query.where(ScheduledJob.job_type == job_type)
        
        query = query.order_by(ScheduledJob.created_at.desc()).limit(limit).offset(offset)
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    async def trigger_job(self, job_id: uuid.UUID, organization_id: uuid.UUID) -> Optional[ScheduledJobRun]:
        """Manually trigger a job execution."""
        job = await self.get_job(job_id, organization_id)
        if not job:
            return None
        
        return await self._execute_job(job)
    
    async def _execute_job(self, job: ScheduledJob) -> ScheduledJobRun:
        """Execute a scheduled job."""
        run = ScheduledJobRun(
            job_id=job.id,
            status=ScheduleStatus.RUNNING,
            started_at=datetime.now(timezone.utc),
            attempt=1,
        )
        self.db.add(run)
        await self.db.flush()
        
        try:
            handler = self._job_handlers.get(job.job_type)
            if not handler:
                raise ValueError(f"No handler for job type: {job.job_type}")
            
            # Apply timeout
            result = await asyncio.wait_for(
                handler(job.payload),
                timeout=job.timeout_seconds,
            )
            
            run.status = ScheduleStatus.COMPLETED
            run.completed_at = datetime.now(timezone.utc)
            run.result = result
            
            # Update job
            job.last_run_at = run.started_at
            job.run_count += 1
            job.next_run_at = self._calculate_next_run_for_job(job)
            
        except asyncio.CancelledError:
            raise
        except Exception as e:
            run.status = ScheduleStatus.FAILED
            run.completed_at = datetime.now(timezone.utc)
            run.error = str(e)
            
            job.failure_count += 1
            job.last_error = str(e)
            
            # Retry logic
            if run.attempt < job.max_retries:
                run.status = ScheduleStatus.PENDING
                run.attempt += 1
                # Retry will be handled by scheduler
            else:
                # Max retries exceeded
                if job.failure_count >= job.max_retries:
                    job.status = ScheduleStatus.FAILED
        
        await self.db.flush()
        return run
    
    def _calculate_next_run(self, config: ScheduleConfig) -> Optional[datetime]:
        """Calculate next run time based on config."""
        now = datetime.now(timezone.utc)
        
        if config.trigger_type == ScheduleTriggerType.ONE_TIME:
            return config.run_at
        elif config.trigger_type == ScheduleTriggerType.INTERVAL:
            return now + timedelta(seconds=config.interval_seconds)
        elif config.trigger_type == ScheduleTriggerType.CRON:
            return self._calculate_cron_next_run(config.cron_expression, config.timezone, now)
        
        return None
    
    def _calculate_next_run_for_job(self, job: ScheduledJob) -> Optional[datetime]:
        """Calculate next run time for a job."""
        now = datetime.now(timezone.utc)
        
        if job.trigger_type == ScheduleTriggerType.ONE_TIME:
            return None  # One-time jobs don't repeat
        elif job.trigger_type == ScheduleTriggerType.INTERVAL:
            return now + timedelta(seconds=job.interval_seconds)
        elif job.trigger_type == ScheduleTriggerType.CRON:
            return self._calculate_cron_next_run(job.cron_expression, job.timezone, now)
        
        return None
    
    def _calculate_cron_next_run(
        self,
        cron_expression: Optional[str],
        timezone: str,
        from_time: datetime,
    ) -> Optional[datetime]:
        """Calculate next run time for cron expression."""
        if not cron_expression:
            return None
        
        try:
            from croniter import croniter
            # croniter handles timezone-aware datetimes
            iter = croniter(cron_expression, from_time)
            return iter.get_next(datetime)
        except ImportError:
            # Fallback if croniter not available
            return None
    
    async def _scheduler_loop(self) -> None:
        """Main scheduler loop."""
        while self._running:
            try:
                await self._check_and_execute_jobs()
            except asyncio.CancelledError:
                break
            except Exception as e:
                # Log error but continue
                pass
            
            await asyncio.sleep(10)  # Check every 10 seconds
    
    async def _check_and_execute_jobs(self) -> None:
        """Check for due jobs and execute them."""
        now = datetime.now(timezone.utc)
        
        # Find jobs that are due
        result = await self.db.execute(
            select(ScheduledJob).where(
                ScheduledJob.status == ScheduleStatus.ACTIVE,
                ScheduledJob.next_run_at.is_not(None),
                ScheduledJob.next_run_at <= now,
            ).limit(100)
        )
        jobs = list(result.scalars().all())
        
        for job in jobs:
            # Check if we should run (concurrency control)
            running_count = await self._get_running_count(job.id)
            if running_count >= job.max_concurrent:
                continue
            
            # Execute job
            asyncio.create_task(self._execute_job(job))
    
    async def _get_running_count(self, job_id: uuid.UUID) -> int:
        """Get count of currently running executions for a job."""
        result = await self.db.execute(
            select(func.count(ScheduledJobRun.id)).where(
                ScheduledJobRun.job_id == job_id,
                ScheduledJobRun.status == ScheduleStatus.RUNNING,
            )
        )
        return result.scalar_one()


# Dependency - lazy import to avoid circular imports
async def get_scheduler_service(db: AsyncSession = Depends(lambda: _get_db())) -> SchedulerService:
    return SchedulerService(db)


# Import needed modules
import asyncio
import time
from datetime import timedelta
from sqlalchemy import func