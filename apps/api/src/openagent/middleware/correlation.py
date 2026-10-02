import time
import uuid
from typing import Callable

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = structlog.get_logger("openagent.middleware")


class RequestCorrelationMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request_id = request.headers.get("X-Request-ID", f"req_{uuid.uuid4().hex[:16]}")
        # Bind to both the logging context and request.state so the error
        # middleware renders the SAME id in ApiError bodies (previously it
        # generated a different fallback id on failures).
        request.state.request_id = request_id
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        start_time = time.time()
        logger.info("Request started", method=request.method, path=request.url.path)

        try:
            response = await call_next(request)
            process_time = time.time() - start_time
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Process-Time"] = str(process_time)
            logger.info("Request completed", status_code=response.status_code, duration=process_time)
            return response
        except Exception as e:
            process_time = time.time() - start_time
            logger.error("Request failed", error=str(e), duration=process_time)
            raise