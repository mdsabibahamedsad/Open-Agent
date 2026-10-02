import asyncio
from contextlib import asynccontextmanager

import redis.asyncio as redis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from openagent.api import v1_router
from openagent.core.config import get_settings
from openagent.core.logging import configure_logging, get_logger
from openagent.core.metrics import MetricsMiddleware
from openagent.core.security.headers import (
    RequestSizeLimitMiddleware,
    RequestTimeoutMiddleware,
    SecurityHeadersMiddleware,
)
from openagent.db.session import async_session_maker, close_db, init_db
from openagent.middleware import (
    ErrorHandlingMiddleware,
    RequestCorrelationMiddleware,
    register_error_handlers,
)

logger = get_logger("openagent.main")

# Minimum accepted secret length (matches Settings min_length=32).
MIN_SECRET_LENGTH = 32

# Bounds for the startup dependency probe (seconds). Short on purpose:
# startup must fail fast, never hang the deploy.
STARTUP_PROBE_TIMEOUT = 10
REDIS_PROBE_CONNECT_TIMEOUT = 5

_ENGINE_NOT_INITIALIZED = "database engine not initialized"


async def _probe_dependencies(fail_fast: bool) -> None:
    """Verify database + Redis reachability at startup.

    Production: raise RuntimeError (fail fast, never serve half-wired).
    Non-production: log a warning and continue so `pnpm dev` works
    before `pnpm infra:up`.
    """
    settings = get_settings()

    async def _probe_db() -> None:
        maker = async_session_maker
        if maker is None:
            raise RuntimeError(_ENGINE_NOT_INITIALIZED)
        async with maker() as session:
            await session.execute("SELECT 1")

    async def _probe_redis() -> None:
        client = redis.from_url(settings.REDIS_URL, socket_connect_timeout=REDIS_PROBE_CONNECT_TIMEOUT)
        try:
            await client.ping()
        finally:
            await client.close()

    for name, probe in (("database", _probe_db), ("redis", _probe_redis)):
        try:
            await asyncio.wait_for(probe(), timeout=STARTUP_PROBE_TIMEOUT)
            logger.info("Startup dependency reachable", dependency=name)
        except Exception as exc:
            message = f"Startup dependency unreachable: {name} ({exc})"
            if fail_fast:
                raise RuntimeError(message) from exc
            logger.warning(message)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    settings = get_settings()
    logger.info("Starting OpenAgent API", environment=settings.OPENAGENT_ENV)
    if settings.is_production:
        # Fail fast on missing/weak cryptographic configuration. (Pydantic
        # also enforces min_length, but this produces an actionable message.)
        for key in ("SECRET_KEY", "ENCRYPTION_KEY"):
            value = getattr(settings, key, "")
            if not value or len(value) < MIN_SECRET_LENGTH:
                message = (
                    f"Production startup blocked: {key} is missing or shorter "
                    f"than {MIN_SECRET_LENGTH} characters."
                )
                raise RuntimeError(message)
        for key in ("DATABASE_URL", "REDIS_URL"):
            if not getattr(settings, key, ""):
                message = f"Production startup blocked: {key} is missing."
                raise RuntimeError(message)
        # MP19: refuse silently-insecure approval configuration in production.
        from openagent.approvals.config import ApprovalSettings
        problems = ApprovalSettings().validate_production()
        if problems:
            raise RuntimeError("Insecure approval configuration: " + "; ".join(problems))
        # MP20: refuse silently-unsafe evaluator configuration in production.
        from openagent.evaluator.config import EvaluatorSettings
        eval_problems = EvaluatorSettings().validate_production()
        if eval_problems:
            raise RuntimeError("Insecure evaluator configuration: " + "; ".join(eval_problems))
        # MP21: refuse silently-unsafe connector configuration in production.
        from openagent.connectors.config import ConnectorSettings
        connector_problems = ConnectorSettings().validate_production()
        if connector_problems:
            raise RuntimeError("Insecure connector configuration: " + "; ".join(connector_problems))
        # MP22: refuse excessive package asset limits in production.
        from openagent.packages.config import get_package_settings
        package_problems = get_package_settings().validate_production()
        if package_problems:
            raise RuntimeError("Insecure packages configuration: " + "; ".join(package_problems))
        # MP24: live billing requires explicit provider + webhook secret.
        from openagent.commerce.config import get_commerce_settings
        commerce_problems = get_commerce_settings().validate_production()
        if commerce_problems:
            raise RuntimeError("Insecure commerce configuration: " + "; ".join(commerce_problems))
        # MP25: cloud runtime safety (autoscale bounds, heartbeat TTL, mode).
        from openagent.cloud.config import get_cloud_settings
        cloud_problems = get_cloud_settings().validate_production()
        if cloud_problems:
            raise RuntimeError("Insecure cloud configuration: " + "; ".join(cloud_problems))
    # MP21: register official connector definitions (lazy manifests stay lazy).
    from openagent.connectors.providers import provider_ids, register_official
    if not provider_ids():
        register_official()
    init_db()
    logger.info("Database initialized")
    # Fail fast in production when dependencies are unreachable; warn in dev.
    await _probe_dependencies(fail_fast=settings.is_production)
    yield
    logger.info("Shutting down OpenAgent API")
    await close_db()
    logger.info("Database connections closed")


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging()

    app = FastAPI(
        title="OpenAgent API",
        description="AI Workforce Operating System",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.is_development else None,
        redoc_url="/redoc" if settings.is_development else None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Security middleware (order matters - first added = outermost)
    app.add_middleware(RequestTimeoutMiddleware, timeout=60.0)
    app.add_middleware(RequestSizeLimitMiddleware, max_size=50 * 1024 * 1024)  # 50MB
    app.add_middleware(SecurityHeadersMiddleware)

    app.add_middleware(RequestCorrelationMiddleware)
    app.add_middleware(ErrorHandlingMiddleware, is_development=settings.is_development)

    # Standard ApiError envelope for errors raised in routes (FastAPI's
    # internal exception middleware would otherwise bypass user
    # middleware and return plain {"detail": ...} without request_id).
    register_error_handlers(app, is_development=settings.is_development)

    # In-memory request metrics (http_requests_total,
    # http_request_duration_seconds). Surfaced as JSON via
    # GET /api/v1/operations/metrics; paths are cardinality-normalized.
    app.add_middleware(MetricsMiddleware)

    app.include_router(v1_router, prefix="/api/v1")

    @app.get("/api/v1", include_in_schema=False)
    async def api_root():
        return {"name": "OpenAgent API", "version": "0.1.0", "docs": "/docs"}

    return app


app = create_app()