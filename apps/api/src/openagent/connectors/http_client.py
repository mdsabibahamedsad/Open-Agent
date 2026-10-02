"""Shared provider HTTP stack (MP21).

Every connector funnels egress through ProviderHTTPClient — no per-connector
HTTP stacks. Guarantees: SSRF gate before connect, redirect validation,
timeouts, provider-aware retries, circuit breaker, keep-alive pooling,
rate-limit cooperation, normalized errors, zero secret logging.
"""

from __future__ import annotations

import asyncio
import time
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Optional

import structlog

from openagent.connectors import ratelimit as ratelimits
from openagent.connectors.errors import (
    ProviderError,
    ProviderErrorKind,
    normalize_exception,
    normalize_http_error,
)
from openagent.connectors.netsec import SSRFError, assert_redirect_safe, assert_url_safe
from openagent.connectors.retry import decide_retry

logger = structlog.get_logger("openagent.connectors.http")

_MAX_BODY_LOG = 500


@dataclass
class CircuitState:
    failures: int = 0
    opened_at: Optional[float] = None
    half_open_at: Optional[float] = None
    state: str = "CLOSED"  # CLOSED|OPEN|HALF_OPEN
    failure_threshold: int = 5
    open_seconds: float = 60.0


@dataclass
class ProviderResponse:
    status: int
    headers: dict[str, str]
    body: Any
    latency_ms: int
    provider_request_id: str = ""
    bytes_size: int = 0


