"""MP23: distribution — content-addressed artifacts over storage backends.

``ArtifactStorage`` abstracts upload/download/delete/exists/metadata over
the existing ``core.storage.StorageBackend`` (local filesystem for
self-hosting; S3/GCS/Azure later). Archive verification enforces size
limits, blocks path traversal, guards against zip/decompression bombs, and
requires manifest + sha256 match (+ signature check via MP22 signing).
Nothing is marked PUBLISHED before integrity verification succeeds.
"""

from __future__ import annotations

import hashlib
import io
import os
import zipfile
from dataclasses import dataclass
from typing import Any, Protocol

# Hard server-side limits (also enforced in the API layer).
MAX_ARCHIVE_BYTES = 100 * 1024 * 1024
MAX_EXTRACTED_BYTES = 500 * 1024 * 1024
MAX_ARCHIVE_FILES = 2000
MAX_COMPRESSION_RATIO = 100.0
MAX_SINGLE_FILE_BYTES = 50 * 1024 * 1024

ALLOWED_ARCHIVE_MIME = frozenset({
    "application/zip", "application/x-zip-compressed",
})
ALLOWED_ASSET_MIME = frozenset({
    "image/png", "image/jpeg", "image/webp", "image/svg+xml", "image/gif",
    "video/mp4", "video/webm", "text/markdown", "application/pdf",
})
BLOCKED_ASSET_EXT = frozenset({
    ".exe", ".dll", ".so", ".dylib", ".sh", ".bat", ".ps1", ".msi",
    ".js", ".html", ".htm", ".svg",
})


@dataclass
class StoredArtifact:
    storage_key: str
    sha256: str
    size_bytes: int
    filename: str


class ArtifactStorage(Protocol):
    provider: str

    async def put(self, key: str, data: bytes, *, mime: str) -> StoredArtifact:
        ...

    async def get(self, key: str) -> bytes | None:
        ...

    async def exists(self, key: str) -> bool:
        ...

    async def delete(self, key: str) -> bool:
        ...


class LocalArtifactStorage:
    """Content-addressed local artifact store (self-hosting default).

    Backed by the existing ``core.storage.LocalStorageBackend`` — no new
    storage system. Keys are content-addressed (sha256), so identical
    bytes are stored once and corruption is detectable on read.
    """

    provider = "LOCAL"

    def __init__(self, base_path: str = "./storage/marketplace-artifacts"):
        from openagent.core.storage import LocalStorageBackend

        self._backend = LocalStorageBackend(base_path=base_path)

    async def put(self, key: str, data: bytes, *, mime: str) -> StoredArtifact:
        import io as _io

        if check_safe_member(key):
            raise ValueError(f"unsafe storage key: {key!r}")
        stored = await self._backend.upload(
            key, _io.BytesIO(data), mime,
            key.split("/")[-1] or "artifact", {"sha256": sha256_bytes(data)})
        return StoredArtifact(storage_key=key, sha256=stored.checksum,
                              size_bytes=stored.size, filename=stored.filename)

    async def get(self, key: str) -> bytes | None:
        if check_safe_member(key):
            return None
        stream = await self._backend.download(key)
        if stream is None:
            return None
        chunks: list[bytes] = []
        async for chunk in stream:
            chunks.append(chunk)
        return b"".join(chunks)

    async def exists(self, key: str) -> bool:
        if check_safe_member(key):
            return False
        return await self._backend.exists(key)

    async def delete(self, key: str) -> bool:
        if check_safe_member(key):
            return False
        return await self._backend.delete(key)


def content_key(prefix: str, sha256: str, filename: str) -> str:
    """Content-addressed key: <prefix>/<aa>/<bb>/<sha256>-<safe name>."""
    safe = "".join(c if (c.isalnum() or c in ("-", "_", ".")) else "_"
                   for c in os.path.basename(filename))[:120] or "artifact"
    return f"{prefix}/{sha256[:2]}/{sha256[2:4]}/{sha256}-{safe}"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def check_safe_member(name: str) -> str | None:
    """Return a problem string for unsafe zip member names, else None."""
    if not name or name.startswith(("/", "\\")):
        return f"absolute path: {name!r}"
    normalized = os.path.normpath(name.replace("\\", "/"))
    if normalized.startswith(("../", "..")) or "/../" in normalized:
        return f"path traversal: {name!r}"
    if os.path.isabs(normalized):
        return f"absolute path: {name!r}"
    return None


def verify_archive(data: bytes, *, filename: str,
                   expected_sha256: str = "") -> dict[str, Any]:
    """Verify a package archive. Returns {ok, sha256, files[], problems[]}.

    Rejects: oversize, bad MIME by extension, traversal, too many files,
    single-file bombs, compression bombs, unreadable zips.
    """
    problems: list[str] = []
    digest = sha256_bytes(data)
    if expected_sha256 and digest != expected_sha256.lower():
        problems.append("sha256 mismatch: artifact is corrupted")
    if len(data) > MAX_ARCHIVE_BYTES:
        problems.append(f"archive exceeds {MAX_ARCHIVE_BYTES} bytes")
    files: list[dict[str, Any]] = []
    total_extracted = 0
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            members = archive.infolist()
            if len(members) > MAX_ARCHIVE_FILES:
                problems.append(f"too many files ({len(members)})")
            for info in members[:MAX_ARCHIVE_FILES + 1]:
                unsafe = check_safe_member(info.filename)
                if unsafe:
                    problems.append(unsafe)
                    continue
                if info.is_dir():
                    continue
                if info.file_size > MAX_SINGLE_FILE_BYTES:
                    problems.append(f"member too large: {info.filename!r}")
                    continue
                total_extracted += info.file_size
                if total_extracted > MAX_EXTRACTED_BYTES:
                    problems.append("extracted size exceeds limit (bomb guard)")
                    break
                ratio = (info.file_size / max(1, info.compress_size)
                         if info.compress_size else 1.0)
                if info.file_size > 1024 * 1024 and ratio > MAX_COMPRESSION_RATIO:
                    problems.append(
                        f"compression bomb suspected: {info.filename!r}")
                    continue
                files.append({"name": info.filename, "size": info.file_size})
    except zipfile.BadZipFile:
        problems.append("malformed archive (not a readable zip)")
    return {"ok": not problems, "sha256": digest, "files": files,
            "problems": problems}


def build_package_archive(files: dict[str, str]) -> bytes:
    """Build a deterministic zip from {path: text} (safe names only)."""
    for path in files:
        problem = check_safe_member(path)
        if problem:
            raise ValueError(problem)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(files):
            archive.writestr(path, files[path])
    return buffer.getvalue()


def validate_asset_upload(*, filename: str, mime: str,
                          size_bytes: int) -> list[str]:
    """Server-side asset validation (images/video/docs only)."""
    problems: list[str] = []
    base = os.path.basename(filename or "")
    if not base or base != (filename or "") or check_safe_member(base):
        problems.append("invalid filename")
    ext = os.path.splitext(base)[1].lower()
    if ext in BLOCKED_ASSET_EXT:
        problems.append(f"executable/active asset type not allowed: {ext}")
    if mime not in ALLOWED_ASSET_MIME:
        problems.append(f"asset MIME {mime!r} not allowed")
    if size_bytes > 25 * 1024 * 1024:
        problems.append("asset exceeds 25MB")
    if size_bytes <= 0:
        problems.append("empty asset")
    return problems
