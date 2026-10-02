"""MP24: provider-neutral registry client.

Architecture::

    RegistryClient -> RegistryProvider -> package metadata -> artifact
    -> integrity -> signature -> installation

Providers implemented here: ``local`` (offline directory / DB-backed),
``mock`` (deterministic, for tests), ``http`` (generic signed-HTTP mirror).
No vendor is hard-coded; the public registry URL comes from configuration.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field
from typing import Any, Protocol

from openagent.commerce.types import (
    REGISTRY_AUTHS,
    REGISTRY_STATUSES,
    REGISTRY_TRUST_RANK,
    REGISTRY_TYPES,
    RegistryAuth,
    RegistryStatus,
)


class RegistryError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class RegistryPackage:
    name: str
    version: str
    manifest: dict[str, Any] = field(default_factory=dict)
    artifact_sha256: str = ""
    signature_status: str = "UNKNOWN"
    publisher: str = ""
    deprecated: bool = False
    revoked: bool = False


class RegistryProvider(Protocol):
    name: str

    async def search(self, *, query: str, limit: int = 20) -> list[dict[str, Any]]:
        ...

    async def get_package(self, *, name: str) -> dict[str, Any]:
        ...

    async def get_version(self, *, name: str, version: str) -> RegistryPackage:
        ...

    async def download_artifact(self, *, name: str, version: str) -> bytes:
        ...

    async def publish_package(self, *, name: str, version: str,
                              payload: dict[str, Any]) -> dict[str, Any]:
        ...

    async def check_updates(self, *, name: str,
                            current_version: str) -> list[str]:
        ...

    async def verify_integrity(self, *, artifact: bytes,
                               expected_sha256: str) -> bool:
        ...

    async def verify_signature(self, *, artifact: bytes,
                               signature: str,
                               key_id: str = "") -> str:
        ...


def validate_registry_config(config: dict[str, Any]) -> list[str]:
    """Return human-readable problems (empty == valid)."""
    problems: list[str] = []
    if config.get("type") not in REGISTRY_TYPES:
        problems.append(f"unknown registry type: {config.get('type')!r}")
    if config.get("status", RegistryStatus.ACTIVE) not in REGISTRY_STATUSES:
        problems.append(f"unknown registry status: {config.get('status')!r}")
    auth = config.get("authentication", RegistryAuth.PUBLIC)
    if auth not in REGISTRY_AUTHS:
        problems.append(f"unknown registry auth: {auth!r}")
    if auth != RegistryAuth.PUBLIC and not config.get("credential_ref"):
        problems.append("non-public registry requires credential_ref "
                        "(never a plaintext secret)")
    if "secret" in config or "api_key" in config or "password" in config:
        problems.append("registry config must reference credentials via "
                        "credential_ref; plaintext secrets forbidden")
    return problems


def registry_usable(config: dict[str, Any]) -> tuple[bool, str]:
    if config.get("status", RegistryStatus.ACTIVE) != RegistryStatus.ACTIVE:
        return False, f"registry status {config.get('status')}"
    if config.get("enabled", True) is False:
        return False, "registry disabled"
    return True, "ok"


def trust_meets(registry_trust: str, minimum: str) -> bool:
    return REGISTRY_TRUST_RANK.get(str(registry_trust).upper(), 0) >= \
        REGISTRY_TRUST_RANK.get(str(minimum).upper(), 0)


def signature_policy_ok(*, policy: dict[str, Any],
                        signature_status: str) -> tuple[bool, str]:
    if policy.get("require_signed") and signature_status != "VALID":
        return False, "registry requires a VALID signature"
    blocked = {str(s).upper() for s in (policy.get("block_statuses") or [])}
    if str(signature_status).upper() in blocked:
        return False, f"signature status {signature_status} blocked"
    return True, "ok"


def verify_artifact_sha256(artifact: bytes, expected_sha256: str) -> bool:
    if not expected_sha256:
        return False
    actual = hashlib.sha256(artifact).hexdigest()
    return hmac.compare_digest(actual, expected_sha256.lower())


def mirror_chain(registry: dict[str, Any],
                 by_slug: dict[str, dict[str, Any]]) -> list[str]:
    chain: list[str] = []
    seen = {str(registry.get("slug", ""))}
    current = registry
    while current.get("mirror_of"):
        parent = str(current["mirror_of"])
        if parent in seen:
            chain.append(f"{parent} (cycle)")
            break
        seen.add(parent)
        chain.append(parent)
        current = by_slug.get(parent, {})
        if not current:
            break
    return chain


def cache_key(*, registry_slug: str, kind: str, name: str,
              version: str = "") -> str:
    raw = f"{registry_slug}|{kind}|{name}|{version}".encode()
    return hashlib.sha256(raw).hexdigest()


class LocalRegistryProvider:
    """Offline-first provider backed by an in-memory package map.

    The service layer populates it from ``commerce_registry_cache`` /
    downloaded artifacts, so self-hosted installs work with no network.
    """

    name = "local"

    def __init__(self, packages: dict[str, dict[str, Any]] | None = None):
        # name -> {"versions": {version: manifest}, "artifacts": {...}}
        self._packages: dict[str, dict[str, Any]] = packages or {}

    async def search(self, *, query: str, limit: int = 20) -> list[dict[str, Any]]:
        q = query.lower()
        out = [ {"name": n, "versions": sorted(v.get("versions", {}))}
                for n, v in self._packages.items() if q in n.lower() ]
        return out[: max(1, limit)]

    async def get_package(self, *, name: str) -> dict[str, Any]:
        entry = self._packages.get(name)
        if entry is None:
            raise RegistryError("NOT_FOUND", f"package {name} not in local registry")
        return {"name": name, "versions": sorted(entry.get("versions", {}))}

    async def get_version(self, *, name: str, version: str) -> RegistryPackage:
        entry = self._packages.get(name)
        manifest = (entry or {}).get("versions", {}).get(version)
        if manifest is None:
            raise RegistryError("NOT_FOUND", f"{name}@{version} not in local registry")
        return RegistryPackage(name=name, version=version, manifest=manifest)

    async def download_artifact(self, *, name: str, version: str) -> bytes:
        entry = self._packages.get(name, {}).get("artifacts", {}).get(version)
        if entry is None:
            raise RegistryError("NOT_FOUND", f"no local artifact {name}@{version}")
        return entry if isinstance(entry, bytes) else str(entry).encode()

    async def publish_package(self, *, name: str, version: str,
                              payload: dict[str, Any]) -> dict[str, Any]:
        entry = self._packages.setdefault(name, {"versions": {}, "artifacts": {}})
        entry["versions"][version] = payload.get("manifest", {})
        return {"name": name, "version": version, "published": True}

    async def check_updates(self, *, name: str,
                            current_version: str) -> list[str]:
        entry = self._packages.get(name, {})
        return sorted(v for v in entry.get("versions", {})
                      if v != current_version)

    async def verify_integrity(self, *, artifact: bytes,
                               expected_sha256: str) -> bool:
        return verify_artifact_sha256(artifact, expected_sha256)

    async def verify_signature(self, *, artifact: bytes,
                               signature: str,
                               key_id: str = "") -> str:
        # Local provider reports; real crypto lives in packages.signing.
        return "VALID" if signature else "MISSING"


class MockRegistryProvider(LocalRegistryProvider):
    """Deterministic mock cloud registry for tests (labelled test data)."""

    name = "mock"

    def __init__(self) -> None:
        super().__init__({
            "acme/support-agent": {
                "versions": {"1.0.0": {"name": "acme/support-agent",
                                       "version": "1.0.0",
                                       "test_fixture": True}},
                "artifacts": {"1.0.0": b"mock-artifact-bytes"},
            }
        })
