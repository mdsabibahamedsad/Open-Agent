import asyncio
import signal
import uuid
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Callable, Awaitable
from datetime import datetime, timezone
from contextlib import asynccontextmanager

import redis.asyncio as redis
import structlog

from worker.config import WorkerSettings
from worker.logging import configure_logging, get_logger
from worker.queue import Job, JobQueue, JobProcessor, JobStatus, RetryPolicy, BackoffStrategy

logger = get_logger("worker.base")


class BaseWorker(ABC):
    def __init__(
        self,
        settings: WorkerSettings,
        redis_client: redis.Redis,
        queue_name: str = "default",
        retry_policy: Optional[RetryPolicy] = None,
    ):
        self.settings = settings
        self.redis = redis_client
        self.queue = JobQueue(redis_client, queue_name, retry_policy)
        self.worker_id = f"worker_{uuid.uuid4().hex[:8]}"
        self.running = False
        self._tasks: List[asyncio.Task] = []
        self._shutdown_event = asyncio.Event()
        self._startup_time = datetime.now(timezone.utc)
        self._jobs_processed = 0
        self._jobs_failed = 0
        self._health_check_interval = 30
        
        # Register signal handlers
        self._register_signal_handlers()

    @abstractmethod
    async def process_job(self, job: Job) -> Dict[str, Any]:
        pass

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
        logger.info("Worker started", worker_id=self.worker_id, concurrency=self.settings.WORKER_CONCURRENCY)

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
        """Main work loop for processing jobs."""
        worker_id = self.worker_id
        
        while self.running:
            try:
                # Check if we should shut down
                if self._shutdown_event.is_set():
                    break
                
                jobs = await self.queue.dequeue(worker_id, count=1)
                if not jobs:
                    await asyncio.sleep(self.settings.WORKER_POLL_INTERVAL)
                    continue

                job = jobs[0]
                logger.info("Processing job", worker_id=worker_id, job_id=job.id, type=job.type, attempt=job.attempts)

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

    async def _health_check_loop(self) -> None:
        """Periodic health check and stats reporting."""
        while self.running:
            try:
                await asyncio.sleep(self._health_check_interval)
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
                await asyncio.sleep(10)  # Check every 10 seconds
                if not self.running:
                    break
                moved = await self.queue._move_scheduled_jobs()
                if moved > 0:
                    logger.debug("Moved scheduled jobs", worker_id=self.worker_id, count=moved)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Scheduled job mover error", worker_id=self.worker_id, error=str(e))

    def get_stats(self) -> Dict[str, Any]:
        """Get worker statistics."""
        return {
            "worker_id": self.worker_id,
            "running": self.running,
            "jobs_processed": self._jobs_processed,
            "jobs_failed": self._jobs_failed,
            "uptime_seconds": (datetime.now(timezone.utc) - self._startup_time).total_seconds(),
            "startup_time": self._startup_time.isoformat(),
        }


class HealthCheckWorker(BaseWorker):
    async def process_job(self, job: Job) -> Dict[str, Any]:
        job_type = job.type
        if job_type == "health_check":
            return {"status": "healthy", "worker_id": self.worker_id}
        return {"status": "unknown_job_type", "type": job_type}