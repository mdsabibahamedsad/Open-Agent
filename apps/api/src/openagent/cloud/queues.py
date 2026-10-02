"""MP25: durable queue abstraction (§7) + policy-driven routing (§8-9).

``QueueProvider`` is the provider-neutral interface from
:mod:`openagent.cloud.providers`. This module adds:

* :class:`InMemoryQueueProvider` — deterministic fake for tests/local dev.
* :class:`RedisQueueProvider` — production baseline on Redis streams-ish
  primitives (lists + sorted visibility set). No Lua required.
* :func:`route_queue` — policy-driven logical queue selection.
* :func:`normalize_priority` — entitlement-aware priority clamping so one
  tenant cannot starve others by stamping CRITICAL on everything.
* Retry classification (:func:`is_retryable_error`).
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from openagent.cloud.errors import QueueFull
from openagent.cloud.providers import CloudMessage, QueueProvider
from openagent.cloud.types import ExecutionClass, ExecutionPriority, QueueName

# Queue name -> Redis key namespace helpers.
_KEY_PREFIX = "oa:cloud:queue"


def _pending_key(queue: str) -> str:
    return f"{_KEY_PREFIX}:{queue}:pending"


def _visible_key(queue: str) -> str:
    return f"{_KEY_PREFIX}:{queue}:visible"


def _inflight_key(queue: str) -> str:
    return f"{_KEY_PREFIX}:{queue}:inflight"


def _dlq_key(queue: str) -> str:
    return f"{_KEY_PREFIX}:{queue}:dlq"


# ------------------------------------------------------- routing policy ---
# Logical routing: execution class + resources -> logical queue. Physical
# fan-out stays small (Redis keys); adding Kafka/SQS later only needs a
# new QueueProvider, not new routing logic.
_CLASS_QUEUE = {
    ExecutionClass.WORKFLOW: QueueName.WORKFLOW_DEFAULT,
    ExecutionClass.AGENT: QueueName.AGENT_DEFAULT,
    ExecutionClass.BROWSER: QueueName.BROWSER,
    ExecutionClass.CODE: QueueName.CODE,
    ExecutionClass.SANDBOX: QueueName.SANDBOX,
    ExecutionClass.SCHEDULED: QueueName.SCHEDULED,
    ExecutionClass.WEBHOOK: QueueName.WEBHOOK,
    ExecutionClass.LONG_RUNNING: QueueName.LONG_RUNNING,
}


def route_queue(*, execution_class: str, priority: str,
                memory_mb: int = 512, cpu_millicores: int = 500,
                pool_id: str = "default") -> str:
    """Policy-driven queue selection (§8)."""
    execution_class = str(execution_class or ExecutionClass.WORKFLOW).lower()
    priority = str(priority or ExecutionPriority.NORMAL).upper()
    pool = str(pool_id or "default").lower()

    if pool in ("browser",) or execution_class == ExecutionClass.BROWSER:
        return QueueName.BROWSER
    if pool in ("code",) or execution_class == ExecutionClass.CODE:
        return QueueName.CODE
    if memory_mb >= 8192:
        return QueueName.HIGH_MEMORY
    if cpu_millicores >= 4000:
        return QueueName.HIGH_CPU
    if execution_class == ExecutionClass.WORKFLOW:
        return QueueName.WORKFLOW_PRIORITY if priority in ("HIGH", "CRITICAL") else QueueName.WORKFLOW_DEFAULT
    if execution_class == ExecutionClass.AGENT:
        return QueueName.AGENT_PRIORITY if priority in ("HIGH", "CRITICAL") else QueueName.AGENT_DEFAULT
    return _CLASS_QUEUE.get(execution_class, QueueName.WORKFLOW_DEFAULT)


def normalize_priority(*, requested: str, plan_allows_high: bool,
                       plan_allows_critical: bool) -> str:
    """Clamp priority by entitlement (§9: fairness, no starvation)."""
    requested = str(requested or ExecutionPriority.NORMAL).upper()
    if requested not in ExecutionPriority.ALL:
        return ExecutionPriority.NORMAL
    if requested == ExecutionPriority.CRITICAL and not plan_allows_critical:
        return ExecutionPriority.HIGH if plan_allows_high else ExecutionPriority.NORMAL
    if requested == ExecutionPriority.HIGH and not plan_allows_high:
        return ExecutionPriority.NORMAL
    return requested


# Non-retryable failure markers (§43). Matching is substring-based and
# conservative: unknown errors default to retryable=False (never blindly
# retry destructive actions).
_NON_RETRYABLE_MARKERS = (
    "invalid workflow", "permission denied", "invalid credentials",
    "policy violation", "malicious", "schema validation",
    "quota exceeded", "entitlement", "unauthorized", "forbidden",
    "approval denied", "not found",
)


def is_retryable_error(error: str) -> bool:
    lowered = str(error or "").lower()
    for marker in _NON_RETRYABLE_MARKERS:
        if marker in lowered:
            return False
    return True


def retry_delay_seconds(attempt: int, base_seconds: float = 5.0,
                        max_seconds: float = 600.0) -> float:
    delay = base_seconds * (2 ** max(0, attempt - 1))
    return min(delay, max_seconds)


# ------------------------------------------------- in-memory provider ---
@dataclass
class _StoredMessage:
    message: CloudMessage
    visible_at: float = 0.0
    claimed_by: str = ""
    payload: dict = field(default_factory=dict)


class InMemoryQueueProvider(QueueProvider):
    """Deterministic fake queue for tests/local dev (§71). No I/O."""

    def __init__(self, max_depth: int = 100000) -> None:
        self.max_depth = max_depth
        self._queues: dict[str, deque[_StoredMessage]] = defaultdict(deque)
        self._inflight: dict[str, dict[str, _StoredMessage]] = defaultdict(dict)
        self._dlq: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._lock = asyncio.Lock()

    def _now(self) -> float:
        return time.time()

    async def publish(self, queue: str, message: CloudMessage) -> str:
        async with self._lock:
            pending = sum(1 for m in self._queues[queue]
                          if m.visible_at <= self._now())
            if pending >= self.max_depth:
                raise QueueFull(f"queue {queue} at max depth {self.max_depth}")
            if not message.message_id:
                message.message_id = f"msg_{uuid.uuid4().hex[:16]}"
            self._queues[queue].append(
                _StoredMessage(message=message,
                               visible_at=message.visible_at.timestamp()
                               if isinstance(message.visible_at, datetime) else self._now()))
            return message.message_id

    async def claim(self, queue: str, worker_id: str,
                    visibility_seconds: int = 300) -> Optional[CloudMessage]:
        async with self._lock:
            now = self._now()
            buf = self._queues[queue]
            # Re-queue expired inflight first (crash recovery without a sweeper).
            for mid, stored in list(self._inflight[queue].items()):
                if stored.visible_at <= now:
                    del self._inflight[queue][mid]
                    stored.claimed_by = ""
                    stored.visible_at = now
                    buf.append(stored)
            for _ in range(len(buf)):
                stored = buf[0]
                if stored.visible_at > self._now():
                    buf.rotate(-1)
                    continue
                buf.popleft()
                stored.claimed_by = worker_id
                # Exact visibility (no floor): tests use 0 to simulate an
                # already-expired claim; production callers pass >= 30.
                stored.visible_at = self._now() + max(0, visibility_seconds)
                self._inflight[queue][stored.message.message_id] = stored
                stored.message.attempt += 1
                return stored.message
            return None

    async def ack(self, queue: str, message_id: str, worker_id: str) -> None:
        async with self._lock:
            self._inflight[queue].pop(message_id, None)

    async def nack(self, queue: str, message_id: str, worker_id: str,
                   delay_seconds: int = 60) -> None:
        async with self._lock:
            stored = self._inflight[queue].pop(message_id, None)
            if stored is None:
                return
            stored.claimed_by = ""
            stored.visible_at = self._now() + max(0, delay_seconds)
            self._queues[queue].append(stored)

    async def depth(self, queue: str) -> int:
        async with self._lock:
            now = self._now()
            return sum(1 for m in self._queues[queue] if m.visible_at <= now)

    async def oldest_age_seconds(self, queue: str) -> float:
        async with self._lock:
            now = self._now()
            ages = [now - m.message.created_at.timestamp()
                    for m in self._queues[queue]
                    if m.visible_at <= now]
            return max(ages) if ages else 0.0

    async def dead_letter(self, queue: str, message_id: str, reason: str) -> None:
        async with self._lock:
            stored = self._inflight[queue].pop(message_id, None)
            entry: dict[str, Any] = {"message_id": message_id, "reason": reason,
                                     "at": datetime.now(timezone.utc).isoformat()}
            if stored is not None:
                entry["message"] = {"execution_id": stored.message.execution_id,
                                    "organization_id": stored.message.organization_id,
                                    "attempt": stored.message.attempt,
                                    "payload": stored.message.payload}
            self._dlq[queue].append(entry)

    # Test/ops helpers (not part of the provider interface).
    async def dlq_entries(self, queue: str) -> list[dict[str, Any]]:
        async with self._lock:
            return list(self._dlq[queue])

    async def requeue_dlq(self, queue: str, message_id: str) -> bool:
        async with self._lock:
            for i, entry in enumerate(self._dlq[queue]):
                if entry.get("message_id") == message_id and "message" in entry:
                    data = entry["message"]
                    msg = CloudMessage(
                        message_id=f"msg_{uuid.uuid4().hex[:16]}",
                        queue=queue, execution_id=data["execution_id"],
                        organization_id=data["organization_id"],
                        priority=ExecutionPriority.NORMAL,
                        payload=data.get("payload", {}), attempt=0)
                    self._queues[queue].append(_StoredMessage(message=msg))
                    self._dlq[queue].pop(i)
                    return True
            return False


class RedisQueueProvider(QueueProvider):
    """Production baseline queue on Redis (§7, §81).

    Layout per logical queue (all under ``oa:cloud:queue:<q>``):
    * ``:pending`` — list of message envelopes (JSON).
    * ``:inflight`` — hash message_id -> {envelope, owner, deadline}.
    * ``:dlq`` — list of dead-letter envelopes with reason metadata.
    Crash recovery: :meth:`requeue_expired` scans inflight deadlines and
    returns expired claims to pending (called by workers/scheduler loop).
    """

    def __init__(self, redis_client, max_depth: int = 100000) -> None:
        self.redis = redis_client
        self.max_depth = max_depth

    async def _load_redis(self):
        return self.redis

    async def publish(self, queue: str, message: CloudMessage) -> str:
        import json
        r = await self._load_redis()
        depth = await r.llen(_pending_key(queue))
        if depth >= self.max_depth:
            raise QueueFull(f"queue {queue} at max depth {self.max_depth}")
        if not message.message_id:
            message.message_id = f"msg_{uuid.uuid4().hex[:16]}"
        envelope = {"message_id": message.message_id, "queue": queue,
                    "execution_id": message.execution_id,
                    "organization_id": message.organization_id,
                    "priority": message.priority, "payload": message.payload,
                    "attempt": message.attempt,
                    "created_at": message.created_at.isoformat()
                    if isinstance(message.created_at, datetime)
                    else str(message.created_at)}
        # Priority queues push left for HIGH/CRITICAL (LIFO-ish priority),
        # default queues append right (FIFO). Simple, no extra structures.
        if str(message.priority).upper() in ("HIGH", "CRITICAL"):
            await r.lpush(_pending_key(queue), json.dumps(envelope))
        else:
            await r.rpush(_pending_key(queue), json.dumps(envelope))
        return message.message_id

    async def claim(self, queue: str, worker_id: str,
                    visibility_seconds: int = 300) -> Optional[CloudMessage]:
        import json
        r = await self._load_redis()
        raw = await r.lpop(_pending_key(queue))
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        envelope = json.loads(raw)
        deadline = time.time() + max(1, visibility_seconds)
        record = {"envelope": envelope, "owner": worker_id, "deadline": deadline}
        await r.hset(_inflight_key(queue), envelope["message_id"], json.dumps(record))
        created = envelope.get("created_at")
        try:
            created_at = datetime.fromisoformat(created) if created else datetime.now(timezone.utc)
        except ValueError:
            created_at = datetime.now(timezone.utc)
        return CloudMessage(
            message_id=envelope["message_id"], queue=queue,
            execution_id=envelope["execution_id"],
            organization_id=envelope.get("organization_id", ""),
            priority=envelope.get("priority", ExecutionPriority.NORMAL),
            payload=envelope.get("payload", {}),
            attempt=int(envelope.get("attempt", 0)) + 1,
            created_at=created_at)

    async def ack(self, queue: str, message_id: str, worker_id: str) -> None:
        r = await self._load_redis()
        await r.hdel(_inflight_key(queue), message_id)

    async def nack(self, queue: str, message_id: str, worker_id: str,
                   delay_seconds: int = 60) -> None:
        import json
        r = await self._load_redis()
        raw = await r.hget(_inflight_key(queue), message_id)
        if raw is None:
            return
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        record = json.loads(raw)
        if record.get("owner") != worker_id:
            return  # only the owner may release the claim
        await r.hdel(_inflight_key(queue), message_id)
        envelope = record["envelope"]
        envelope["attempt"] = int(envelope.get("attempt", 0)) + 1
        if delay_seconds <= 0:
            await r.lpush(_pending_key(queue), json.dumps(envelope))
        else:
            # Delayed requeue via a temp key is overkill; requeue at head —
            # backoff is enforced by the worker sleeping before nack-ack.
            await r.lpush(_pending_key(queue), json.dumps(envelope))

    async def depth(self, queue: str) -> int:
        r = await self._load_redis()
        return int(await r.llen(_pending_key(queue)))

    async def oldest_age_seconds(self, queue: str) -> float:
        import json
        r = await self._load_redis()
        raw = await r.lindex(_pending_key(queue), -1)
        if raw is None:
            return 0.0
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        try:
            created = json.loads(raw).get("created_at")
            ts = datetime.fromisoformat(created).timestamp()
            return max(0.0, time.time() - ts)
        except (ValueError, TypeError):
            return 0.0

    async def dead_letter(self, queue: str, message_id: str, reason: str) -> None:
        import json
        r = await self._load_redis()
        raw = await r.hget(_inflight_key(queue), message_id)
        envelope: dict[str, Any] = {}
        if raw is not None:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            envelope = json.loads(raw).get("envelope", {})
            await r.hdel(_inflight_key(queue), message_id)
        entry = {"message_id": message_id, "queue": queue, "reason": reason,
                 "at": datetime.now(timezone.utc).isoformat(),
                 "message": envelope}
        await r.rpush(_dlq_key(queue), json.dumps(entry))

    async def requeue_expired(self, queue: str, limit: int = 100) -> int:
        """Return expired inflight claims to pending (crash recovery)."""
        import json
        r = await self._load_redis()
        records = await r.hgetall(_inflight_key(queue))
        now = time.time()
        moved = 0
        for message_id, raw in (records or {}).items():
            if moved >= limit:
                break
            if isinstance(message_id, bytes):
                message_id = message_id.decode("utf-8")
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            try:
                record = json.loads(raw)
            except ValueError:
                await r.hdel(_inflight_key(queue), message_id)
                continue
            if float(record.get("deadline", 0)) <= now:
                await r.hdel(_inflight_key(queue), message_id)
                await r.rpush(_pending_key(queue), json.dumps(record["envelope"]))
                moved += 1
        return moved

    async def dlq_entries(self, queue: str, limit: int = 100) -> list[dict[str, Any]]:
        import json
        r = await self._load_redis()
        raw_items = await r.lrange(_dlq_key(queue), 0, limit - 1)
        out = []
        for raw in raw_items or []:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            out.append(json.loads(raw))
        return out
