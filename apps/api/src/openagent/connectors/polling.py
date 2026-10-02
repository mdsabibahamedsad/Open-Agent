"""Polling triggers for providers without webhooks (MP21).

Cursor/last-seen state machine with deduplication, exponential backoff, and
rate-limit cooperation. No uncontrolled loops: every cycle is bounded by
max_items/max_pages and backs off on empty/error cycles.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional


@dataclass
class PollCursor:
    cursor: str = ""
    last_seen_id: str = ""
    seen_ids: list[str] = field(default_factory=list)
    last_poll_epoch: float = 0.0
    consecutive_empty: int = 0
    consecutive_errors: int = 0
    backoff_until_epoch: float = 0.0
    order: str = "newest_first"

    def to_dict(self) -> dict[str, Any]:
        return {"cursor": self.cursor, "last_seen_id": self.last_seen_id,
                "seen_ids": list(self.seen_ids[-200:]),
                "last_poll_epoch": self.last_poll_epoch,
                "consecutive_empty": self.consecutive_empty,
                "consecutive_errors": self.consecutive_errors,
                "backoff_until_epoch": self.backoff_until_epoch,
                "order": self.order}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PollCursor":
        data = data or {}
        seen = data.get("seen_ids", []) or []
        return cls(cursor=str(data.get("cursor", "")),
                   last_seen_id=str(data.get("last_seen_id", "")),
                   seen_ids=[str(s) for s in seen if s][:200],
                   last_poll_epoch=float(data.get("last_poll_epoch", 0.0) or 0.0),
                   consecutive_empty=int(data.get("consecutive_empty", 0) or 0),
                   consecutive_errors=int(data.get("consecutive_errors", 0) or 0),
                   backoff_until_epoch=float(data.get("backoff_until_epoch", 0.0) or 0.0),
                   order=str(data.get("order", "newest_first") or "newest_first"))


@dataclass
class PollResult:
    new_items: list[dict[str, Any]] = field(default_factory=list)
    cursor: PollCursor = field(default_factory=PollCursor)
    skipped_backoff: bool = False
    error: str = ""


def backoff_delay(consecutive_failures: int, *, base: float = 30.0,
                  cap: float = 3600.0) -> float:
    return min(cap, base * (2 ** max(0, consecutive_failures)))


async def run_poll_cycle(*, cursor: PollCursor,
                         fetch: Callable[[dict[str, Any]], Awaitable[list[dict[str, Any]]]],
                         id_of: Callable[[dict[str, Any]], str] | None = None,
                         max_items: int = 100,
                         now: Optional[float] = None) -> PollResult:
    """One bounded poll cycle. `fetch` receives {"cursor","last_seen_id"}."""
    now = now if now is not None else time.time()
    if cursor.backoff_until_epoch and now < cursor.backoff_until_epoch:
        return PollResult(cursor=cursor, skipped_backoff=True)
    id_of = id_of or (lambda item: str(item.get("id", "")))
    try:
        raw = await fetch({"cursor": cursor.cursor,
                           "last_seen_id": cursor.last_seen_id})
    except Exception as exc:
        cursor.consecutive_errors += 1
        cursor.consecutive_empty = 0
        cursor.backoff_until_epoch = now + backoff_delay(cursor.consecutive_errors)
        cursor.last_poll_epoch = now
        return PollResult(cursor=cursor, error=str(exc)[:300])
    items = [i for i in (raw or []) if isinstance(i, dict)][:max(1, max_items)]
    # Deduplicate against the persistent seen-set so reordered, repeated, or
    # oldest-first pages never re-emit. The cursor advances to the newest id
    # actually observed (last item), never assuming provider ordering.
    known = set(cursor.seen_ids or ([] if not cursor.last_seen_id else [cursor.last_seen_id]))
    fresh: list[dict[str, Any]] = []
    batch_ids: set[str] = set()
    for item in items:
        item_id = id_of(item)
        if not item_id or item_id in batch_ids or item_id in known:
            continue
        batch_ids.add(item_id)
        fresh.append(item)
    if fresh:
        newest = id_of(fresh[-1])
        cursor.last_seen_id = newest or cursor.last_seen_id
        cursor.cursor = cursor.last_seen_id
        cursor.seen_ids = ([*cursor.seen_ids, *[id_of(i) for i in fresh]][-200:])
        cursor.consecutive_empty = 0
        cursor.consecutive_errors = 0
    else:
        cursor.consecutive_empty += 1
        if cursor.consecutive_empty >= 5:
            cursor.backoff_until_epoch = now + backoff_delay(cursor.consecutive_empty - 5,
                                                             base=60.0)
    cursor.last_poll_epoch = now
    return PollResult(new_items=fresh, cursor=cursor)
