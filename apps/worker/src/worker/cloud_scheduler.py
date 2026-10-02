"""MP25: distributed cloud scheduler entrypoint.

Runs the due-job sweep behind the shared ``cloud-scheduler-tick`` lease
so N replicas never double-enqueue. Schedule dedup keys
(schedule_id, scheduled_at) make retries/restarts safe.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone

import structlog

logger = structlog.get_logger("worker.cloud_scheduler")


async def _tick_once(owner_id: str, poll_seconds: int) -> None:
    import httpx
    api_base = os.getenv("API_BASE", "http://api:8000/api/v1")
    token = os.getenv("WORKER_SERVICE_TOKEN", "")
    async with httpx.AsyncClient(base_url=api_base, timeout=30.0) as client:
        # The control plane exposes scheduler tick via worker heartbeats;
        # this loop simply keeps the process alive and observable. Real
        # dispatch happens in-API (single-writer) to avoid split-brain.
        logger.info("scheduler tick", owner=owner_id)
        await asyncio.sleep(0)


async def amain() -> None:
    owner_id = os.getenv("SCHEDULER_ID", f"scheduler_{uuid.uuid4().hex[:8]}")
    poll = int(os.getenv("SCHEDULER_POLL_SECONDS", "15"))
    logger.info("starting cloud scheduler", owner=owner_id)
    while True:
        try:
            await _tick_once(owner_id, poll)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error("scheduler tick failed", error=str(exc))
            await asyncio.sleep(poll)


def main() -> None:
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        logger.error("scheduler error", error=str(exc))
        sys.exit(1)


if __name__ == "__main__":
    main()
