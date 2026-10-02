"""MP25: provider-neutral infrastructure abstractions (§48).

The core execution logic depends only on these ABCs. Concrete adapters
(Redis queue, filesystem/S3-compatible storage, etc.) live behind them
so future AWS/GCP/Azure/Cloudflare/Hetzner adapters slot in without
rewriting execution logic.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Optional


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------- compute ---
@dataclass
class ComputeRequest:
    execution_id: str
    organization_id: str
    execution_class: str
    cpu_millicores: int = 500
    memory_mb: int = 512
    timeout_seconds: int = 600
    region_id: str = "local-1"
    pool_id: str = "default"
    labels: dict[str, str] = field(default_factory=dict)


@dataclass
class ComputeHandle:
    handle_id: str
    worker_id: str
    region_id: str
    started_at: datetime = field(default_factory=_utcnow)


class ComputeProvider(abc.ABC):
    @abc.abstractmethod
    async def launch(self, request: ComputeRequest) -> ComputeHandle: ...

    @abc.abstractmethod
    async def terminate(self, handle_id: str) -> None: ...

    @abc.abstractmethod
    async def describe(self, handle_id: str) -> Optional[ComputeHandle]: ...


# ------------------------------------------------------------------ queue ---
@dataclass
class CloudMessage:
    message_id: str
    queue: str
    execution_id: str
    organization_id: str
    priority: str
    payload: dict[str, Any]
    attempt: int = 0
    created_at: datetime = field(default_factory=_utcnow)
    visible_at: datetime = field(default_factory=_utcnow)


class QueueProvider(abc.ABC):
    """Durable queue abstraction (Redis/Postgres today; Kafka/SQS later)."""

    @abc.abstractmethod
    async def publish(self, queue: str, message: CloudMessage) -> str: ...

    @abc.abstractmethod
    async def claim(self, queue: str, worker_id: str,
                    visibility_seconds: int = 300) -> Optional[CloudMessage]: ...

    @abc.abstractmethod
    async def ack(self, queue: str, message_id: str, worker_id: str) -> None: ...

    @abc.abstractmethod
    async def nack(self, queue: str, message_id: str, worker_id: str,
                   delay_seconds: int = 60) -> None: ...

    @abc.abstractmethod
    async def depth(self, queue: str) -> int: ...

    @abc.abstractmethod
    async def oldest_age_seconds(self, queue: str) -> float: ...

    @abc.abstractmethod
    async def dead_letter(self, queue: str, message_id: str,
                          reason: str) -> None: ...


# ---------------------------------------------------------- object storage ---
@dataclass
class StoredObject:
    key: str
    size: int
    checksum: str
    mime_type: str
    created_at: datetime = field(default_factory=_utcnow)
    metadata: dict[str, str] = field(default_factory=dict)


class ObjectStorageProvider(abc.ABC):
    """Provider-neutral object storage (§29-30)."""

    @abc.abstractmethod
    async def put(self, key: str, data: bytes, mime_type: str,
                  metadata: Optional[dict[str, str]] = None) -> StoredObject: ...

    @abc.abstractmethod
    async def put_stream(self, key: str, stream: AsyncIterator[bytes],
                         mime_type: str,
                         metadata: Optional[dict[str, str]] = None) -> StoredObject: ...

    @abc.abstractmethod
    async def get(self, key: str) -> Optional[bytes]: ...

    @abc.abstractmethod
    async def get_stream(self, key: str) -> Optional[AsyncIterator[bytes]]: ...

    @abc.abstractmethod
    async def delete(self, key: str) -> bool: ...

    @abc.abstractmethod
    async def exists(self, key: str) -> bool: ...

    @abc.abstractmethod
    async def list(self, prefix: str = "", limit: int = 100,
                   cursor: str = "") -> tuple[list[StoredObject], str]: ...

    @abc.abstractmethod
    async def presigned_url(self, key: str, expires_seconds: int = 3600,
                            method: str = "GET") -> str: ...

    @abc.abstractmethod
    async def copy(self, src_key: str, dst_key: str) -> StoredObject: ...

    @abc.abstractmethod
    async def metadata(self, key: str) -> Optional[StoredObject]: ...


# --------------------------------------------------------------- database ---
class DatabaseProvider(abc.ABC):
    @abc.abstractmethod
    async def ping(self) -> bool: ...

    @abc.abstractmethod
    async def in_transaction(self): ...


# ------------------------------------------------------------------ cache ---
class CacheProvider(abc.ABC):
    @abc.abstractmethod
    async def get(self, key: str) -> Optional[str]: ...

    @abc.abstractmethod
    async def set(self, key: str, value: str, ttl_seconds: int = 300) -> None: ...

    @abc.abstractmethod
    async def delete(self, key: str) -> None: ...

    @abc.abstractmethod
    async def acquire_lock(self, key: str, owner: str,
                           ttl_seconds: int = 30) -> bool: ...

    @abc.abstractmethod
    async def release_lock(self, key: str, owner: str) -> bool: ...


# ----------------------------------------------------------------- secret ---
class SecretProvider(abc.ABC):
    """Secrets never enter prompts/logs/metrics/events/artifacts (§49)."""

    @abc.abstractmethod
    async def get(self, ref: str) -> Optional[str]: ...

    @abc.abstractmethod
    async def put(self, ref: str, value: str) -> None: ...

    @abc.abstractmethod
    async def delete(self, ref: str) -> None: ...

    @abc.abstractmethod
    async def exists(self, ref: str) -> bool: ...


# --------------------------------------------------------------- container ---
@dataclass
class ContainerSpec:
    image: str
    command: list[str]
    env_refs: dict[str, str] = field(default_factory=dict)
    cpu_millicores: int = 500
    memory_mb: int = 512
    network_policy: str = "NO_NETWORK"


class ContainerProvider(abc.ABC):
    @abc.abstractmethod
    async def run(self, spec: ContainerSpec) -> str: ...

    @abc.abstractmethod
    async def stop(self, container_id: str) -> None: ...

    @abc.abstractmethod
    async def logs(self, container_id: str, tail: int = 1000) -> str: ...


# ---------------------------------------------------------------- network ---
class NetworkProvider(abc.ABC):
    @abc.abstractmethod
    async def check_egress(self, url: str, policy: str) -> tuple[bool, str]:
        """Return (allowed, reason) for an outbound URL under a policy."""
