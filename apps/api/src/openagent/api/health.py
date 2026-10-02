import redis.asyncio as redis
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from openagent.db.session import get_db
from openagent.schemas.base import HealthResponse, ReadyResponse
from openagent.core.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, status_code=status.HTTP_200_OK)
async def health_check() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="ok",
        service="openagent-api",
        environment=settings.OPENAGENT_ENV,
    )


@router.get("/health/ready", response_model=ReadyResponse, status_code=status.HTTP_200_OK)
async def readiness_check(db: AsyncSession = Depends(get_db)) -> ReadyResponse:
    settings = get_settings()
    checks = {}

    # Check database
    try:
        await db.execute("SELECT 1")
        checks["database"] = True
    except Exception:
        checks["database"] = False

    # Check Redis
    try:
        redis_client = redis.from_url(settings.REDIS_URL)
        await redis_client.ping()
        await redis_client.close()
        checks["redis"] = True
    except Exception:
        checks["redis"] = False

    # Overall status
    all_healthy = all(checks.values())
    degraded = any(not v for v in checks.values())

    return ReadyResponse(
        status="ok" if all_healthy else "degraded",
        service="openagent-api",
        checks=checks,
    )