import json
import uuid
import time
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Generic, List, Optional, TypeVar, Callable, Awaitable
import redis.asyncio as redis
import structlog

from worker.logging import get_logger

logger = get_logger("worker.queue")

T = TypeVar("T")


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RETRYING = "retrying"
    DEAD_LETTER = "dead_letter"
    SCHEDULED = "scheduled"


class BackoffStrategy(str, Enum):
    FIXED = "fixed"
    EXPONENTIAL = "exponential"
    EXPONENTIAL_JITTER = "exponential_jitter"
    LINEAR = "linear"


@dataclass
class RetryPolicy:
    max_attempts: int = 3
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 300.0
    strategy: BackoffStrategy = BackoffStrategy.EXPONENTIAL_JITTER
    retryable_exceptions: tuple = (Exception,)


@dataclass
class Job(Generic[T]):
    id: str = field(default_factory=lambda: f"job_{uuid.uuid4().hex[:16]}")
    type: str = ""
    payload: T = None
    status: JobStatus = JobStatus.QUEUED
    priority: int = 0
    attempts: int = 0
    max_attempts: int = 3
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    next_retry_at: Optional[datetime] = None
    error: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    retry_policy: Optional[RetryPolicy] = None
    scheduled_at: Optional[datetime] = None
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "payload": self.payload,
            "status": self.status.value,
            "priority": self.priority,
            "attempts": self.attempts,
            "max_attempts": self.max_attempts,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "next_retry_at": self.next_retry_at.isoformat() if self.next_retry_at else None,
            "error": self.error,
            "result": self.result,
            "retry_policy": self.retry_policy.__dict__ if self.retry_policy else None,
            "scheduled_at": self.scheduled_at.isoformat() if self.scheduled_at else None,
            "tags": self.tags,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Job":
        retry_policy_data = data.get("retry_policy")
        retry_policy = None
        if retry_policy_data:
            retry_policy = RetryPolicy(
                max_attempts=retry_policy_data.get("max_attempts", 3),
                base_delay_seconds=retry_policy_data.get("base_delay_seconds", 1.0),
                max_delay_seconds=retry_policy_data.get("max_delay_seconds", 300.0),
                strategy=BackoffStrategy(retry_policy_data.get("strategy", "exponential_jitter")),
            )
        
        job = cls(
            id=data["id"],
            type=data["type"],
            payload=data["payload"],
            status=JobStatus(data["status"]),
            priority=data.get("priority", 0),
            attempts=data.get("attempts", 0),
            max_attempts=data.get("max_attempts", 3),
            retry_policy=retry_policy,
            scheduled_at=datetime.fromisoformat(data["scheduled_at"]) if data.get("scheduled_at") else None,
            tags=data.get("tags", []),
            metadata=data.get("metadata", {}),
        )
        job.created_at = datetime.fromisoformat(data["created_at"])
        if data.get("started_at"):
            job.started_at = datetime.fromisoformat(data["started_at"])
        if data.get("completed_at"):
            job.completed_at = datetime.fromisoformat(data["completed_at"])
        if data.get("next_retry_at"):
            job.next_retry_at = datetime.fromisoformat(data["next_retry_at"])
        job.error = data.get("error")
        job.result = data.get("result")
        return job

    def calculate_next_retry_delay(self) -> float:
        """Calculate delay before next retry based on retry policy."""
        if not self.retry_policy:
            return 1.0
        
        policy = self.retry_policy
        attempt = self.attempts
        
        if policy.strategy == BackoffStrategy.FIXED:
            delay = policy.base_delay_seconds
        elif policy.strategy == BackoffStrategy.LINEAR:
            delay = policy.base_delay_seconds * attempt
        elif policy.strategy == BackoffStrategy.EXPONENTIAL:
            delay = policy.base_delay_seconds * (2 ** (attempt - 1))
        elif policy.strategy == BackoffStrategy.EXPONENTIAL_JITTER:
            base_delay = policy.base_delay_seconds * (2 ** (attempt - 1))
            delay = base_delay * (0.5 + random.random())  # Add jitter
        else:
            delay = policy.base_delay_seconds
        
        return min(delay, policy.max_delay_seconds)

    def should_retry(self) -> bool:
        """Check if job should be retried."""
        if not self.retry_policy:
            return self.attempts < self.max_attempts
        return self.attempts < self.retry_policy.max_attempts


class DeadLetterEntry:
    """Entry in the dead letter queue."""
    
    def __init__(
        self,
        job: Job,
        error: str,
        failed_at: datetime,
        worker_id: str,
    ):
        self.job = job
        self.error = error
        self.failed_at = failed_at
        self.worker_id = worker_id
        self.id = f"dlq_{uuid.uuid4().hex[:16]}"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "job": self.job.to_dict(),
            "error": self.error,
            "failed_at": self.failed_at.isoformat(),
            "worker_id": self.worker_id,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DeadLetterEntry":
        entry = cls(
            job=Job.from_dict(data["job"]),
            error=data["error"],
            failed_at=datetime.fromisoformat(data["failed_at"]),
            worker_id=data["worker_id"],
        )
        entry.id = data["id"]
        return entry


