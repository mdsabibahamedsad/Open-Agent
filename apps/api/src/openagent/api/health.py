import redis.asyncio as redis
from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.core.config import get_settings
from openagent.db.session import get_db
from openagent.schemas.base import HealthResponse, ReadyResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, status_code=status.HTTP_200_OK)
async def health_check() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="ok",
        service="openagent-api",
        environment=settings.OPENAGENT_ENV,
    )


@router.get(
    "/health/ready",
    response_model=ReadyResponse,
    status_code=status.HTTP_200_OK,
    responses={503: {"description": "Degraded: a dependency check failed"}},
)
async def readiness_check(db: AsyncSession = Depends(get_db)):
    """Readiness distinguishes healthy (200) from degraded (503).

    Load balancers / orchestrators must NOT route traffic to a degraded
    instance; returning 200 unconditionally hid database/Redis outages.
    The body shape is unchanged so existing consumers keep parsing it.
    """
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

    body = ReadyResponse(
        status="ok" if all_healthy else "degraded",
        service="openagent-api",
        checks=checks,
    )
    if all_healthy:
        return body
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content=body.model_dump(),
    )
