"""Shared sync/async HTTP transport for the OpenAgent SDK.

Covers base-URL normalization, auth headers, per-request IDs, retries
(GET or idempotent writes only, exponential backoff + Retry-After on 429),
timeouts, pagination iteration, and SSE streaming.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, Tuple

import httpx

from .errors import OpenAgentError, TimeoutError, from_response
from .types_ import PaginatedResult

DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_RETRIES = 3
RETRYABLE_STATUSES = frozenset({429, 502, 503, 504})
_IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

__all__ = [
    "DEFAULT_TIMEOUT",
    "DEFAULT_MAX_RETRIES",
    "RETRYABLE_STATUSES",
    "SyncTransport",
    "AsyncTransport",
    "normalize_base_url",
    "parse_sse_events",
]


def normalize_base_url(base_url: str) -> str:
    """Normalize a user-supplied base URL to the ``/api/v1`` root."""
    url = (base_url or "").strip().rstrip("/")
    if not url:
        raise ValueError("base_url must be a non-empty URL")
    if url.endswith("/api/v1"):
        return url
    return url + "/api/v1"


def _new_request_id() -> str:
    return uuid.uuid4().hex


def _parse_retry_after(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        delay = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    if delay < 0:
        return None
    return min(delay, 60.0)


def _retry_delay(attempt: int, retry_after: Optional[float] = None) -> float:
    if retry_after is not None:
        return retry_after
    return min(0.5 * (2.0**attempt), 8.0)


def _extract_rate_limit(headers: httpx.Headers) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key in (
        "x-ratelimit-limit",
        "x-ratelimit-remaining",
        "x-ratelimit-reset",
        "ratelimit-limit",
        "ratelimit-remaining",
        "ratelimit-reset",
        "retry-after",
        "x-request-id",
    ):
        if key in headers:
            out[key] = headers[key]
    return out


def _parse_body(response: httpx.Response) -> Any:
    if response.status_code == 204 or not response.content:
        return {}
    try:
        return response.json()
    except ValueError:
        text = response.text
        return {"detail": text[:500]}


def _raise_for_failure(
    response: httpx.Response,
    payload: Any,
    request_id: str,
) -> None:
    headers = response.headers
    retry_after = _parse_retry_after(headers.get("retry-after"))
    server_request_id = headers.get("x-request-id", "") or request_id
    rate_limit = _extract_rate_limit(headers)
    raise from_response(
        response.status_code,
        payload,
        server_request_id,
        retry_after=retry_after,
        rate_limit=rate_limit,
    )


def _should_retry(
    method: str,
    status: int,
    attempt: int,
    max_retries: int,
    idempotency_key: Optional[str],
) -> bool:
    if attempt >= max_retries:
        return False
    if status not in RETRYABLE_STATUSES:
        return False
    if method.upper() in _IDEMPOTENT_METHODS:
        return True
    # Only retry writes when the caller made them idempotent.
    return bool(idempotency_key)


def _split_page(payload: Any) -> Tuple[List[Any], Optional[str], Optional[int], bool]:
    """Split a collection payload into (items, next_cursor, total, has_more)."""
    if isinstance(payload, list):
        return list(payload), None, len(payload), False
    if not isinstance(payload, dict):
        return [], None, None, False
    items: List[Any] = []
    for key in ("items", "data", "results"):
        value = payload.get(key)
        if isinstance(value, list):
            items = value
            break
    meta = payload.get("pagination") or payload.get("meta") or {}
    if not isinstance(meta, dict):
        meta = {}
    cursor: Optional[str] = None
    for key in ("next_cursor", "next_page_token", "cursor"):
        value = payload.get(key, meta.get(key))
        if value:
            cursor = str(value)
            break
    total = payload.get("total", meta.get("total"))
    try:
        total_int = int(total) if total is not None else None
    except (TypeError, ValueError):
        total_int = None
    has_more = bool(
        cursor
        or meta.get("has_more")
        or payload.get("has_more")
        or (
            isinstance(payload.get("page"), int)
            and isinstance(payload.get("total_pages"), int)
            and payload["page"] < payload["total_pages"]
        )
    )
    return items, cursor, total_int, has_more


def _next_params(
    params: Dict[str, Any], payload: Any, next_cursor: Optional[str]
) -> Optional[Dict[str, Any]]:
    if next_cursor:
        updated = dict(params)
        updated["cursor"] = next_cursor
        updated.pop("page", None)
        return updated
    if isinstance(payload, dict):
        page = payload.get("page", (payload.get("pagination") or {}).get("page"))
        total_pages = payload.get(
            "total_pages", (payload.get("pagination") or {}).get("total_pages")
        )
        if isinstance(page, int) and isinstance(total_pages, int) and page < total_pages:
            updated = dict(params)
            updated["page"] = page + 1
            return updated
    return None


def parse_sse_events(buffer: str) -> Tuple[List[Dict[str, Any]], str]:
    """Parse complete SSE frames from a text buffer.

    Returns (events, remainder) where remainder is the incomplete tail
    that must be prepended to the next chunk.
    """
    events: List[Dict[str, Any]] = []
    frames = buffer.split("\n\n")
    remainder = frames.pop()
    for frame in frames:
        if not frame.strip():
            continue
        event_name = "message"
        data_lines: List[str] = []
        for line in frame.splitlines():
            if line.startswith("data:"):
                data_lines.append(line[5:].strip())
            elif line.startswith("event:"):
                event_name = line[6:].strip() or "message"
            elif line.startswith(":"):
                continue
        raw = "\n".join(data_lines)
        if not raw:
            continue
        try:
            data: Any = json.loads(raw)
        except ValueError:
            data = raw
        events.append({"event": event_name, "data": data})
    return events, remainder


class _TransportBase:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        organization_id: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        self.api_key = api_key
        self.base_url = normalize_base_url(base_url)
        self.organization_id = organization_id
        self.timeout = timeout
        self.max_retries = max(0, int(max_retries))

    def _headers(
        self,
        *,
        organization_id: Optional[str] = None,
        request_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        extra: Optional[Dict[str, str]] = None,
    ) -> Dict[str, str]:
        org = organization_id or self.organization_id
        headers: Dict[str, str] = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "X-Request-ID": request_id or _new_request_id(),
        }
        if org:
            headers["X-Organization-ID"] = org
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        if extra:
            headers.update(extra)
        return headers

    def _url(self, path: str) -> str:
        if not path.startswith("/"):
            path = "/" + path
        return self.base_url + path


class SyncTransport(_TransportBase):
    """Synchronous httpx transport with retries, pagination, and SSE."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        organization_id: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        http_client: Optional[httpx.Client] = None,
    ) -> None:
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            organization_id=organization_id,
            timeout=timeout,
            max_retries=max_retries,
        )
        self._client = http_client or httpx.Client(timeout=timeout)
        self._owned = http_client is None

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        organization_id: Optional[str] = None,
        request_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> Any:
        rid = request_id or _new_request_id()
        attempt = 0
        while True:
            headers = self._headers(
                organization_id=organization_id,
                request_id=rid,
                idempotency_key=idempotency_key,
            )
            try:
                response = self._client.request(
                    method.upper(),
                    self._url(path),
                    params=params,
                    json=json_body,
                    headers=headers,
                    timeout=timeout if timeout is not None else self.timeout,
                )
            except httpx.TimeoutException as exc:
                raise TimeoutError(f"request timed out: {exc!r}"[:500]) from exc
            except httpx.HTTPError as exc:
                raise OpenAgentError(
                    f"request failed: {type(exc).__name__}"[:200],
                    request_id=rid,
                ) from exc
            payload = _parse_body(response)
            if response.status_code < 400:
                return payload
            if _should_retry(
                method, response.status_code, attempt, self.max_retries, idempotency_key
            ):
                delay = _retry_delay(
                    attempt, _parse_retry_after(response.headers.get("retry-after"))
                )
                time.sleep(delay)
                attempt += 1
                continue
            _raise_for_failure(response, payload, rid)

    def request_paginated(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> PaginatedResult:
        payload = self.request(method, path, params=params, **kwargs)
        items, cursor, total, has_more = _split_page(payload)
        raw = payload if isinstance(payload, dict) else {"items": items}
        return PaginatedResult(
            items=items, total=total, next_cursor=cursor, has_more=has_more, raw=raw
        )

    def iter_paginated(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        max_pages: int = 100,
        **kwargs: Any,
    ) -> Iterator[Any]:
        current = dict(params or {})
        for _ in range(max_pages):
            payload = self.request(method, path, params=current, **kwargs)
            items, cursor, _, _ = _split_page(payload)
            for item in items:
                yield item
            nxt = _next_params(current, payload, cursor)
            if nxt is None:
                return
            current = nxt

    def stream(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Iterator[Dict[str, Any]]:
        headers = self._headers(
            organization_id=kwargs.get("organization_id"),
            request_id=kwargs.get("request_id"),
            idempotency_key=kwargs.get("idempotency_key"),
            extra={"Accept": "text/event-stream"},
        )
        try:
            with self._client.stream(
                method.upper(),
                self._url(path),
                params=params,
                json=json_body,
                headers=headers,
                timeout=kwargs.get("timeout", self.timeout),
            ) as response:
                if response.status_code >= 400:
                    payload = _parse_body(response)
                    _raise_for_failure(
                        response, payload, headers["X-Request-ID"]
                    )
                buffer = ""
                for chunk in response.iter_text():
                    buffer += chunk
                    events, buffer = parse_sse_events(buffer)
                    for event in events:
                        yield event
                events, _ = parse_sse_events(buffer + "\n\n")
                for event in events:
                    yield event
        except httpx.TimeoutException as exc:
            raise TimeoutError(f"stream timed out: {exc!r}"[:500]) from exc
        except httpx.HTTPError as exc:
            if isinstance(exc, OpenAgentError):
                raise
            raise OpenAgentError(
                f"stream failed: {type(exc).__name__}"[:200],
            ) from exc

    def close(self) -> None:
        if self._owned:
            self._client.close()


class AsyncTransport(_TransportBase):
    """Async httpx transport mirroring :class:`SyncTransport`."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        organization_id: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        http_client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            organization_id=organization_id,
            timeout=timeout,
            max_retries=max_retries,
        )
        self._client = http_client or httpx.AsyncClient(timeout=timeout)
        self._owned = http_client is None

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        organization_id: Optional[str] = None,
        request_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> Any:
        rid = request_id or _new_request_id()
        attempt = 0
        while True:
            headers = self._headers(
                organization_id=organization_id,
                request_id=rid,
                idempotency_key=idempotency_key,
            )
            try:
                response = await self._client.request(
                    method.upper(),
                    self._url(path),
                    params=params,
                    json=json_body,
                    headers=headers,
                    timeout=timeout if timeout is not None else self.timeout,
                )
            except httpx.TimeoutException as exc:
                raise TimeoutError(f"request timed out: {exc!r}"[:500]) from exc
            except httpx.HTTPError as exc:
                raise OpenAgentError(
                    f"request failed: {type(exc).__name__}"[:200],
                    request_id=rid,
                ) from exc
            payload = _parse_body(response)
            if response.status_code < 400:
                return payload
            if _should_retry(
                method, response.status_code, attempt, self.max_retries, idempotency_key
            ):
                delay = _retry_delay(
                    attempt, _parse_retry_after(response.headers.get("retry-after"))
                )
                await asyncio.sleep(delay)
                attempt += 1
                continue
            _raise_for_failure(response, payload, rid)

    async def request_paginated(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> PaginatedResult:
        payload = await self.request(method, path, params=params, **kwargs)
        items, cursor, total, has_more = _split_page(payload)
        raw = payload if isinstance(payload, dict) else {"items": items}
        return PaginatedResult(
            items=items, total=total, next_cursor=cursor, has_more=has_more, raw=raw
        )

    async def iter_paginated(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        max_pages: int = 100,
        **kwargs: Any,
    ) -> AsyncIterator[Any]:
        current = dict(params or {})
        for _ in range(max_pages):
            payload = await self.request(method, path, params=current, **kwargs)
            items, cursor, _, _ = _split_page(payload)
            for item in items:
                yield item
            nxt = _next_params(current, payload, cursor)
            if nxt is None:
                return
            current = nxt

    async def stream(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> AsyncIterator[Dict[str, Any]]:
        headers = self._headers(
            organization_id=kwargs.get("organization_id"),
            request_id=kwargs.get("request_id"),
            idempotency_key=kwargs.get("idempotency_key"),
            extra={"Accept": "text/event-stream"},
        )
        try:
            async with self._client.stream(
                method.upper(),
                self._url(path),
                params=params,
                json=json_body,
                headers=headers,
                timeout=kwargs.get("timeout", self.timeout),
            ) as response:
                if response.status_code >= 400:
                    body = await response.aread()
                    try:
                        payload: Any = json.loads(body.decode() or "{}")
                    except ValueError:
                        payload = {"detail": body.decode(errors="replace")[:500]}
                    _raise_for_failure(
                        response, payload, headers["X-Request-ID"]
                    )
                buffer = ""
                async for chunk in response.aiter_text():
                    buffer += chunk
                    events, buffer = parse_sse_events(buffer)
                    for event in events:
                        yield event
                events, _ = parse_sse_events(buffer + "\n\n")
                for event in events:
                    yield event
        except httpx.TimeoutException as exc:
            raise TimeoutError(f"stream timed out: {exc!r}"[:500]) from exc
        except httpx.HTTPError as exc:
            if isinstance(exc, OpenAgentError):
                raise
            raise OpenAgentError(
                f"stream failed: {type(exc).__name__}"[:200],
            ) from exc

    async def close(self) -> None:
        if self._owned:
            await self._client.aclose()
