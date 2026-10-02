"""MP25: distributed leases (§12) + distributed locks (§15).

Every distributed execution uses a lease (execution/worker/sandbox).
Leases carry owner/version/expiry; mutation requires ownership +
version match (optimistic concurrency) so two workers can never hold
the same exclusive task simultaneously.

Backends: in-memory (tests/dev) and Redis (production). Postgres
row-version leases back critical scheduler paths via ``SchedulerLease``.
"""

from __future__ import annotations

import abc
import asyncio
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from openagent.cloud.errors import LeaseConflict


@dataclass
class Lease:
    lease_id: str
    resource: str
    owner_id: str
    version: int = 1
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    renewed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def expired(self, now: Optional[datetime] = None) -> bool:
        moment = now or datetime.now(timezone.utc)
        return moment >= self.expires_at


class LeaseBackend(abc.ABC):
    @abc.abstractmethod
    async def acquire(self, resource: str, owner_id: str,
                      ttl_seconds: int) -> Lease: ...

    @abc.abstractmethod
    async def renew(self, lease: Lease, ttl_seconds: int) -> Lease: ...

    @abc.abstractmethod
    async def release(self, lease: Lease) -> None: ...

    @abc.abstractmethod
    async def get(self, resource: str) -> Optional[Lease]: ...


class InMemoryLeaseBackend(LeaseBackend):
    def __init__(self) -> None:
        self._leases: dict[str, Lease] = {}
        self._lock = asyncio.Lock()

    async def acquire(self, resource: str, owner_id: str, ttl_seconds: int) -> Lease:
        from datetime import timedelta
        async with self._lock:
            now = datetime.now(timezone.utc)
            existing = self._leases.get(resource)
            if existing is not None and not existing.expired(now):
                raise LeaseConflict(f"resource {resource} leased by {existing.owner_id}")
            version = (existing.version + 1) if existing else 1
            lease = Lease(lease_id=f"lse_{uuid.uuid4().hex[:12]}",
                          resource=resource, owner_id=owner_id,
                          version=version, created_at=now, renewed_at=now,
                          expires_at=now + timedelta(seconds=max(1, ttl_seconds)))
            self._leases[resource] = lease
            return lease

    async def renew(self, lease: Lease, ttl_seconds: int) -> Lease:
        from datetime import timedelta
        async with self._lock:
            now = datetime.now(timezone.utc)
            current = self._leases.get(lease.resource)
            if current is None or current.lease_id != lease.lease_id:
                raise LeaseConflict(f"lease {lease.lease_id} no longer held")
            if current.owner_id != lease.owner_id:
                raise LeaseConflict("lease owner mismatch")
            if current.version != lease.version:
                raise LeaseConflict("lease version mismatch")
            if current.expired(now):
                raise LeaseConflict("lease already expired")
            current.version += 1
            current.renewed_at = now
            current.expires_at = now + timedelta(seconds=max(1, ttl_seconds))
            lease.version = current.version
            lease.renewed_at = current.renewed_at
            lease.expires_at = current.expires_at
            return lease

    async def release(self, lease: Lease) -> None:
        async with self._lock:
            current = self._leases.get(lease.resource)
            if current is not None and current.lease_id == lease.lease_id:
                if current.owner_id == lease.owner_id:
                    del self._leases[lease.resource]

    async def get(self, resource: str) -> Optional[Lease]:
        async with self._lock:
            return self._leases.get(resource)


