"""OpenAgent public error taxonomy.

Mirrors the backend taxonomy (safe info only: code + message + request_id).
Never includes stack traces, secrets, credentials, or internal paths.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Type

__all__ = [
    "OpenAgentError",
    "AuthenticationError",
    "AuthorizationError",
    "ValidationError",
    "NotFoundError",
    "ConflictError",
    "RateLimitError",
    "TimeoutError",
    "PolicyDeniedError",
    "ApprovalRequiredError",
    "CompatibilityError",
    "ExtensionError",
    "ToolExecutionError",
    "ConnectorError",
    "MCPError",
    "SandboxError",
    "DeploymentError",
    "ERROR_CODES",
    "from_response",
]

_MAX_MESSAGE_LEN = 500


def _safe_message(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    elif isinstance(value, (list, tuple)):
        parts = []
        for item in value:
            if isinstance(item, dict):
                loc = item.get("loc", "")
                msg = item.get("msg", "")
                parts.append(f"{loc}: {msg}" if loc else str(msg))
            else:
                parts.append(str(item))
        text = "; ".join(parts)
    elif isinstance(value, dict):
        text = value.get("message", "") or str(value)
    else:
        text = str(value)
    text = " ".join(text.split())
    if len(text) > _MAX_MESSAGE_LEN:
        text = text[:_MAX_MESSAGE_LEN] + "..."
    return text


class OpenAgentError(Exception):
    """Base class for all OpenAgent SDK errors."""

    code = "OPENAGENT_ERROR"
    status_code = 500

    def __init__(
        self,
        message: str = "",
        *,
        request_id: str = "",
        details: Optional[Dict[str, Any]] = None,
        retry_after: Optional[float] = None,
        rate_limit: Optional[Dict[str, Any]] = None,
    ) -> None:
        safe = _safe_message(message) or self.code
        super().__init__(safe)
        self.message = safe
        self.request_id = request_id or ""
        self.details: Dict[str, Any] = dict(details or {})
        self.retry_after = retry_after
        self.rate_limit: Dict[str, Any] = dict(rate_limit or {})

    def __str__(self) -> str:  # pragma: no cover - trivial
        if self.request_id:
            return f"[{self.code}] {self.message} (request_id={self.request_id})"
        return f"[{self.code}] {self.message}"

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return (
            f"{type(self).__name__}(code={self.code!r}, message={self.message!r}, "
            f"request_id={self.request_id!r})"
        )


class AuthenticationError(OpenAgentError):
    code = "AUTHENTICATION_ERROR"
    status_code = 401


class AuthorizationError(OpenAgentError):
    code = "AUTHORIZATION_ERROR"
    status_code = 403


class ValidationError(OpenAgentError):
    code = "VALIDATION_ERROR"
    status_code = 422


class NotFoundError(OpenAgentError):
    code = "NOT_FOUND"
    status_code = 404


class ConflictError(OpenAgentError):
    code = "CONFLICT"
    status_code = 409


class RateLimitError(OpenAgentError):
    code = "RATE_LIMITED"
    status_code = 429


class TimeoutError(OpenAgentError):
    code = "TIMEOUT"
    status_code = 504


class PolicyDeniedError(OpenAgentError):
    code = "POLICY_DENIED"
    status_code = 403


class ApprovalRequiredError(OpenAgentError):
    code = "APPROVAL_REQUIRED"
    status_code = 403


class CompatibilityError(OpenAgentError):
    code = "COMPATIBILITY_ERROR"
    status_code = 422


class ExtensionError(OpenAgentError):
    code = "EXTENSION_ERROR"
    status_code = 422


class ToolExecutionError(OpenAgentError):
    code = "TOOL_EXECUTION_ERROR"
    status_code = 502


class ConnectorError(OpenAgentError):
    code = "CONNECTOR_ERROR"
    status_code = 502


class MCPError(OpenAgentError):
    code = "MCP_ERROR"
    status_code = 502


class SandboxError(OpenAgentError):
    code = "SANDBOX_ERROR"
    status_code = 502


class DeploymentError(OpenAgentError):
    code = "DEPLOYMENT_ERROR"
    status_code = 502


_CODE_TO_CLASS: Dict[str, Type[OpenAgentError]] = {
    cls.code: cls
    for cls in (
        AuthenticationError,
        AuthorizationError,
        ValidationError,
        NotFoundError,
        ConflictError,
        RateLimitError,
        TimeoutError,
        PolicyDeniedError,
        ApprovalRequiredError,
        CompatibilityError,
        ExtensionError,
        ToolExecutionError,
        ConnectorError,
        MCPError,
        SandboxError,
        DeploymentError,
    )
}

_STATUS_FALLBACK: Dict[int, Type[OpenAgentError]] = {
    400: ValidationError,
    401: AuthenticationError,
    402: AuthorizationError,
    403: AuthorizationError,
    404: NotFoundError,
    405: ValidationError,
    409: ConflictError,
    410: NotFoundError,
    412: CompatibilityError,
    415: ValidationError,
    422: ValidationError,
    423: ApprovalRequiredError,
    429: RateLimitError,
    502: ToolExecutionError,
    503: DeploymentError,
    504: TimeoutError,
    507: DeploymentError,
}

ERROR_CODES = tuple(sorted(_CODE_TO_CLASS.keys()))


def _extract_code_and_message(payload: Any) -> tuple[str, str]:
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            code = str(error.get("code", "") or "")
            message = _safe_message(error.get("message", ""))
            return code, message
        if "detail" in payload:
            return "", _safe_message(payload.get("detail"))
        if "message" in payload:
            return str(payload.get("code", "") or ""), _safe_message(payload.get("message"))
    return "", _safe_message(payload)


def from_response(
    status: int,
    payload: Any,
    request_id: str = "",
    *,
    retry_after: Optional[float] = None,
    rate_limit: Optional[Dict[str, Any]] = None,
) -> OpenAgentError:
    """Build the most specific SDK error for an HTTP failure response."""
    code, message = _extract_code_and_message(payload)
    cls: Optional[Type[OpenAgentError]] = _CODE_TO_CLASS.get(code) if code else None
    if cls is None:
        cls = _STATUS_FALLBACK.get(status)
    if cls is None:
        if 400 <= status < 500:
            cls = ValidationError if status in (400, 405, 415, 422) else OpenAgentError
            if status == 401:
                cls = AuthenticationError
            elif status == 403:
                cls = AuthorizationError
            elif status == 404:
                cls = NotFoundError
            elif status == 409:
                cls = ConflictError
            elif status == 429:
                cls = RateLimitError
        elif status == 504:
            cls = TimeoutError
        elif status >= 500:
            cls = OpenAgentError
        else:
            cls = OpenAgentError
    details: Dict[str, Any] = {"http_status": status}
    if code:
        details["code"] = code
    return cls(
        message or code or f"request failed with status {status}",
        request_id=request_id,
        details=details,
        retry_after=retry_after,
        rate_limit=rate_limit,
    )
