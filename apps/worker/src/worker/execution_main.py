"""Workflow execution worker."""

from __future__ import annotations

import asyncio
import signal
import sys
import uuid
from datetime import datetime, timezone

import redis.asyncio as redis
import structlog

from openagent.runtime.core import (
    ExecutionRuntime,
    initialize_runtime,
    get_runtime,
)
from openagent.runtime.engine import expression_engine
from openagent.worker.config import WorkerSettings
from openagent.worker.logging import configure_logging, get_logger
from openagent.worker.queue import Job, JobQueue, JobProcessor, JobStatus, RetryPolicy
from openagent.db.session import get_db
from openagent.db.models import WorkflowExecution, WorkflowExecutionStatus
from openagent.db.session import get_db
from openagent.runtime.models import WorkflowExecutionStatus

logger = structlog.get_logger("worker.execution")


class ExecutionWorker:
    """Worker that processes workflow execution jobs."""
    
    def __init__(
        self,
        settings: WorkerSettings,
        redis_client: redis.Redis,
        queue_name: str = "workflow_execution",
    ):
        self.settings = settings
        self.redis = redis_client
        self.queue = JobQueue(redis_client, queue_name, RetryPolicy(
            max_attempts=3,
            base_delay_seconds=5.0,
            max_delay_seconds=300.0,
        ))
        self.worker_id = f"execution_worker_{uuid.uuid4().hex[:8]}"
        self.running = False
        self._tasks: list[asyncio.Task] = []
        self._shutdown_event = asyncio.Event()
        self._startup_time = datetime.now(timezone.utc)
        self._jobs_processed = 0
        self._jobs_failed = 0
        
        self._register_signal_handlers()
    
    def _register_signal_handlers(self) -> None:
        """Register signal handlers for graceful shutdown."""
        try:
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGTERM, signal.SIGINT):
                loop.add_signal_handler(sig, self._shutdown_signal_handler)
        except NotImplementedError:
            # Not supported on Windows
            pass
    
    def _shutdown_signal_handler(self) -> None:
        logger.info("Shutdown signal received", worker_id=self.worker_id)
        self._shutdown_event.set()
    
    async def start(self) -> None:
        self.running = True
        self._shutdown_event.clear()
        logger.info("Execution worker started", worker_id=self.worker_id, concurrency=self.settings.WORKER_CONCURRENCY)
        
        # Start background tasks
        self._tasks = [
            asyncio.create_task(self._work_loop(), name=f"work_loop_{i}")
            for i in range(self.settings.WORKER_CONCURRENCY)
        ]
        
        # Start health check task
        self._tasks.append(asyncio.create_task(self._health_check_loop(), name="health_check"))
        
        # Start scheduled job mover
        self._tasks.append(asyncio.create_task(self._scheduled_job_mover(), name="scheduled_mover"))
        
        # Wait for shutdown
        await self._shutdown_event.wait()
        await self.stop()
    
    async def stop(self, timeout: float = 30.0) -> None:
        if not self.running:
            return
        
        self.running = False
        logger.info("Worker stopping", worker_id=self.worker_id)
        
        # Cancel all tasks
        for task in self._tasks:
            if not task.done():
                task.cancel()
        
        # Wait for tasks to complete with timeout
        try:
            await asyncio.wait_for(
                asyncio.gather(*self._tasks, return_exceptions=True),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            logger.warning("Worker shutdown timeout, forcing exit", worker_id=self.worker_id)
        
        logger.info(
            "Worker stopped",
            worker_id=self.worker_id,
            jobs_processed=self._jobs_processed,
            jobs_failed=self._jobs_failed,
            uptime_seconds=(datetime.now(timezone.utc) - self._startup_time).total_seconds(),
        )
    
    async def _work_loop(self) -> None:
        """Main work loop for processing execution jobs."""
        worker_id = self.worker_id
        
        while self.running:
            try:
                if self._shutdown_event.is_set():
                    break
                
                jobs = await self.queue.dequeue(worker_id, count=1)
                if not jobs:
                    await asyncio.sleep(self.settings.WORKER_POLL_INTERVAL)
                    continue
                
                job = jobs[0]
                logger.info("Processing execution job", worker_id=worker_id, job_id=job.id, type=job.type)
                
                try:
                    # Apply timeout
                    result = await asyncio.wait_for(
                        self.process_job(job),
                        timeout=self.settings.JOB_TIMEOUT,
                    )
                    await self.queue.complete(worker_id, job, result)
                    self._jobs_processed += 1
                except asyncio.TimeoutError:
                    await self.queue.fail(worker_id, job, f"Job timeout after {self.settings.JOB_TIMEOUT}s")
                    self._jobs_failed += 1
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    await self.queue.fail(worker_id, job, str(e))
                    self._jobs_failed += 1
            
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Work loop error", worker_id=worker_id, error=str(e))
                await asyncio.sleep(5)
    
    async def process_job(self, job: Job) -> Dict[str, Any]:
        """Process an execution job."""
        job_type = job.type
        
        if job_type == "workflow_execute":
            return await self._execute_workflow(job)
        elif job_type == "workflow_cancel":
            return await self._cancel_execution(job)
        elif job_type == "workflow_retry":
            return await self._retry_execution(job)
        elif job_type == "workflow_resume":
            return await self._resume_execution(job)
        else:
            raise ValueError(f"Unknown job type: {job_type}")
    
    async def _execute_workflow(self, job: Job) -> Dict[str, Any]:
        """Execute a workflow."""
        payload = job.payload
        workflow_id = payload.get("workflow_id")
        organization_id = payload.get("organization_id")
        version = payload.get("version")
        trigger_input = payload.get("input", {})
        
        if not workflow_id or not organization_id:
            raise ValueError("workflow_id and organization_id required")
        
        # Get database session
        db = next(get_db())
        try:
            # Create execution runtime
            runtime = ExecutionRuntime(db)
            
            # Create execution
            execution_id = await runtime.create_execution(
                workflow_id=workflow_id,
                organization_id=organization_id,
                trigger_input={},
            )
            
            # Start execution
            await runtime.start_execution(execution_id)
            
            return {"execution_id": execution_id, "status": "started"}
        finally:
            await db.close()
    
    async def _cancel_execution(self, job: Job) -> Dict[str, Any]:
        """Cancel a running execution."""
        payload = job.payload
        execution_id = payload.get("execution_id")
        
        if not execution_id:
            raise ValueError("execution_id required")
        
        db = next(get_db())
        try:
            # Get execution
            result = await db.execute(
                select(WorkflowExecution).where(WorkflowExecution.id == execution_id)
            )
            execution = result.scalar_one_or_none()
            
            if not execution:
                raise ValueError(f"Execution {execution_id} not found")
            
            if execution.status not in [WorkflowExecutionStatus.QUEUED, WorkflowExecutionStatus.RUNNING, WorkflowExecutionStatus.WAITING, WorkflowExecutionStatus.PAUSED]:
                return {"status": "already_terminal", "current_status": execution.status.value}
            
            execution.status = WorkflowExecutionStatus.CANCELLED
            execution.completed_at = datetime.now(timezone.utc)
            await db.commit()
            
            return {"status": "cancelled", "execution_id": execution_id}
        finally:
            await db.close()
    
    async def _retry_execution(self, job: Job) -> Dict[str, Any]:
        """Retry a failed execution."""
        payload = job.payload
        execution_id = payload.get("execution_id")
        
        if not execution_id:
            raise ValueError("execution_id required")
        
        db = next(get_db())
        try:
            result = await db.execute(
                select(WorkflowExecution).where(WorkflowExecution.id == execution_id)
            )
            execution = result.scalar_one_or_none()
            
            if not execution:
                raise ValueError(f"Execution {execution_id} not found")
            
            if execution.status not in [WorkflowExecutionStatus.FAILED, WorkflowExecutionStatus.CANCELLED, WorkflowExecutionStatus.TIMED_OUT]:
                return {"status": "not_retryable", "current_status": execution.status.value}
            
            # Reset execution to queued
            execution.status = WorkflowExecutionStatus.QUEUED
            execution.error_message = None
            execution.error_code = None
            execution.completed_at = None
            execution.started_at = None
            
            await db.commit()
            
            return {"status": "retry_queued", "execution_id": execution_id}
        finally:
            await db.close()
    
    async def _resume_execution(self, job: Job) -> Dict[str, Any]:
        """Resume a paused/waiting execution."""
        payload = job.payload
        execution_id = payload.get("execution_id")
        resume_token = payload.get("resume_token")
        
        if not execution_id:
            raise ValueError("execution_id required")
        
        # In a full implementation, this would:
        # 1. Validate the resume token
        # 2. Find the waiting node
        # 3. Resume execution from that point
        
        return {"status": "resume_not_implemented", "execution_id": execution_id}
    
    async def _health_check_loop(self) -> None:
        """Periodic health check and stats reporting."""
        while self.running:
            try:
                await asyncio.sleep(30)
                if not self.running:
                    break
                
                stats = await self.queue.get_queue_stats()
                logger.info(
                    "Worker health check",
                    worker_id=self.worker_id,
                    jobs_processed=self._jobs_processed,
                    jobs_failed=self._jobs_failed,
                    queue_stats=stats,
                    uptime_seconds=(datetime.now(timezone.utc) - self._startup_time).total_seconds(),
                )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Health check error", worker_id=self.worker_id, error=str(e))
    
    async def _scheduled_job_mover(self) -> None:
        """Move scheduled jobs to main queue when due."""
        while self.running:
            try:
                await asyncio.sleep(10)
                if not self.running:
                    break
                moved = await self.queue._move_scheduled_jobs()
                if moved > 0:
                    logger.debug("Moved scheduled jobs", worker_id=self.worker_id, count=moved)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Scheduled job mover error", worker_id=self.worker_id, error=str(e))


async def main() -> None:
    settings = WorkerSettings()
    configure_logging(settings)
    
    logger.info("Starting OpenAgent Execution Worker", environment=settings.OPENAGENT_ENV)
    
    redis_client = redis.from_url(
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
    )
    
    try:
        await redis_client.ping()
        logger.info("Redis connected")
    except Exception as e:
        logger.error("Failed to connect to Redis", error=str(e))
        sys.exit(1)
    
    worker = ExecutionWorker(settings, redis_client)
    
    loop = asyncio.get_running_loop()
    
    def signal_handler() -> None:
        logger.info("Shutdown signal received")
        asyncio.create_task(shutdown(worker, redis_client))
    
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, signal_handler)
        except NotImplementedError:
            pass
    
    try:
        await worker.start()
    except Exception as e:
        logger.error("Worker error", error=str(e))
        sys.exit(1)
    finally:
        await shutdown(worker, redis_client)


async def shutdown(worker: 'ExecutionWorker', redis_client: redis.Redis) -> None:
    logger.info("Shutting down worker")
    await worker.stop()
    await redis_client.close()
    logger.info("Worker shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())