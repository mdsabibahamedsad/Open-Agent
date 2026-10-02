"""MP25: object storage providers (§29-30).

Baselines: filesystem (dev/single-host), in-memory fake (tests), and an
S3-compatible adapter (MinIO/AWS/R2/GCS-via-interop) that only imports
``boto3`` lazily so self-hosted installs never require cloud SDKs.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator, Optional

from openagent.cloud.errors import StorageError
from openagent.cloud.providers import ObjectStorageProvider, StoredObject


def _checksum(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ------------------------------------------------------------- fake store ---
class FakeObjectStorageProvider(ObjectStorageProvider):
    """Deterministic in-memory object storage for tests (§71)."""

    def __init__(self) -> None:
        self._objects: dict[str, tuple[bytes, StoredObject]] = {}
        self._lock = asyncio.Lock()

    async def put(self, key: str, data: bytes, mime_type: str,
                  metadata: Optional[dict[str, str]] = None) -> StoredObject:
        return await self.put_stream(key, self._one_shot(data), mime_type, metadata)

    async def _one_shot(self, data: bytes):
        yield data
        return

    async def put_stream(self, key: str, stream: AsyncIterator[bytes],
                         mime_type: str,
                         metadata: Optional[dict[str, str]] = None) -> StoredObject:
        chunks = []
        async for chunk in stream:
            chunks.append(chunk)
        data = b"".join(chunks)
        stored = StoredObject(key=key, size=len(data), checksum=_checksum(data),
                              mime_type=mime_type, created_at=_utcnow(),
                              metadata=dict(metadata or {}))
        async with self._lock:
            self._objects[key] = (data, stored)
        return stored

    async def get(self, key: str) -> Optional[bytes]:
        async with self._lock:
            entry = self._objects.get(key)
            return entry[0] if entry else None

    async def get_stream(self, key: str):
        data = await self.get(key)
        if data is None:
            return None

        async def _gen():
            for i in range(0, len(data), 65536):
                yield data[i:i + 65536]
        return _gen()

    async def delete(self, key: str) -> bool:
        async with self._lock:
            return self._objects.pop(key, None) is not None

    async def exists(self, key: str) -> bool:
        async with self._lock:
            return key in self._objects

    async def list(self, prefix: str = "", limit: int = 100,
                   cursor: str = "") -> tuple[list[StoredObject], str]:
        async with self._lock:
            keys = sorted(k for k in self._objects if k.startswith(prefix))
            if cursor:
                keys = [k for k in keys if k > cursor]
            page = keys[:max(1, limit)]
            items = [self._objects[k][1] for k in page]
            return items, (page[-1] if len(keys) > len(page) else "")

    async def presigned_url(self, key: str, expires_seconds: int = 3600,
                            method: str = "GET") -> str:
        token = hmac.new(b"fake-storage", key.encode(), hashlib.sha256).hexdigest()[:16]
        return f"memory://{key}?method={method}&expires={expires_seconds}&sig={token}"

    async def copy(self, src_key: str, dst_key: str) -> StoredObject:
        data = await self.get(src_key)
        if data is None:
            raise StorageError(f"object {src_key} not found")
        async with self._lock:
            _, src_meta = self._objects[src_key]
        return await self.put(dst_key, data, src_meta.mime_type, src_meta.metadata)

    async def metadata(self, key: str) -> Optional[StoredObject]:
        async with self._lock:
            entry = self._objects.get(key)
            return entry[1] if entry else None


# -------------------------------------------------------- filesystem store ---
class FilesystemObjectStorageProvider(ObjectStorageProvider):
    """Single-host filesystem baseline (dev/small self-hosted)."""

    def __init__(self, base_dir: str = "./storage/cloud") -> None:
        self.base = Path(base_dir).resolve()
        self.base.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        safe = Path(key)
        if safe.is_absolute() or ".." in safe.parts:
            raise StorageError("unsafe storage key")
        return self.base.joinpath(*safe.parts)

    async def put(self, key: str, data: bytes, mime_type: str,
                  metadata: Optional[dict[str, str]] = None) -> StoredObject:
        async def _gen():
            yield data
            return
        return await self.put_stream(key, _gen(), mime_type, metadata)

    async def put_stream(self, key: str, stream: AsyncIterator[bytes],
                         mime_type: str,
                         metadata: Optional[dict[str, str]] = None) -> StoredObject:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        hasher = hashlib.sha256()
        size = 0
        tmp = path.with_suffix(path.suffix + f".tmp-{uuid.uuid4().hex[:8]}")
        with open(tmp, "wb") as fh:
            async for chunk in stream:
                fh.write(chunk)
                hasher.update(chunk)
                size += len(chunk)
        os.replace(tmp, path)
        return StoredObject(key=key, size=size, checksum=hasher.hexdigest(),
                            mime_type=mime_type, created_at=_utcnow(),
                            metadata=dict(metadata or {}))

    async def get(self, key: str) -> Optional[bytes]:
        path = self._path(key)
        if not path.exists():
            return None
        with open(path, "rb") as fh:
            return fh.read()

    async def get_stream(self, key: str):
        path = self._path(key)
        if not path.exists():
            return None

        async def _gen():
            with open(path, "rb") as fh:
                while True:
                    chunk = fh.read(65536)
                    if not chunk:
                        break
                    yield chunk
        return _gen()

    async def delete(self, key: str) -> bool:
        path = self._path(key)
        if not path.exists():
            return False
        path.unlink()
        return True

    async def exists(self, key: str) -> bool:
        return self._path(key).exists()

    async def list(self, prefix: str = "", limit: int = 100,
                   cursor: str = "") -> tuple[list[StoredObject], str]:
        files = sorted(self.base.rglob("*"))
        items: list[StoredObject] = []
        for path in files:
            if not path.is_file():
                continue
            key = path.relative_to(self.base).as_posix()
            if prefix and not key.startswith(prefix):
                continue
            if cursor and key <= cursor:
                continue
            stat = path.stat()
            with open(path, "rb") as fh:
                digest = hashlib.sha256(fh.read()).hexdigest()
            items.append(StoredObject(key=key, size=stat.st_size, checksum=digest,
                                      mime_type="application/octet-stream",
                                      created_at=datetime.fromtimestamp(
                                          stat.st_mtime, tz=timezone.utc)))
            if len(items) >= max(1, limit):
                break
        next_cursor = items[-1].key if items else ""
        return items, next_cursor

    async def presigned_url(self, key: str, expires_seconds: int = 3600,
                            method: str = "GET") -> str:
        # Filesystem baseline has no external signer; the API mints signed
        # download tokens instead. This URL shape stays internal.
        return f"/api/v1/cloud/files/{key}?method={method}&expires={expires_seconds}"

    async def copy(self, src_key: str, dst_key: str) -> StoredObject:
        data = await self.get(src_key)
        if data is None:
            raise StorageError(f"object {src_key} not found")
        return await self.put(dst_key, data, "application/octet-stream")

    async def metadata(self, key: str) -> Optional[StoredObject]:
        path = self._path(key)
        if not path.exists():
            return None
        stat = path.stat()
        with open(path, "rb") as fh:
            digest = hashlib.sha256(fh.read()).hexdigest()
        return StoredObject(key=key, size=stat.st_size, checksum=digest,
                            mime_type="application/octet-stream",
                            created_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc))


# ------------------------------------------------------ S3-compatible store ---
@dataclass
class S3CompatibleConfig:
    bucket: str
    endpoint: str = ""
    region: str = "us-east-1"
    access_key: str = ""
    secret_key: str = ""


class S3CompatibleStorageProvider(ObjectStorageProvider):
    """S3-compatible storage (AWS S3, MinIO, R2, GCS interop).

    ``boto3`` is imported lazily so installs without cloud SDKs keep
    working; operations run in threads to avoid blocking the event loop.
    """

    def __init__(self, config: S3CompatibleConfig) -> None:
        if not config.bucket:
            raise ValueError("S3 bucket is required")
        self.config = config
        self._client = None

    def _client_or_raise(self):
        if self._client is None:
            try:
                import boto3  # type: ignore
            except ImportError as exc:
                raise StorageError("boto3 is required for S3-compatible storage") from exc
            kwargs: dict = {"region_name": self.config.region}
            if self.config.endpoint:
                kwargs["endpoint_url"] = self.config.endpoint
            if self.config.access_key:
                kwargs["aws_access_key_id"] = self.config.access_key
                kwargs["aws_secret_access_key"] = self.config.secret_key
            self._client = boto3.client("s3", **kwargs)
        return self._client

    async def put(self, key: str, data: bytes, mime_type: str,
                  metadata: Optional[dict[str, str]] = None) -> StoredObject:
        client = self._client_or_raise()
        loop = asyncio.get_running_loop()
        checksum = _checksum(data)

        def _do():
            client.put_object(Bucket=self.config.bucket, Key=key, Body=data,
                              ContentType=mime_type,
                              Metadata={k: str(v) for k, v in (metadata or {}).items()})
        await loop.run_in_executor(None, _do)
        return StoredObject(key=key, size=len(data), checksum=checksum,
                            mime_type=mime_type, created_at=_utcnow(),
                            metadata=dict(metadata or {}))

    async def put_stream(self, key: str, stream: AsyncIterator[bytes],
                         mime_type: str,
                         metadata: Optional[dict[str, str]] = None) -> StoredObject:
        chunks = []
        async for chunk in stream:
            chunks.append(chunk)
        return await self.put(key, b"".join(chunks), mime_type, metadata)

    async def get(self, key: str) -> Optional[bytes]:
        client = self._client_or_raise()
        loop = asyncio.get_running_loop()

        def _do():
            try:
                resp = client.get_object(Bucket=self.config.bucket, Key=key)
                return resp["Body"].read()
            except Exception as exc:
                if "NoSuchKey" in type(exc).__name__ or "404" in str(exc):
                    return None
                raise
        return await loop.run_in_executor(None, _do)

    async def get_stream(self, key: str):
        data = await self.get(key)
        if data is None:
            return None

        async def _gen():
            for i in range(0, len(data), 65536):
                yield data[i:i + 65536]
        return _gen()

    async def delete(self, key: str) -> bool:
        client = self._client_or_raise()
        loop = asyncio.get_running_loop()

        def _do():
            client.delete_object(Bucket=self.config.bucket, Key=key)
            return True
        return await loop.run_in_executor(None, _do)

    async def exists(self, key: str) -> bool:
        client = self._client_or_raise()
        loop = asyncio.get_running_loop()

        def _do():
            try:
                client.head_object(Bucket=self.config.bucket, Key=key)
                return True
            except Exception:
                return False
        return await loop.run_in_executor(None, _do)

    async def list(self, prefix: str = "", limit: int = 100,
                   cursor: str = "") -> tuple[list[StoredObject], str]:
        client = self._client_or_raise()
        loop = asyncio.get_running_loop()

        def _do():
            kwargs: dict = {"Bucket": self.config.bucket, "Prefix": prefix,
                            "MaxKeys": max(1, min(limit, 1000))}
            if cursor:
                kwargs["ContinuationToken"] = cursor
            return client.list_objects_v2(**kwargs)
        resp = await loop.run_in_executor(None, _do)
        items = [StoredObject(key=o["Key"], size=o.get("Size", 0),
                              checksum=o.get("ETag", "").strip('"'),
                              mime_type="application/octet-stream",
                              created_at=o.get("LastModified") or _utcnow())
                 for o in resp.get("Contents", [])]
        return items, (resp.get("NextContinuationToken", "")
                       if resp.get("IsTruncated") else "")

    async def presigned_url(self, key: str, expires_seconds: int = 3600,
                            method: str = "GET") -> str:
        client = self._client_or_raise()
        loop = asyncio.get_running_loop()
        operation = "get_object" if method.upper() == "GET" else "put_object"

        def _do():
            return client.generate_presigned_url(
                operation, Params={"Bucket": self.config.bucket, "Key": key},
                ExpiresIn=max(60, min(expires_seconds, 604800)))
        return await loop.run_in_executor(None, _do)

    async def copy(self, src_key: str, dst_key: str) -> StoredObject:
        client = self._client_or_raise()
        loop = asyncio.get_running_loop()

        def _do():
            client.copy_object(Bucket=self.config.bucket, Key=dst_key,
                               CopySource={"Bucket": self.config.bucket, "Key": src_key})
            head = client.head_object(Bucket=self.config.bucket, Key=dst_key)
            return head
        head = await loop.run_in_executor(None, _do)
        return StoredObject(key=dst_key, size=head.get("ContentLength", 0),
                            checksum=head.get("ETag", "").strip('"'),
                            mime_type=head.get("ContentType", "application/octet-stream"),
                            created_at=head.get("LastModified") or _utcnow())

    async def metadata(self, key: str) -> Optional[StoredObject]:
        client = self._client_or_raise()
        loop = asyncio.get_running_loop()

        def _do():
            try:
                return client.head_object(Bucket=self.config.bucket, Key=key)
            except Exception:
                return None
        head = await loop.run_in_executor(None, _do)
        if head is None:
            return None
        return StoredObject(key=key, size=head.get("ContentLength", 0),
                            checksum=head.get("ETag", "").strip('"'),
                            mime_type=head.get("ContentType", "application/octet-stream"),
                            created_at=head.get("LastModified") or _utcnow(),
                            metadata=dict(head.get("Metadata", {})))


def get_object_storage_provider(kind: str = "filesystem",
                                base_dir: str = "./storage/cloud",
                                s3_config: Optional[S3CompatibleConfig] = None
                                ) -> ObjectStorageProvider:
    kind = str(kind or "filesystem").lower()
    if kind in ("fake", "memory"):
        return FakeObjectStorageProvider()
    if kind in ("s3", "minio", "r2", "s3_compatible", "s3-compatible"):
        if s3_config is None:
            raise ValueError("S3-compatible storage requires a config")
        return S3CompatibleStorageProvider(s3_config)
    return FilesystemObjectStorageProvider(base_dir)
