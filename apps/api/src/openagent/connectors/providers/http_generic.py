"""Generic HTTP connector executor (MP21).

Executes declarative HTTP actions from custom/HTTP_GENERIC manifests:
method + path template + param mapping, all through the shared provider
stack (SSRF gate, retries, circuit breaker, error normalization). Unknown
custom mutations already default HIGH risk at the engine gate.
"""

from __future__ import annotations

import re
from typing import Any

from openagent.connectors.errors import ProviderError, ProviderErrorKind
from openagent.connectors.providers._base import (
    base_url, bearer_headers, ok, secrets_of, validate_input,
)

_ALLOWED_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"}
_PATH_PARAM_RE = re.compile(r"\{([a-zA-Z0-9_]+)\}")


def _schema_of(manifest: Any, action_id: str) -> dict[str, Any]:
    for action in manifest.actions:
        if action.id == action_id:
            return action.input_schema
    return {"type": "object"}


def _action_def(manifest: Any, action_id: str) -> Any:
    for action in manifest.actions:
        if action.id == action_id:
            return action
    return None


async def execute_generic(manifest: Any, action_id: str,
                          params: dict[str, Any], auth: dict[str, Any],
                          ctx: dict[str, Any]) -> dict[str, Any]:
    http = ctx["http"]
    definition = _action_def(manifest, action_id)
    if definition is None:
        raise ProviderError(ProviderErrorKind.VALIDATION_ERROR,
                            f"Unknown action '{action_id}'")
    spec = dict(definition.http or {})
    method = str(spec.get("method", "GET")).upper()
    if method not in _ALLOWED_METHODS:
        raise ProviderError(ProviderErrorKind.VALIDATION_ERROR,
                            f"HTTP method '{method}' not allowed")
    path_template = str(spec.get("path", "/") or "/")
    if not path_template.startswith("/"):
        raise ProviderError(ProviderErrorKind.VALIDATION_ERROR,
                            "HTTP path must be absolute")
    params = validate_input(_schema_of(manifest, action_id), params, action_id)
    remaining = dict(params)
    path = path_template
    for name in _PATH_PARAM_RE.findall(path_template):
        if name not in remaining:
            raise ProviderError(ProviderErrorKind.VALIDATION_ERROR,
                                f"Missing path parameter '{name}'")
        value = str(remaining.pop(name))
        if not value or len(value) > 256 or "/" in value or ".." in value:
            raise ProviderError(ProviderErrorKind.VALIDATION_ERROR,
                                f"Unsafe path parameter '{name}'")
        from urllib.parse import quote
        path = path.replace("{" + name + "}", quote(value, safe=""))
    base = base_url(auth, "")
    url = f"{base}{path}"
    query_keys = spec.get("query_params", []) or []
    query = {k: remaining.pop(k) for k in query_keys if k in remaining}
    body = remaining if method in ("POST", "PUT", "PATCH") else None
    headers = _auth_headers(manifest, auth)
    credential_type = str(auth.get("credential_type", "") or "")
    idempotent = method in ("GET", "HEAD") or bool(
        getattr(definition, "supports_idempotency", False))
    resp = await http.request(
        method, url, headers=headers,
        params=query or None, json_body=body,
        timeout_seconds=min(int(getattr(definition, "timeout_seconds", 30) or 30),
                            300),
        max_attempts=3 if idempotent else 1, idempotent=idempotent)
    body_out = resp.body
    extract = str(spec.get("extract", "") or "")
    if extract and isinstance(body_out, dict):
        from openagent.connectors.mapping import resolve_path
        body_out = resolve_path(body_out, extract)
    _ = credential_type
    return ok(action_id, body_out,
              provider_request_id=resp.provider_request_id, verified=True)


def _auth_headers(manifest: Any, auth: dict[str, Any]) -> dict[str, str]:
    auth_cfg = manifest.auth if hasattr(manifest, "auth") else {}
    auth_type = str((auth_cfg or {}).get("type", "api_key")).lower()
    secrets = secrets_of(auth)
    if auth_type == "oauth2":
        token = secrets.get("access_token", "")
        if not token:
            raise ProviderError(ProviderErrorKind.AUTHENTICATION_ERROR,
                                "Missing OAuth access token")
        return {"Authorization": f"Bearer {token}"}
    if auth_type == "bearer_token":
        return bearer_headers(auth)
    if auth_type == "basic":
        import base64
        username = secrets.get("username", "")
        password = secrets.get("password", "")
        if not username:
            raise ProviderError(ProviderErrorKind.AUTHENTICATION_ERROR,
                                "Missing basic-auth username")
        raw = base64.b64encode(f"{username}:{password}".encode()).decode()
        return {"Authorization": f"Basic {raw}"}
    if auth_type == "jwt":
        token = secrets.get("jwt") or secrets.get("token", "")
        if not token:
            raise ProviderError(ProviderErrorKind.AUTHENTICATION_ERROR,
                                "Missing JWT")
        return {"Authorization": f"Bearer {token}"}
    if auth_type in ("custom_header", "service_account"):
        name = str((auth_cfg or {}).get("header_name", "X-API-Key"))
        key = secrets.get("api_key") or secrets.get("token", "")
        if not key:
            raise ProviderError(ProviderErrorKind.AUTHENTICATION_ERROR,
                                "Missing API credential")
        prefix = str((auth_cfg or {}).get("header_prefix", ""))
        return {name: f"{prefix}{key}".strip()}
    # api_key default: header (never query strings — avoids log leakage).
    return bearer_headers(auth) if str(
        (auth_cfg or {}).get("api_key_in", "header")) == "bearer" else \
        _api_key_header(auth, auth_cfg)


def _api_key_header(auth: dict[str, Any], auth_cfg: Any) -> dict[str, str]:
    secrets = secrets_of(auth)
    key = secrets.get("api_key", "")
    if not key:
        raise ProviderError(ProviderErrorKind.AUTHENTICATION_ERROR,
                            "Missing API key")
    name = str((auth_cfg or {}).get("header_name", "X-API-Key"))
    return {name: key}


async def test_generic(manifest: Any, auth: dict[str, Any],
                       ctx: dict[str, Any]) -> dict[str, Any]:
    """Safe connection test: smallest read action, else base URL HEAD."""
    http = ctx["http"]
    read_action = next((a for a in manifest.actions if not a.mutation), None)
    if read_action is not None and read_action.http:
        outcome = await execute_generic(
            manifest, read_action.id, {}, auth, ctx)
        return {"provider": manifest.id, "action": read_action.id,
                "ok": True, "outcome": outcome.get("status")}
    base = base_url(auth, "")
    resp = await http.request("HEAD", base, headers=_auth_headers(manifest, auth),
                              timeout_seconds=15, max_attempts=2, idempotent=True)
    return {"provider": manifest.id, "ok": resp.status < 400,
            "status": resp.status}
