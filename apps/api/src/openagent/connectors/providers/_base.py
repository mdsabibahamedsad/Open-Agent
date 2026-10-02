"""Shared provider helpers (MP21).

Auth-bundle handling, base URLs, JSON-schema validation of action inputs,
compact response shaping. Provider modules stay thin; all security lives in
the shared stack (SSRF gate, retries, circuit breaker, error normalization).
"""

from __future__ import annotations

from typing import Any, Optional

from openagent.connectors.errors import ProviderError, ProviderErrorKind
from openagent.evaluator.deterministic import validate_json_schema


def secrets_of(auth: dict[str, Any]) -> dict[str, Any]:
    secrets = auth.get("secrets", {}) or {}
    if not isinstance(secrets, dict):
        raise ProviderError(ProviderErrorKind.AUTHENTICATION_ERROR,
                            "Credential payload malformed")
    return secrets


def bearer_headers(auth: dict[str, Any], *, extra: Optional[dict[str, str]] = None,
                   scheme: str = "Bearer") -> dict[str, str]:
    secrets = secrets_of(auth)
    token = secrets.get("access_token") or secrets.get("token") or \
        secrets.get("api_key") or ""
    if not token:
        raise ProviderError(ProviderErrorKind.AUTHENTICATION_ERROR,
                            "Missing bearer credential")
    headers = {"Authorization": f"{scheme} {token}"}
    headers.update(extra or {})
    return headers


def api_key_headers(auth: dict[str, Any], *, header: str = "X-API-Key",
                    extra: Optional[dict[str, str]] = None) -> dict[str, str]:
    secrets = secrets_of(auth)
    key = secrets.get("api_key", "")
    if not key:
        raise ProviderError(ProviderErrorKind.AUTHENTICATION_ERROR,
                            "Missing API key")
    headers = {header: key}
    headers.update(extra or {})
    return headers


def basic_auth(auth: dict[str, Any]) -> tuple[str, str]:
    secrets = secrets_of(auth)
    username = secrets.get("username", "")
    password = secrets.get("password", "")
    if not username:
        raise ProviderError(ProviderErrorKind.AUTHENTICATION_ERROR,
                            "Missing basic-auth username")
    return username, password


def base_url(auth: dict[str, Any], default: str, *, key: str = "base_url") -> str:
    secrets = secrets_of(auth)
    url = str(secrets.get(key, "") or default)
    if not url.startswith("https://"):
        raise ProviderError(ProviderErrorKind.VALIDATION_ERROR,
                            f"Provider base URL must be https, got '{url[:60]}'")
    return url.rstrip("/")


def validate_input(schema: dict[str, Any], params: dict[str, Any],
                   action_id: str) -> dict[str, Any]:
    violations = validate_json_schema(params or {}, schema or {"type": "object"})
    if violations:
        raise ProviderError(ProviderErrorKind.VALIDATION_ERROR,
                            f"Invalid input for {action_id}: {'; '.join(violations[:3])}")
    return dict(params or {})


def ok(action_id: str, result: Any, *,
       provider_request_id: str = "",
       verified: bool = False) -> dict[str, Any]:
    return {"status": "ok", "action": action_id, "result": result,
            "provider_request_id": provider_request_id, "verified": verified}


def schema(obj_type: str = "object", properties: Optional[dict[str, Any]] = None,
           required: Optional[list[str]] = None,
           additional: bool = False) -> dict[str, Any]:
    return {"type": obj_type, "properties": properties or {},
            "required": required or [], "additionalProperties": additional}
