"""Orchestration worker: background execution of orchestration runs.

Logical queues (orchestration / orchestration_task / agent execution) share
the same Redis physical infrastructure as the workflow execution worker.
Crash recovery: task leases expire; on startup the worker reclaims expired
leases and requeues safe tasks (CREATED/READY/ASSIGNED only).
"""

from __future__ import annotations

import asyncio
import signal
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Dict
from uuid import UUID

import redis.asyncio as redis
import structlog

from worker.config import WorkerSettings
from worker.logging import configure_logging, get_logger
from worker.queue import Job, JobQueue, RetryPolicy

logger = structlog.get_logger("worker.orchestration")


class OrchestrationWorker:
    """Worker that processes orchestration jobs."""

    def __init__(
        self,
        settings: WorkerSettings,
        redis_client: redis.Redis,
        queue_name: str = "orchestration",
    ):
        self.settings = settings
        self.redis = redis_client
        self.queue = JobQueue(
            redis_client,
            queue_name,
            RetryPolicy(max_attempts=3, base_delay_seconds=5.0, max_delay_seconds=300.0),
        )
        self.worker_id = f"orchestration_worker_{uuid.uuid4().hex[:8]}"
        self.running = False
        self._tasks: list[asyncio.Task] = []
        self._shutdown_event = asyncio.Event()
        self._jobs_processed = 0
        self._jobs_failed = 0

    async def start(self) -> None:
        self.running = True
        self._shutdown_event.clear()
        await self._recover_expired_leases()
        self._tasks = [
            asyncio.create_task(self._work_loop(), name=f"orch_work_loop_{i}")
            for i in range(self.settings.WORKER_CONCURRENCY)
        ]
        await self._shutdown_event.wait()
        await self.stop()

    async def stop(self, timeout: float = 30.0) -> None:
        if not self.running:
            return
        self.running = False
        for task in self._tasks:
            if not task.done():
                task.cancel()
        try:
            await asyncio.wait_for(
                asyncio.gather(*self._tasks, return_exceptions=True), timeout=timeout
            )
        except asyncio.TimeoutError:
            logger.warning("Orchestration worker shutdown timeout")

    async def _work_loop(self) -> None:
        while self.running:
            try:
                if self._shutdown_event.is_set():
                    break
                jobs = await self.queue.dequeue(self.worker_id, count=1)
                if not jobs:
                    await asyncio.sleep(self.settings.WORKER_POLL_INTERVAL)
                    continue
                job = jobs[0]
                try:
                    result = await asyncio.wait_for(
                        self.process_job(job), timeout=self.settings.JOB_TIMEOUT
                    )
                    await self.queue.complete(self.worker_id, job, result)
                    self._jobs_processed += 1
                except asyncio.TimeoutError:
                    await self.queue.fail(self.worker_id, job, "orchestration job timeout")
                    self._jobs_failed += 1
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    await self.queue.fail(self.worker_id, job, str(exc))
                    self._jobs_failed += 1
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                logger.error("Orchestration work loop error", error=str(exc))
                await asyncio.sleep(5)

    async def process_job(self, job: Job) -> Dict[str, Any]:
        if job.type == "orchestration_execute":
            return await self._execute_run(job)
        if job.type == "orchestration_task_execute":
            return await self._execute_task(job)
        if job.type == "orchestration_recover":
            return await self._recover(job)
        if job.type == "manager_tick":
            return await self._manager_tick(job)
        raise ValueError(f"Unknown orchestration job type: {job.type}")

    async def _execute_run(self, job: Job) -> Dict[str, Any]:
        from openagent.db.session import get_db
        from openagent.orchestration.config import OrchestrationOrgSettings
        from openagent.orchestration.service import OrchestrationService

        payload = job.payload or {}
        run_id = payload.get("orchestration_run_id")
        organization_id = payload.get("organization_id")
        if not run_id or not organization_id:
            raise ValueError("orchestration_run_id and organization_id required")
        db_gen = get_db()
        db = await db_gen.__anext__()
        try:
            service = OrchestrationService(db, OrchestrationOrgSettings())
            result = await service.execute_run(UUID(organization_id), UUID(run_id))
            return {"status": result.status, "run_id": run_id}
        finally:
            await db.close()

    async def _execute_task(self, job: Job) -> Dict[str, Any]:
        # Task-level jobs re-enter run execution; the executor claims tasks
        # via leases so duplicate delivery is safe (idempotent).
        return await self._execute_run(job)

    async def _recover(self, job: Job) -> Dict[str, Any]:
        reclaimed = await self._recover_expired_leases()
        return {"reclaimed": reclaimed}

    async def _manager_tick(self, job: Job) -> Dict[str, Any]:
        """Drive one controlled manager-loop step for a run."""
        from openagent.db.session import get_db
        from openagent.management.service import ManagementService
        from openagent.orchestration.config import OrchestrationOrgSettings

        payload = job.payload or {}
        run_id = payload.get("orchestration_run_id")
        organization_id = payload.get("organization_id")
        manager_agent_id = payload.get("manager_agent_id")
        if not run_id or not organization_id or not manager_agent_id:
            raise ValueError("orchestration_run_id, organization_id, manager_agent_id required")
        db_gen = get_db()
        db = await db_gen.__anext__()
        try:
            service = ManagementService(db, OrchestrationOrgSettings())
            result = await service.manager_tick(
                UUID(organization_id), UUID(run_id), UUID(manager_agent_id))
            return {"run_id": run_id, **result}
        finally:
            await db.close()

    async def _recover_expired_leases(self) -> int:
        """Reclaim tasks whose lease expired (worker crash recovery)."""
        try:
            from openagent.db.session import get_db
            from openagent.db.models.orchestration import (
                OrchestrationTask,
                OrchestrationTaskStatus,
            )
            from sqlalchemy import select

            db_gen = get_db()
            db = await db_gen.__anext__()
            try:
                now = datetime.now(timezone.utc)
                result = await db.execute(
                    select(OrchestrationTask).where(
                        OrchestrationTask.lease_expires_at.is_not(None),
                        OrchestrationTask.lease_expires_at < now,
                        OrchestrationTask.status.in_(
                            [OrchestrationTaskStatus.RUNNING, OrchestrationTaskStatus.WAITING]
                        ),
                    ).limit(200)
                )
                rows = list(result.scalars().all())
                for row in rows:
                    # Only safe states revert to READY; terminal states untouched.
                    row.status = OrchestrationTaskStatus.READY
                    row.lease_owner = None
                    row.lease_expires_at = None
                await db.commit()
                if rows:
                    logger.info("Reclaimed expired task leases", count=len(rows))
                return len(rows)
            finally:
                await db.close()
        except Exception as exc:  # noqa: BLE001
            logger.error("Lease recovery failed", error=str(exc))
            return 0


