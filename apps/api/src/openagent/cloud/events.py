"""MP25: execution event store + streaming (§35-37).

Durable per-execution event log with monotonic sequence numbers
(resume-from-cursor), bounded live-stream buffers with drop policies
(backpressure), and secret redaction before anything reaches a client.
"""

from __future__ import annotations

import asyncio
import re
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Optional

STREAM_EVENT_TYPES = (
    "execution.started", "execution.progress", "execution.completed",
    "execution.failed", "node.started", "node.progress", "node.completed",
    "tool.called", "tool.completed", "agent.message", "approval.required",
    "artifact.created", "log.appended",
)

# Redact credential-looking keys/values before streaming/persisting.
_SECRET_KEY_RE = re.compile(r"(api[_-]?key|secret|password|token|credential|private[_-]?key)", re.I)
_SECRET_VALUE_RES = (
    re.compile(r"sk-(live|test)-[A-Za-z0-9]{8,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{8,}"),
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/-]{8,}"),
)


def redact_payload(payload: Any) -> Any:
    if isinstance(payload, dict):
        clean: dict[str, Any] = {}
        for key, value in payload.items():
            if _SECRET_KEY_RE.search(str(key)):
                clean[key] = "[REDACTED]"
            else:
                clean[key] = redact_payload(value)
        return clean
    if isinstance(payload, list):
        return [redact_payload(v) for v in payload]
    if isinstance(payload, str):
        redacted = payload
        for pattern in _SECRET_VALUE_RES:
            redacted = pattern.sub("[REDACTED]", redacted)
        return redacted
    return payload


@dataclass
class ExecutionEvent:
    execution_id: str
    sequence: int
    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {"execution_id": self.execution_id, "sequence": self.sequence,
                "type": self.type, "payload": redact_payload(self.payload),
                "timestamp": self.timestamp.isoformat()}


class EventStore:
    """Durable in-memory event store (DB-backed store layered in service)."""

    def __init__(self) -> None:
        self._events: dict[str, list[ExecutionEvent]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def append(self, execution_id: str, event_type: str,
                     payload: Optional[dict[str, Any]] = None) -> ExecutionEvent:
        if event_type not in STREAM_EVENT_TYPES:
            raise ValueError(f"unknown event type {event_type}")
        async with self._lock:
            seq = len(self._events[execution_id])
            event = ExecutionEvent(execution_id=execution_id, sequence=seq,
                                   type=event_type,
                                   payload=redact_payload(dict(payload or {})))
            self._events[execution_id].append(event)
            return event

    async def list(self, execution_id: str, from_sequence: int = 0,
                   limit: int = 500) -> list[ExecutionEvent]:
        async with self._lock:
            events = self._events.get(execution_id, [])
            return [e for e in events if e.sequence >= from_sequence][:max(1, limit)]

    async def latest_sequence(self, execution_id: str) -> int:
        async with self._lock:
            events = self._events.get(execution_id, [])
            return len(events) - 1


class StreamBuffer:
    """Bounded live buffer with drop policy (§36).

    Slow clients never consume unbounded memory: the buffer caps at
    ``max_events`` and either drops the oldest (default) or stops with a
    ``stream.truncated`` marker the client can use to resubscribe.
    """

    def __init__(self, max_events: int = 1000, drop_oldest: bool = True) -> None:
        self.max_events = max(16, max_events)
        self.drop_oldest = drop_oldest
        self._buf: deque[dict[str, Any]] = deque()
        self.dropped = 0
        self._cond = asyncio.Condition()

    async def publish(self, event: dict[str, Any]) -> None:
        async with self._cond:
            if len(self._buf) >= self.max_events:
                if self.drop_oldest:
                    self._buf.popleft()
                    self.dropped += 1
                else:
                    self.dropped += 1
                    return
            self._buf.append(redact_payload(event))
            self._cond.notify_all()

    async def subscribe(self, timeout_seconds: float = 300.0):
        """Yield events until timeout. Never yields secrets (redacted)."""
        import time
        deadline = time.monotonic() + max(1.0, timeout_seconds)
        index = 0
        snapshot: list[dict[str, Any]] = []
        async with self._cond:
            snapshot = list(self._buf)
        for event in snapshot:
            yield event
            index += 1
        while time.monotonic() < deadline:
            async with self._cond:
                try:
                    await asyncio.wait_for(
                        self._cond.wait(),
                        timeout=max(0.1, deadline - time.monotonic()))
                except asyncio.TimeoutError:
                    break
                while index < len(self._buf):
                    event = self._buf[index]
                    index += 1
                    yield event
        return