class ProviderHTTPClient:
    """One instance per process; sessions pooled, credentials never cached."""

    def __init__(self, *, user_agent: str = "OpenAgent-Connector/1.0",
                 allow_private: bool = False):
        self.user_agent = user_agent
        self.allow_private = allow_private
        self._session = None
        self._circuits: dict[str, CircuitState] = {}
        self._lock = asyncio.Lock()

    async def _session_get(self):
        if self._session is None or getattr(self._session, "closed", True):
            import aiohttp
            timeout = aiohttp.ClientTimeout(total=120)
            connector = aiohttp.TCPConnector(limit=64, limit_per_host=8,
                                             keepalive_timeout=30)
            self._session = aiohttp.ClientSession(timeout=timeout,
                                                  connector=connector)
        return self._session

    async def aclose(self) -> None:
        if self._session is not None:
            with suppress(Exception):
                await self._session.close()
            self._session = None

    def _circuit(self, host: str) -> CircuitState:
        return self._circuits.setdefault(host, CircuitState())

    async def request(self, method: str, url: str, *,
                      headers: Optional[dict[str, str]] = None,
                      params: Optional[dict[str, Any]] = None,
                      json_body: Any = None,
                      form: Any = None,
                      files: Optional[dict[str, Any]] = None,
                      log_url: Optional[str] = None,
                      timeout_seconds: int = 30,
                      max_attempts: int = 3,
                      idempotent: bool = False,
                      rate_state: Optional[ratelimits.RateLimitState] = None,
                      rate_strategy: str = "wait") -> ProviderResponse:
        """Execute one provider call with the full safety stack.

        files: {field: (filename, bytes, content_type)} multipart upload.
        log_url: redacted URL for logs when the real URL carries secrets
        (e.g. Telegram bot token in path).
        """
        parts = assert_url_safe(url, allow_private=self.allow_private)
        host = parts["host"]
        circuit = self._circuit(host)
        now = time.time()
        if circuit.state == "OPEN":
            if now - (circuit.opened_at or 0) < circuit.open_seconds:
                raise ProviderError(ProviderErrorKind.PROVIDER_UNAVAILABLE,
                                    f"Circuit OPEN for {host}; backing off")
            circuit.state = "HALF_OPEN"
        safe_headers = dict(headers or {})
        safe_headers.setdefault("User-Agent", self.user_agent)
        # Never log Authorization material (defense in depth; callers must
        # not pass raw secrets in logs either).
        attempt = 0
        last_error: Optional[ProviderError] = None
        session = await self._session_get()
        while attempt < max(1, max_attempts):
            if rate_state is not None:
                decision = ratelimits.check(rate_state, strategy=rate_strategy)
                if not decision.allowed:
                    if decision.strategy == "fail" or decision.wait_seconds <= 0:
                        raise ProviderError(ProviderErrorKind.RATE_LIMITED,
                                            f"Rate limited: {decision.reason}")
                    await asyncio.sleep(min(decision.wait_seconds, 60.0))
            started = time.time()
            try:
                import aiohttp
                current_url = url
                response = None
                redirects = 0
                log_label = log_url or url
                data_payload = form
                if files:
                    form_data = aiohttp.FormData()
                    for field_name, spec in files.items():
                        if isinstance(spec, (list, tuple)) and len(spec) == 3:
                            filename, content, content_type = spec
                            form_data.add_field(
                                field_name, content, filename=str(filename),
                                content_type=str(content_type or
                                                 "application/octet-stream"))
                        else:
                            form_data.add_field(field_name, spec)
                    data_payload = form_data
                while True:
                    async with session.request(
                            method.upper(), current_url,
                            headers={k: v for k, v in safe_headers.items()},
                            params=params if current_url == url else None,
                            json=json_body, data=data_payload,
                            timeout=aiohttp.ClientTimeout(total=max(1, timeout_seconds)),
                            allow_redirects=False) as resp:
                        location = resp.headers.get("Location")
                        if location and resp.status in (301, 302, 303, 307, 308):
                            redirects += 1
                            assert_redirect_safe(
                                current_url, location,
                                allow_private=self.allow_private,
                                max_redirects=max(0, 5 - redirects + 1))
                            if redirects > 5:
                                raise ProviderError(
                                    ProviderErrorKind.NETWORK_ERROR,
                                    "Too many redirects")
                            from urllib.parse import urljoin
                            current_url = urljoin(current_url, location)
                            # Drop query params on redirect; never forward the
                            # original params to a new host.
                            continue
                        body: Any = None
                        raw = await resp.read()
                        ctype = resp.headers.get("Content-Type", "")
                        if raw:
                            if "json" in ctype:
                                try:
                                    import json as _json
                                    body = _json.loads(raw.decode("utf-8", "replace"))
                                except Exception:
                                    body = raw.decode("utf-8", "replace")[:8000]
                            else:
                                body = raw.decode("utf-8", "replace")[:8000]
                        response = (resp.status, dict(resp.headers), body, len(raw))
                        break
                status, resp_headers, body, size = response
                latency_ms = int((time.time() - started) * 1000)
                if rate_state is not None:
                    parsed = ratelimits.parse_headers(
                        {k: str(v) for k, v in resp_headers.items()})
                    if parsed.limit is not None:
                        rate_state.limit = parsed.limit
                    if parsed.remaining is not None:
                        rate_state.remaining = parsed.remaining
                    if parsed.reset_at_epoch is not None:
                        rate_state.reset_at_epoch = parsed.reset_at_epoch
                    if parsed.retry_after_seconds is not None:
                        rate_state.retry_after_seconds = parsed.retry_after_seconds
                    ratelimits.record_call(rate_state)
                if status >= 400:
                    raise normalize_http_error(status, body)
                circuit.failures = 0
                if circuit.state == "HALF_OPEN":
                    circuit.state = "CLOSED"
                provider_request_id = ""
                lowered_headers = {str(k).lower(): str(v)
                                   for k, v in resp_headers.items()}
                for key in ("x-request-id", "x-github-request-id",
                            "x-stripe-request-id", "x-slack-request-id"):
                    if key in lowered_headers:
                        provider_request_id = lowered_headers[key][:128]
                        break
                self._log_call(method, log_label, status, latency_ms, None)
                return ProviderResponse(status=status, headers=dict(resp_headers),
                                        body=body, latency_ms=latency_ms,
                                        provider_request_id=provider_request_id,
                                        bytes_size=size)
            except SSRFError:
                raise
            except ProviderError as exc:
                last_error = exc
                # 4xx validation/auth errors must not poison the host circuit;
                # only rate-limits, 5xx, and timeouts count toward OPEN.
                retryable_for_circuit = (
                    exc.kind in (ProviderErrorKind.RATE_LIMITED,
                                 ProviderErrorKind.PROVIDER_UNAVAILABLE,
                                 ProviderErrorKind.TIMEOUT,
                                 ProviderErrorKind.NETWORK_ERROR)
                    or (exc.status_code is not None and exc.status_code >= 500))
                if retryable_for_circuit:
                    circuit.failures += 1
                    if circuit.failures >= circuit.failure_threshold:
                        if circuit.state != "OPEN":
                            from openagent.connectors import metrics as _m
                            with suppress(Exception):
                                _m.inc("circuit_opens_total")
                        circuit.state = "OPEN"
                        circuit.opened_at = time.time()
                retry_after = None
                if exc.kind == ProviderErrorKind.RATE_LIMITED:
                    retry_after = exc.retry_after_seconds
                decision = decide_retry(exc, attempt=attempt,
                                        idempotent=idempotent,
                                        retry_after=retry_after)
                self._log_call(method, log_label, exc.status_code or 0, 0, exc.kind)
                if decision.refresh_credential:
                    raise
                if not decision.retry or attempt + 1 >= max(1, max_attempts):
                    raise
                await asyncio.sleep(decision.delay_seconds)
                attempt += 1
            except Exception as exc:
                last_error = normalize_exception(exc)
                circuit.failures += 1
                if circuit.failures >= circuit.failure_threshold and \
                        circuit.state != "OPEN":
                    from openagent.connectors import metrics as _m2
                    with suppress(Exception):
                        _m2.inc("circuit_opens_total")
                    circuit.state = "OPEN"
                    circuit.opened_at = time.time()
                decision = decide_retry(last_error, attempt=attempt,
                                        idempotent=idempotent)
                self._log_call(method, log_label, 0, 0, last_error.kind)
                if not decision.retry or attempt + 1 >= max(1, max_attempts):
                    raise last_error
                await asyncio.sleep(decision.delay_seconds)
                attempt += 1
        raise last_error or ProviderError(ProviderErrorKind.UNKNOWN_PROVIDER_ERROR,
                                          "Request failed")

    def _log_call(self, method: str, url: str, status: int,
                  latency_ms: int, error_kind: Optional[str]) -> None:
        from urllib.parse import urlparse
        try:
            parsed = urlparse(url)
            safe = f"{parsed.scheme}://{parsed.hostname}{parsed.path}"
        except Exception:
            safe = "<unparseable>"
        logger.info("connector.http", method=method, url=safe, status=status,
                    latency_ms=latency_ms, error=error_kind or "")


_shared_client: Optional[ProviderHTTPClient] = None


def shared_client(*, allow_private: bool = False) -> ProviderHTTPClient:
    global _shared_client
    if _shared_client is None:
        _shared_client = ProviderHTTPClient(allow_private=allow_private)
    return _shared_client