class RedisLeaseBackend(LeaseBackend):
    """Redis lease backend. Uses SET NX + ownership/version checks."""

    def __init__(self, redis_client, key_prefix: str = "oa:cloud:lease") -> None:
        self.redis = redis_client
        self.key_prefix = key_prefix

    def _key(self, resource: str) -> str:
        return f"{self.key_prefix}:{resource}"

    async def acquire(self, resource: str, owner_id: str, ttl_seconds: int) -> Lease:
        import json
        from datetime import timedelta
        now = datetime.now(timezone.utc)
        key = self._key(resource)
        raw = await self.redis.get(key)
        if raw is not None:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            data = json.loads(raw)
            expires = datetime.fromisoformat(data["expires_at"])
            if now < expires:
                raise LeaseConflict(f"resource {resource} leased by {data['owner_id']}")
            version = int(data.get("version", 0)) + 1
        else:
            version = 1
        lease = Lease(lease_id=f"lse_{uuid.uuid4().hex[:12]}", resource=resource,
                      owner_id=owner_id, version=version, created_at=now,
                      renewed_at=now,
                      expires_at=now + timedelta(seconds=max(1, ttl_seconds)))
        payload = json.dumps({"lease_id": lease.lease_id, "owner_id": owner_id,
                              "version": version, "created_at": now.isoformat(),
                              "renewed_at": now.isoformat(),
                              "expires_at": lease.expires_at.isoformat()})
        await self.redis.set(key, payload, ex=max(1, ttl_seconds + 5))
        return lease

    async def renew(self, lease: Lease, ttl_seconds: int) -> Lease:
        import json
        from datetime import timedelta
        now = datetime.now(timezone.utc)
        key = self._key(lease.resource)
        raw = await self.redis.get(key)
        if raw is None:
            raise LeaseConflict(f"lease {lease.lease_id} no longer held")
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        data = json.loads(raw)
        if data.get("lease_id") != lease.lease_id:
            raise LeaseConflict("lease superseded")
        if data.get("owner_id") != lease.owner_id:
            raise LeaseConflict("lease owner mismatch")
        if int(data.get("version", 0)) != lease.version:
            raise LeaseConflict("lease version mismatch")
        if now >= datetime.fromisoformat(data["expires_at"]):
            raise LeaseConflict("lease already expired")
        version = lease.version + 1
        expires = now + timedelta(seconds=max(1, ttl_seconds))
        payload = json.dumps({"lease_id": lease.lease_id, "owner_id": lease.owner_id,
                              "version": version, "created_at": data.get("created_at"),
                              "renewed_at": now.isoformat(),
                              "expires_at": expires.isoformat()})
        await self.redis.set(key, payload, ex=max(1, ttl_seconds + 5))
        lease.version = version
        lease.renewed_at = now
        lease.expires_at = expires
        return lease

    async def release(self, lease: Lease) -> None:
        import json
        key = self._key(lease.resource)
        raw = await self.redis.get(key)
        if raw is None:
            return
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        try:
            data = json.loads(raw)
        except ValueError:
            return
        if data.get("lease_id") == lease.lease_id and data.get("owner_id") == lease.owner_id:
            await self.redis.delete(key)

    async def get(self, resource: str) -> Optional[Lease]:
        import json
        raw = await self.redis.get(self._key(resource))
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        data = json.loads(raw)
        return Lease(lease_id=data["lease_id"], resource=resource,
                     owner_id=data["owner_id"], version=int(data.get("version", 1)),
                     created_at=datetime.fromisoformat(data["created_at"]),
                     renewed_at=datetime.fromisoformat(data["renewed_at"]),
                     expires_at=datetime.fromisoformat(data["expires_at"]))


# ---------------------------------------------------------- distributed lock ---
class DistributedLock(abc.ABC):
    @abc.abstractmethod
    async def acquire(self, ttl_seconds: int = 30) -> bool: ...

    @abc.abstractmethod
    async def renew(self, ttl_seconds: int = 30) -> bool: ...

    @abc.abstractmethod
    async def release(self) -> None: ...


class InMemoryDistributedLock(DistributedLock):
    """Scoped in-memory lock (single process). Never a global lock."""

    _registry: dict[str, tuple[str, float]] = {}
    _guard = asyncio.Lock()

    def __init__(self, name: str, owner: str) -> None:
        self.name = name
        self.owner = owner

    async def acquire(self, ttl_seconds: int = 30) -> bool:
        async with InMemoryDistributedLock._guard:
            now = time.time()
            holder = InMemoryDistributedLock._registry.get(self.name)
            if holder is not None:
                owner, deadline = holder
                if owner != self.owner and deadline > now:
                    return False
            InMemoryDistributedLock._registry[self.name] = (
                self.owner, now + max(1, ttl_seconds))
            return True

    async def renew(self, ttl_seconds: int = 30) -> bool:
        async with InMemoryDistributedLock._guard:
            holder = InMemoryDistributedLock._registry.get(self.name)
            if holder is None or holder[0] != self.owner:
                return False
            InMemoryDistributedLock._registry[self.name] = (
                self.owner, time.time() + max(1, ttl_seconds))
            return True

    async def release(self) -> None:
        async with InMemoryDistributedLock._guard:
            holder = InMemoryDistributedLock._registry.get(self.name)
            if holder is not None and holder[0] == self.owner:
                del InMemoryDistributedLock._registry[self.name]


class RedisDistributedLock(DistributedLock):
    """Redis lock with ownership validation (no abandoned-lock takeover)."""

    def __init__(self, redis_client, name: str, owner: str,
                 key_prefix: str = "oa:cloud:lock") -> None:
        self.redis = redis_client
        self.key = f"{key_prefix}:{name}"
        self.owner = owner

    async def acquire(self, ttl_seconds: int = 30) -> bool:
        result = await self.redis.set(self.key, self.owner, ex=max(1, ttl_seconds), nx=True)
        return bool(result)

    async def renew(self, ttl_seconds: int = 30) -> bool:
        current = await self.redis.get(self.key)
        if current is None:
            return False
        if isinstance(current, bytes):
            current = current.decode("utf-8")
        if current != self.owner:
            return False
        await self.redis.expire(self.key, max(1, ttl_seconds))
        return True

    async def release(self) -> None:
        current = await self.redis.get(self.key)
        if current is None:
            return
        if isinstance(current, bytes):
            current = current.decode("utf-8")
        if current == self.owner:
            await self.redis.delete(self.key)


def get_lease_backend(kind: str = "memory", redis_client=None) -> LeaseBackend:
    if kind == "redis":
        if redis_client is None:
            raise ValueError("redis lease backend requires a client")
        return RedisLeaseBackend(redis_client)
    return InMemoryLeaseBackend()
