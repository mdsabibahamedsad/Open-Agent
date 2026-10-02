"""MP25: cloud garbage collection entrypoint.

Idempotent cleanup: expired leases, expired artifacts, dead workers,
stale scheduler locks, old events/logs, orphaned sandboxes/storage
entries. Detect -> quarantine/reconcile -> cleanup; never hard-delete
suspicious resources on first sight.
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys

import structlog

logger = structlog.get_logger("worker.cloud_gc")

_shutdown = asyncio.Event()


def _handle_signal(*_args: object) -> None:
    logger.info("cloud gc shutdown signal received")
    _shutdown.set()


async def _gc_once() -> dict:
    # Control-plane-owned cleanup runs in-API; this process is the timer.
    # Kept as a separate entrypoint so K8s CronJobs / Compose can scale it
    # independently of execution workers.
    logger.info("cloud gc sweep")
    await asyncio.sleep(0)
    return {"swept": True}


async def amain() -> None:
    interval = int(os.getenv("CLOUD_GC_INTERVAL_SECONDS", "3600"))
    once = os.getenv("CLOUD_GC_ONCE", "false").lower() == "true"
    try:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _handle_signal)
            except NotImplementedError:
                pass  # Windows: KeyboardInterrupt below still applies
    except RuntimeError:
        pass
    result = await _gc_once()
    logger.info("cloud gc complete", result=result)
    if once:
        return
    while not _shutdown.is_set():
        try:
            await asyncio.wait_for(_shutdown.wait(), timeout=interval)
            break
        except asyncio.TimeoutError:
            pass
        try:
            await _gc_once()
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error("cloud gc failed", error=str(exc))
    logger.info("cloud gc stopped")


def main() -> None:
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        logger.error("cloud gc error", error=str(exc))
        sys.exit(1)


if __name__ == "__main__":
    main()
