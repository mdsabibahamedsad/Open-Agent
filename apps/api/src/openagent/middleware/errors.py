import uuid
from typing import Callable

import structlog
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from openagent.schemas.base import ApiError, ApiErrorResponse, ErrorDetail

logger = structlog.get_logger("openagent.errors")


ERROR_CODES = {
    "VALIDATION_ERROR": 422,
    "NOT_FOUND": 404,
    "UNAUTHORIZED": 401,
    "FORBIDDEN": 403,
    "INTERNAL_ERROR": 500,
    "CONFLICT": 409,
    "RATE_LIMITED": 429,
    "SERVICE_UNAVAILABLE": 503,
    "BAD_REQUEST": 400,
    "UNPROCESSABLE_ENTITY": 422,
}


def request_id_for(request: Request) -> str:
    """Single source of truth for the request id.

    The correlation middleware stamps request.state; fall back to the
    logging context, then to a fresh id (never reuse another request's).
    """
    state_id = getattr(request.state, "request_id", None)
    if state_id:
        return state_id
    try:
        ctx = structlog.contextvars.get_contextvars()
        if ctx.get("request_id"):
            return ctx["request_id"]
    except Exception:
        pass
    return f"req_{uuid.uuid4().hex[:16]}"


class ErrorHandlingMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, is_development: bool = False):
        super().__init__(app)
        self.is_development = is_development

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        try:
            return await call_next(request)
        except HTTPException as e:
            return self._handle_http_exception(request, e)
        except ValidationError as e:
            return self._handle_validation_error(request, e)
        except Exception as e:
            return self._handle_unexpected_error(request, e)

    def _handle_http_exception(self, request: Request, exc: HTTPException) -> JSONResponse:
        request_id = request_id_for(request)
        status_code = exc.status_code
        code = self._get_error_code(status_code)

        logger.warning(
            "HTTP exception",
            request_id=request_id,
            status_code=status_code,
            detail=exc.detail,
            path=request.url.path,
        )

        error = ApiError(
            code=code,
            message=str(exc.detail),
            request_id=request_id,
            status_code=status_code,
        )
        return JSONResponse(status_code=status_code, content=ApiErrorResponse(error=error).model_dump())

    def _handle_validation_error(self, request: Request, exc: ValidationError) -> JSONResponse:
        request_id = request_id_for(request)

        details = [
            ErrorDetail(field=".".join(str(x) for x in err["loc"]), code="VALIDATION_ERROR", message=err["msg"])
            for err in exc.errors()
        ]

        logger.warning("Validation error", request_id=request_id, details=details, path=request.url.path)

        error = ApiError(
            code="VALIDATION_ERROR",
            message="Invalid request",
            request_id=request_id,
            status_code=422,
            details=details,
        )
        return JSONResponse(status_code=422, content=ApiErrorResponse(error=error).model_dump())

    def _handle_unexpected_error(self, request: Request, exc: Exception) -> JSONResponse:
        request_id = request_id_for(request)

        logger.error(
            "Unexpected error",
            request_id=request_id,
            error=str(exc),
            error_type=type(exc).__name__,
            path=request.url.path,
            exc_info=self.is_development,
        )

        error = ApiError(
            code="INTERNAL_ERROR",
            message="An unexpected error occurred" if not self.is_development else str(exc),
            request_id=request_id,
            status_code=500,
        )
        return JSONResponse(status_code=500, content=ApiErrorResponse(error=error).model_dump())

    def _get_error_code(self, status_code: int) -> str:
        for code, code_status in ERROR_CODES.items():
            if code_status == status_code:
                return code
        return "INTERNAL_ERROR"


def register_error_handlers(app: FastAPI, is_development: bool = False) -> None:
    """Render EVERY error (including HTTPException raised in routes) as the
    standard ApiError envelope with the request's correlation id.

    This is required in addition to ErrorHandlingMiddleware because
    FastAPI's internal ExceptionMiddleware converts HTTPException /
    RequestValidationError into responses before they can reach user
    middleware — without handlers, those common errors bypass the
    standard shape entirely (plain {"detail": ...}, no request_id).
    """
    renderer = ErrorHandlingMiddleware(app, is_development=is_development)

    async def _http_handler(request: Request, exc: HTTPException) -> JSONResponse:
        return renderer._handle_http_exception(request, exc)

    async def _validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        return renderer._handle_validation_error(request, exc)

    async def _unexpected_handler(request: Request, exc: Exception) -> JSONResponse:
        return renderer._handle_unexpected_error(request, exc)

    app.add_exception_handler(HTTPException, _http_handler)
    # RequestValidationError subclasses ValidationError; register both so
    # nothing falls back to FastAPI's {"detail": ...} shape.
    app.add_exception_handler(RequestValidationError, _validation_handler)
    app.add_exception_handler(Exception, _unexpected_handler)
