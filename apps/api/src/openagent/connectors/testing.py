"""Connector test harness (MP21): mock provider, auth, webhooks, rate limits,
errors, pagination, retries. Official connectors ship tests on these fakes —
no real provider credentials needed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class MockHTTPResponse:
    status: int
    body: Any = None
    headers: dict[str, str] = field(default_factory=dict)


class MockProviderHTTP:
    """Drop-in fake for ProviderHTTPClient.request + provider executors."""

    def __init__(self, routes: Optional[dict[tuple[str, str], Any]] = None):
        # (METHOD, path_suffix) -> MockHTTPResponse | list[MockHTTPResponse] | Exception
        self.routes: dict[tuple[str, str], Any] = routes or {}
        self.calls: list[dict[str, Any]] = []
        self.default = MockHTTPResponse(200, {})

    def add(self, method: str, path_suffix: str, response: Any) -> None:
        self.routes[(method.upper(), path_suffix)] = response

    async def request(self, method: str, url: str, **kwargs: Any):
        from openagent.connectors.errors import normalize_http_error
        from openagent.connectors.http_client import ProviderResponse
        call = {"method": method.upper(), "url": url,
                "headers": dict(kwargs.get("headers", {}) or {}),
                "params": kwargs.get("params"), "json": kwargs.get("json_body"),
                "log_url": kwargs.get("log_url")}
        self.calls.append(call)
        matched = None
        for (route_method, suffix), response in self.routes.items():
            if route_method == method.upper() and suffix in url:
                matched = response
                break
        if matched is None:
            matched = self.default
        if isinstance(matched, list):
            matched = matched.pop(0) if matched else self.default
        if isinstance(matched, dict):
            matched = MockHTTPResponse(200, matched)
        if isinstance(matched, Exception):
            raise matched
        if matched.status >= 400:
            raise normalize_http_error(matched.status, matched.body)
        return ProviderResponse(status=matched.status, headers=dict(matched.headers),
                                body=matched.body, latency_ms=1,
                                provider_request_id="mock-req-1",
                                bytes_size=len(json.dumps(matched.body or {})))


class MockAuth:
    """Capability-scoped fake auth bundle (no real secrets)."""

    def __init__(self, secrets: Optional[dict[str, Any]] = None,
                 credential_type: str = "api_key"):
        self.bundle = {"credential_id": "00000000-0000-0000-0000-000000000000",
                       "credential_type": credential_type,
                       "secrets": dict(secrets or {"api_key": "test-key"}),
                       "expires_at": None}

    def as_dict(self) -> dict[str, Any]:
        return dict(self.bundle)


def mock_ctx(http: Optional[MockProviderHTTP] = None, **extra: Any) -> dict[str, Any]:
    ctx = {"http": http or MockProviderHTTP(), "logger": _NullLogger(),
           "idempotency_key": "", "connector_id": "test",
           "connection": {"id": "conn-1", "connector_id": "test", "config": {}}}
    ctx.update(extra)
    return ctx


class _NullLogger:
    def __getattr__(self, _name: str):
        def _noop(*_args: Any, **_kwargs: Any) -> None:
            return None
        return _noop


def mock_rate_limited() -> MockHTTPResponse:
    return MockHTTPResponse(429, {"error": "slow down"},
                            {"Retry-After": "1", "X-RateLimit-Remaining": "0"})


def mock_unauthorized() -> MockHTTPResponse:
    return MockHTTPResponse(401, {"error": "invalid_auth"})


def mock_server_error() -> MockHTTPResponse:
    return MockHTTPResponse(503, {"error": "try again"})


def paged(items: list[Any], *, per_page: int = 2) -> Callable[[dict], Any]:
    """Build a cursor fetch callback over static items for Paginator tests."""
    async def _fetch(params: dict[str, Any]):
        cursor = params.get("cursor", "")
        start = int(cursor) if str(cursor).isdigit() else 0
        chunk = items[start: start + per_page]
        nxt = str(start + per_page) if start + per_page < len(items) else ""
        return {"items": chunk, "next_cursor": nxt}, {}, len(str(chunk))
    return _fetch


def assert_no_secrets_in_calls(http: MockProviderHTTP,
                               secrets: list[str]) -> None:
    """Fail if any recorded call's LOGGABLE surface (headers/log_url) holds
    secret material. The request URL itself is excluded: some providers
    (Telegram) require tokens in path by design — those calls must pass a
    redacted log_url, which is what gets asserted here."""
    for call in http.calls:
        blob = json.dumps({"h": call.get("headers", {}),
                           "l": call.get("log_url", "") or ""})
        for secret in secrets:
            if secret and secret in blob:
                raise AssertionError(f"Secret leaked into call: {call}")


def validate_manifest_contract(manifest: dict[str, Any]) -> dict[str, Any]:
    """Contract gate for connector tests: manifest validity + action schemas
    + trigger/pagination/rate-limit declarations."""
    from openagent.connectors.manifest import validate_manifest
    parsed = validate_manifest(manifest)
    assert parsed.actions, "connector must declare actions"
    for action in parsed.actions:
        assert action.input_schema.get("type") == "object"
        assert action.required_capabilities
    return {"connector": parsed.id, "version": parsed.version,
            "actions": len(parsed.actions),
            "capabilities": len(parsed.capabilities),
            "triggers": len(parsed.triggers)}
