import asyncio
import signal
import sys

import redis.asyncio as redis
import structlog

from worker.config import WorkerSettings
from worker.logging import configure_logging, get_logger
from worker.base import HealthCheckWorker

logger = get_logger("worker.main")


async def main() -> None:
    settings = WorkerSettings()
    configure_logging(settings)

    logger.info("Starting OpenAgent Worker", environment=settings.OPENAGENT_ENV)

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

    worker = HealthCheckWorker(settings, redis_client)

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


async def shutdown(worker: HealthCheckWorker, redis_client: redis.Redis) -> None:
    logger.info("Shutting down worker")
    await worker.stop()
    await redis_client.close()
    logger.info("Worker shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())