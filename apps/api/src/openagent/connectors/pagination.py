"""Universal pagination abstraction (MP21).

Supports cursor/offset/page/link-header/next-url strategies with hard caps
(max_pages, max_items, max_bytes, max_time). Never unbounded retrieval.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class PageSpec:
    strategy: str = "cursor"  # cursor|offset|page|link_header|next_url|single
    page_param: str = "page"
    per_page_param: str = "per_page"
    per_page: int = 50
    cursor_param: str = "cursor"
    cursor_path: str = ""  # dotted path in response for next cursor
    offset_param: str = "offset"
    items_path: str = ""  # dotted path to items array ("" = body itself)
    max_pages: int = 10
    max_items: int = 500
    max_bytes: int = 5 * 1024 * 1024
    max_seconds: float = 120.0


@dataclass
class PageResult:
    items: list[Any] = field(default_factory=list)
    pages_fetched: int = 0
    bytes_seen: int = 0
    truncated: bool = False
    next_cursor: str = ""


def _dig(mapping: Any, path: str) -> Any:
    if not path:
        return mapping
    node = mapping
    for part in path.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return None
    return node


def _parse_link_header(value: str) -> dict[str, str]:
    links: dict[str, str] = {}
    for chunk in (value or "").split(","):
        parts = chunk.split(";")
        if len(parts) < 2:
            continue
        url = parts[0].strip().strip("<>")
        for param in parts[1:]:
            param = param.strip()
            if param.lower().startswith("rel="):
                links[param[4:].strip().strip('"')] = url
    return links


class Paginator:
    """Drives a fetch callback until exhaustion or caps. The callback performs
    one HTTP call: fetch(params) -> (response_json, response_headers, byte_size)."""

    def __init__(self, spec: PageSpec):
        if spec.strategy not in ("cursor", "offset", "page", "link_header",
                                 "next_url", "single"):
            raise ValueError(f"Unknown pagination strategy '{spec.strategy}'")
        self.spec = spec

    async def collect(self, fetch: Callable[[dict[str, Any]], Any]) -> PageResult:
        started = time.time()
        result = PageResult()
        params: dict[str, Any] = {}
        cursor = ""
        page_number = 1
        offset = 0
        next_url: Optional[str] = None
        headers: dict[str, str] = {}
        while True:
            if result.pages_fetched >= max(1, self.spec.max_pages):
                result.truncated = True
                break
            if len(result.items) >= max(1, self.spec.max_items):
                result.truncated = True
                break
            if time.time() - started > max(1.0, self.spec.max_seconds):
                result.truncated = True
                break
            if self.spec.strategy == "cursor":
                params = {self.spec.cursor_param: cursor} if cursor else {}
                if self.spec.per_page_param:
                    params[self.spec.per_page_param] = self.spec.per_page
            elif self.spec.strategy == "offset":
                params = {self.spec.offset_param: offset,
                          self.spec.per_page_param: self.spec.per_page}
            elif self.spec.strategy == "page":
                params = {self.spec.page_param: page_number,
                          self.spec.per_page_param: self.spec.per_page}
            elif self.spec.strategy == "next_url" and next_url:
                params = {"__next_url__": next_url}
            body, headers, size = await fetch(params)
            result.pages_fetched += 1
            result.bytes_seen += int(size or 0)
            if result.bytes_seen > max(1024, self.spec.max_bytes):
                result.truncated = True
                break
            items = _dig(body, self.spec.items_path)
            if not isinstance(items, list):
                items = []
            room = max(0, self.spec.max_items - len(result.items))
            result.items.extend(items[:room])
            if len(items) > room:
                result.truncated = True
                break
            # Advance cursor per strategy.
            advanced = False
            if self.spec.strategy == "cursor":
                nxt = _dig(body, self.spec.cursor_path) if self.spec.cursor_path else None
                if isinstance(nxt, str) and nxt and nxt != cursor:
                    cursor = nxt
                    result.next_cursor = nxt
                    advanced = True
            elif self.spec.strategy == "offset":
                if len(items) == 0:
                    break
                offset += len(items)
                advanced = True
            elif self.spec.strategy == "page":
                if len(items) == 0:
                    break
                page_number += 1
                advanced = True
            elif self.spec.strategy == "link_header":
                links = _parse_link_header(headers.get("link", headers.get("Link", "")))
                if "next" in links and links["next"] != next_url:
                    next_url = links["next"]
                    advanced = True
            elif self.spec.strategy == "next_url":
                nxt = _dig(body, "next") or _dig(body, "next_url")
                if isinstance(nxt, str) and nxt and nxt != next_url:
                    next_url = nxt
                    advanced = True
            elif self.spec.strategy == "single":
                break
            if not advanced:
                break
        return result