class JobQueue:
    def __init__(
        self,
        redis_client: redis.Redis,
        queue_name: str = "default",
        default_retry_policy: Optional[RetryPolicy] = None,
    ):
        self.redis = redis_client
        self.queue_name = queue_name
        self.processing_key = f"{queue_name}:processing"
        self.dead_letter_key = f"{queue_name}:dead_letter"
        self.scheduled_key = f"{queue_name}:scheduled"
        self.default_retry_policy = default_retry_policy or RetryPolicy()

    async def enqueue(self, job: Job) -> str:
        """Enqueue a job."""
        if job.scheduled_at and job.scheduled_at > datetime.now(timezone.utc):
            # Schedule for later
            job.status = JobStatus.SCHEDULED
            job_data = json.dumps(job.to_dict())
            await self.redis.zadd(
                self.scheduled_key,
                {job_data: job.scheduled_at.timestamp()}
            )
        else:
            job_data = json.dumps(job.to_dict())
            await self.redis.zadd(self.queue_name, {job_data: -job.priority})
        logger.info("Job enqueued", job_id=job.id, type=job.type, status=job.status.value)
        return job.id

    async def enqueue_batch(self, jobs: List[Job]) -> List[str]:
        """Enqueue multiple jobs in a pipeline."""
        pipe = self.redis.pipeline()
        job_ids = []
        for job in jobs:
            if job.scheduled_at and job.scheduled_at > datetime.now(timezone.utc):
                job.status = JobStatus.SCHEDULED
                job_data = json.dumps(job.to_dict())
                pipe.zadd(self.scheduled_key, {job_data: job.scheduled_at.timestamp()})
            else:
                job_data = json.dumps(job.to_dict())
                pipe.zadd(self.queue_name, {job_data: -job.priority})
            job_ids.append(job.id)
        await pipe.execute()
        return job_ids

    async def dequeue(self, worker_id: str, count: int = 1) -> List[Job]:
        """Dequeue jobs for processing."""
        jobs = []
        now = datetime.now(timezone.utc)
        
        # First, move any due scheduled jobs to the main queue
        await self._move_scheduled_jobs()
        
        for _ in range(count):
            result = await self.redis.zpopmin(self.queue_name, count=1)
            if not result:
                break
            job_data, score = result[0]
            job = Job.from_dict(json.loads(job_data))
            job.status = JobStatus.RUNNING
            job.started_at = datetime.now(timezone.utc)
            job.attempts += 1
            await self.redis.hset(self.processing_key, worker_id, json.dumps(job.to_dict()))
            jobs.append(job)
        return jobs

    async def _move_scheduled_jobs(self) -> int:
        """Move due scheduled jobs to the main queue."""
        now = datetime.now(timezone.utc).timestamp()
        moved = 0
        
        while True:
            result = await self.redis.zpopmin(self.scheduled_key, count=1)
            if not result:
                break
            job_data, score = result[0]
            if score > now:
                # Put it back, not due yet
                await self.redis.zadd(self.scheduled_key, {job_data: score})
                break
            
            job = Job.from_dict(json.loads(job_data))
            job.status = JobStatus.QUEUED
            job_data = json.dumps(job.to_dict())
            await self.redis.zadd(self.queue_name, {job_data: -job.priority})
            moved += 1
        
        return moved

    async def complete(self, worker_id: str, job: Job, result: Dict[str, Any]) -> None:
        """Mark job as completed."""
        job.status = JobStatus.COMPLETED
        job.completed_at = datetime.now(timezone.utc)
        job.result = result
        await self.redis.hdel(self.processing_key, worker_id)
        logger.info("Job completed", job_id=job.id, type=job.type, duration_seconds=(
            job.completed_at - job.started_at
        ).total_seconds() if job.started_at else None)

    async def fail(self, worker_id: str, job: Job, error: str) -> None:
        """Handle job failure with retry logic."""
        job.error = error
        
        if job.should_retry():
            # Schedule retry
            job.status = JobStatus.RETRYING
            delay = job.calculate_next_retry_delay()
            job.next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
            
            await self.redis.hdel(self.processing_key, worker_id)
            
            # Re-enqueue with delay
            job_data = json.dumps(job.to_dict())
            await self.redis.zadd(
                self.queue_name,
                {job_data: -(job.priority + 1000)}  # Slightly higher priority for retries
            )
            logger.warning(
                "Job retrying",
                job_id=job.id,
                attempt=job.attempts,
                max_attempts=job.max_attempts,
                delay_seconds=delay,
                error=error,
            )
        else:
            # Max attempts reached - move to dead letter
            job.status = JobStatus.DEAD_LETTER
            job.completed_at = datetime.now(timezone.utc)
            await self.redis.hdel(self.processing_key, worker_id)
            
            dlq_entry = DeadLetterEntry(
                job=job,
                error=error,
                failed_at=datetime.now(timezone.utc),
                worker_id=worker_id,
            )
            await self.redis.lpush(self.dead_letter_key, json.dumps(dlq_entry.to_dict()))
            logger.error(
                "Job failed permanently, moved to dead letter",
                job_id=job.id,
                error=error,
                attempts=job.attempts,
            )

    async def cancel(self, job_id: str) -> bool:
        """Cancel a queued job."""
        # Check main queue
        jobs = await self.redis.zrange(self.queue_name, 0, -1)
        for job_data in jobs:
            job = Job.from_dict(json.loads(job_data))
            if job.id == job_id:
                await self.redis.zrem(self.queue_name, job_data)
                return True
        
        # Check scheduled queue
        jobs = await self.redis.zrange(self.scheduled_key, 0, -1)
        for job_data in jobs:
            job = Job.from_dict(json.loads(job_data))
            if job.id == job_id:
                await self.redis.zrem(self.scheduled_key, job_data)
                return True
        
        return False

    async def requeue_dead_letter(self, dlq_id: str) -> bool:
        """Requeue a job from the dead letter queue."""
        dlq_entries = await self.redis.lrange(self.dead_letter_key, 0, -1)
        for entry_data in dlq_entries:
            entry = DeadLetterEntry.from_dict(json.loads(entry_data))
            if entry.id == dlq_id:
                # Reset job for retry
                entry.job.status = JobStatus.QUEUED
                entry.job.attempts = 0
                entry.job.error = None
                entry.job.next_retry_at = None
                entry.job.completed_at = None
                
                await self.redis.lrem(self.dead_letter_key, 1, entry_data)
                await self.enqueue(entry.job)
                return True
        return False

    async def get_job_status(self, job_id: str) -> Optional[Job]:
        """Get job status from any queue."""
        for key in [self.queue_name, self.processing_key, self.scheduled_key, self.dead_letter_key]:
            if key == self.queue_name or key == self.scheduled_key:
                jobs = await self.redis.zrange(key, 0, -1)
                for job_data in jobs:
                    job = Job.from_dict(json.loads(job_data))
                    if job.id == job_id:
                        return job
            elif key == self.processing_key:
                jobs = await self.redis.hgetall(key)
                for job_data in jobs.values():
                    job = Job.from_dict(json.loads(job_data))
                    if job.id == job_id:
                        return job
            else:
                jobs = await self.redis.lrange(key, 0, -1)
                for job_data in jobs:
                    job = Job.from_dict(json.loads(job_data))
                    if job.id == job_id:
                        return job
        return None

    async def get_queue_stats(self) -> Dict[str, int]:
        queued = await self.redis.zcard(self.queue_name)
        scheduled = await self.redis.zcard(self.scheduled_key)
        processing = await self.redis.hlen(self.processing_key)
        dead_letter = await self.redis.llen(self.dead_letter_key)
        return {
            "queued": queued,
            "scheduled": scheduled,
            "processing": processing,
            "dead_letter": dead_letter,
        }

    async def get_dead_letter_jobs(self, limit: int = 100) -> List[DeadLetterEntry]:
        """Get jobs from the dead letter queue."""
        entries = await self.redis.lrange(self.dead_letter_key, 0, limit - 1)
        return [DeadLetterEntry.from_dict(json.loads(e)) for e in entries]

    async def clear_dead_letter(self, older_than_days: int = 30) -> int:
        """Clear old entries from dead letter queue."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
        cleared = 0
        
        while True:
            entry_data = await self.redis.lpop(self.dead_letter_key)
            if not entry_data:
                break
            entry = DeadLetterEntry.from_dict(json.loads(entry_data))
            if entry.failed_at < cutoff:
                cleared += 1
            else:
                # Put it back
                await self.redis.rpush(self.dead_letter_key, json.dumps(entry.to_dict()))
                break
        
        return cleared

    async def requeue_all_dead_letter(self) -> int:
        """Requeue all jobs from dead letter queue."""
        requeued = 0
        while True:
            entry_data = await self.redis.lpop(self.dead_letter_key)
            if not entry_data:
                break
            entry = DeadLetterEntry.from_dict(json.loads(entry_data))
            entry.job.status = JobStatus.QUEUED
            entry.job.attempts = 0
            entry.job.error = None
            entry.job.next_retry_at = None
            entry.job.completed_at = None
            await self.enqueue(entry.job)
            requeued += 1
        return requeued


class JobProcessor:
    """Process jobs with middleware support."""
    
    def __init__(
        self,
        queue: JobQueue,
        handlers: Dict[str, Callable[[Job], Awaitable[Dict[str, Any]]]],
        middleware: Optional[List[Callable[[Job], Awaitable[None]]]] = None,
    ):
        self.queue = queue
        self.handlers = handlers
        self.middleware = middleware or []
        self.running = False
    
    async def process_job(self, job: Job) -> Dict[str, Any]:
        """Process a single job through middleware and handler."""
        # Run before middleware
        for mw in self.middleware:
            await mw(job)
        
        handler = self.handlers.get(job.type)
        if not handler:
            raise ValueError(f"No handler for job type: {job.type}")
        
        return await handler(job)
    
    def add_middleware(self, middleware: Callable[[Job], Awaitable[None]]) -> None:
        self.middleware.append(middleware)