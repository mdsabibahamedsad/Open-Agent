"""MP28: public error taxonomy (§48) + webhook helpers (§93) + mocks (§59)."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any

# ---------------------------------------------------------------------------
# Stable public error taxonomy. Production responses carry safe info only:
# code + message + request_id. Never stack traces, secrets, credentials,
# internal paths, or infrastructure details.
# ---------------------------------------------------------------------------

class OpenAgentError(Exception):
    code = "OPENAGENT_ERROR"
    status_code = 500

    def __init__(self, message: str = "", *, details: dict | None = None):
        super().__init__(message or self.code)
        self.message = message or self.code
        self.details = details or {}

    def to_public(self, request_id: str = "") -> dict:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "request_id": request_id,
            }
        }


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


ERROR_CODES: tuple[str, ...] = tuple(sorted({
    AuthenticationError.code, AuthorizationError.code, ValidationError.code,
    NotFoundError.code, ConflictError.code, RateLimitError.code,
    TimeoutError.code, PolicyDeniedError.code, ApprovalRequiredError.code,
    CompatibilityError.code, ExtensionError.code, ToolExecutionError.code,
    ConnectorError.code, MCPError.code, SandboxError.code, DeploymentError.code,
}))


# ---------------------------------------------------------------------------
# Webhook signing / verification (§93). HMAC-SHA256 over
#   v1.{timestamp}.{delivery_id}.{sha256(body)}
# Replay window: 5 minutes. Constant-time comparison. No signature
# confusion: the version prefix is mandatory.
# ---------------------------------------------------------------------------

SIGNATURE_VERSION = "v1"
REPLAY_TOLERANCE_SECONDS = 300


def sign_webhook(secret: str, body: bytes, *, delivery_id: str, timestamp: int = 0) -> str:
    ts = timestamp or int(time.time())
    body_hash = hashlib.sha256(body).hexdigest()
    base = f"{SIGNATURE_VERSION}.{ts}.{delivery_id}.{body_hash}".encode()
    digest = hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()
    return f"{SIGNATURE_VERSION},t={ts},id={delivery_id},sig={digest}"


def verify_webhook(
    secret: str,
    body: bytes,
    header: str,
    *,
    now: int = 0,
    tolerance: int = REPLAY_TOLERANCE_SECONDS,
) -> dict[str, Any]:
    """Verify a webhook signature header. Returns {ok, reason, delivery_id}."""
    try:
        parts: dict[str, str] = {}
        for chunk in header.split(","):
            chunk = chunk.strip()
            if chunk == SIGNATURE_VERSION:
                parts["v"] = chunk
            elif "=" in chunk:
                key, _, value = chunk.partition("=")
                parts[key.strip()] = value.strip()
        if parts.get("v") != SIGNATURE_VERSION or not parts.get("sig") or not parts.get("t"):
            return {"ok": False, "reason": "malformed signature header", "delivery_id": parts.get("id", "")}
        ts = int(parts["t"])
        current = now or int(time.time())
        if abs(current - ts) > tolerance:
            return {"ok": False, "reason": "timestamp outside tolerance", "delivery_id": parts.get("id", "")}
        expected = sign_webhook(secret, body, delivery_id=parts.get("id", ""), timestamp=ts)
        if not hmac.compare_digest(expected, header.strip()):
            return {"ok": False, "reason": "signature mismatch", "delivery_id": parts.get("id", "")}
        return {"ok": True, "reason": "", "delivery_id": parts.get("id", "")}
    except (ValueError, TypeError) as exc:
        return {"ok": False, "reason": f"verification error: {exc}", "delivery_id": ""}


def parse_webhook(body: bytes) -> dict[str, Any]:
    try:
        data = json.loads(body.decode())
    except Exception as exc:
        raise ValidationError(f"invalid webhook JSON: {exc}") from exc
    if not isinstance(data, dict) or "event" not in data:
        raise ValidationError("webhook body must be a JSON object with an 'event' field")
    return data