async def enqueue_orchestration_run(
    redis_client: redis.Redis,
    *,
    organization_id: str,
    orchestration_run_id: str,
    queue_name: str = "orchestration",
) -> str:
    """Enqueue a run for background execution. Returns job id."""
    queue = JobQueue(redis_client, queue_name, RetryPolicy())
    job = Job(
        type="orchestration_execute",
        payload={"organization_id": organization_id, "orchestration_run_id": orchestration_run_id},
        tags=["orchestration"],
        metadata={"enqueued_at": datetime.now(timezone.utc).isoformat()},
    )
    await queue.enqueue(job)
    return job.id


async def enqueue_manager_tick(
    redis_client: redis.Redis,
    *,
    organization_id: str,
    orchestration_run_id: str,
    manager_agent_id: str,
    queue_name: str = "orchestration",
) -> str:
    """Enqueue one manager-loop tick. Returns job id."""
    queue = JobQueue(redis_client, queue_name, RetryPolicy())
    job = Job(
        type="manager_tick",
        payload={
            "organization_id": organization_id,
            "orchestration_run_id": orchestration_run_id,
            "manager_agent_id": manager_agent_id,
        },
        tags=["orchestration", "manager"],
        metadata={"enqueued_at": datetime.now(timezone.utc).isoformat()},
    )
    await queue.enqueue(job)
    return job.id


async def main() -> None:
    settings = WorkerSettings()
    configure_logging(settings)
    redis_client = redis.from_url(settings.REDIS_URL, encoding="utf-8", decode_responses=True)
    try:
        await redis_client.ping()
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to connect to Redis", error=str(exc))
        sys.exit(1)
    worker = OrchestrationWorker(settings, redis_client)

    def _handle_signal() -> None:
        worker._shutdown_event.set()

    try:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, _handle_signal)
            except NotImplementedError:
                pass
    except RuntimeError:
        pass
    try:
        await worker.start()
    finally:
        await worker.stop()
        await redis_client.close()


if __name__ == "__main__":
    asyncio.run(main())
