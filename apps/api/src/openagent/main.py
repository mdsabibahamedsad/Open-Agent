from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from openagent.core.config import get_settings
from openagent.core.logging import configure_logging, get_logger
from openagent.core.security.headers import SecurityHeadersMiddleware, RequestSizeLimitMiddleware, RequestTimeoutMiddleware
from openagent.middleware import RequestCorrelationMiddleware, ErrorHandlingMiddleware
from openagent.api import v1_router
from openagent.db.session import init_db, close_db


logger = get_logger("openagent.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    settings = get_settings()
    logger.info("Starting OpenAgent API", environment=settings.OPENAGENT_ENV)
    if settings.is_production:
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

    app.include_router(v1_router, prefix="/api/v1")

    @app.get("/api/v1", include_in_schema=False)
    async def api_root():
        return {"name": "OpenAgent API", "version": "0.1.0", "docs": "/docs"}

    return app


app = create_app()