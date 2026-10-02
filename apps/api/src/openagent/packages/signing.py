"""MP22: package hashing + signing foundation.

Pipeline: canonical serialization -> sha256 hash -> signature -> verify.

- :func:`canonicalize` produces stable JSON bytes (sorted keys, compact
  separators, UTF-8) so hashes are reproducible across runtimes.
- :func:`content_hash` hashes a manifest/resource payload dict.
- :class:`HmacSigner` provides a symmetric signing provider suitable for
  self-hosted / organization signing.
- :class:`Ed25519Signer` provides asymmetric signatures when the
  ``cryptography`` package is available (it is a backend dependency).
- :class:`SignatureVerifier` verifies against a registry of trusted keys
  without requiring any centralized marketplace.

Secrets must never be part of signed content; callers are expected to hash
the *export-safe* (secret-stripped) payload — enforced in packaging.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any, Protocol


def canonicalize(payload: dict[str, Any]) -> bytes:
    """Deterministic JSON serialization for hashing/signing."""
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def content_hash(payload: dict[str, Any], algorithm: str = "sha256") -> str:
    """Hex digest of the canonical form of ``payload``."""
    if algorithm != "sha256":
        raise ValueError(f"unsupported hash algorithm: {algorithm!r}")
    return hashlib.sha256(canonicalize(payload)).hexdigest()


def verify_content_hash(payload: dict[str, Any], expected: str) -> bool:
    return hmac.compare_digest(content_hash(payload), expected)


class SigningProvider(Protocol):
    algorithm: str

    def sign(self, payload: dict[str, Any]) -> str:
        ...

    def verify(self, payload: dict[str, Any], signature: str) -> bool:
        ...


@dataclass
class HmacSigner:
    """Symmetric HMAC-SHA256 signing provider (self-host friendly)."""

    key: bytes
    key_id: str = "local-hmac"
    algorithm: str = "hmac-sha256"

    def sign(self, payload: dict[str, Any]) -> str:
        digest = hmac.new(self.key, canonicalize(payload), hashlib.sha256).digest()
        return base64.b64encode(digest).decode("ascii")

    def verify(self, payload: dict[str, Any], signature: str) -> bool:
        try:
            expected = base64.b64decode(signature.encode("ascii"))
        except Exception:
            return False
        actual = hmac.new(self.key, canonicalize(payload), hashlib.sha256).digest()
        return hmac.compare_digest(actual, expected)


@dataclass
class Ed25519Signer:
    """Asymmetric Ed25519 signing provider (publisher verification)."""

    private_bytes: bytes = b""
    public_bytes: bytes = b""
    key_id: str = "ed25519"
    algorithm: str = "ed25519"

    def _private_key(self) -> Any:  # pragma: no cover - thin wrapper
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey,
        )

        return Ed25519PrivateKey.from_private_bytes(self.private_bytes)

    def _public_key(self) -> Any:  # pragma: no cover - thin wrapper
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PublicKey,
        )

        if self.public_bytes:
            return Ed25519PublicKey.from_public_bytes(self.public_bytes)
        return self._private_key().public_key()

    def sign(self, payload: dict[str, Any]) -> str:
        signature = self._private_key().sign(canonicalize(payload))
        return base64.b64encode(signature).decode("ascii")

    def verify(self, payload: dict[str, Any], signature: str) -> bool:
        try:
            raw = base64.b64decode(signature.encode("ascii"))
            self._public_key().verify(raw, canonicalize(payload))
            return True
        except Exception:
            return False


@dataclass
class SignatureRecord:
    algorithm: str
    signature: str
    key_id: str
    signer: str = ""
    verified: bool = False


def verify_signature(
    payload: dict[str, Any],
    record: SignatureRecord,
    providers: list[SigningProvider],
) -> SignatureRecord:
    """Verify ``record`` against each provider; return updated record."""
    for provider in providers:
        if provider.algorithm != record.algorithm:
            continue
        try:
            if provider.verify(payload, record.signature):
                record.verified = True
                return record
        except Exception:
            continue
    record.verified = False
    return record


def sign_manifest(
    manifest: dict[str, Any], provider: SigningProvider, signer: str = ""
) -> SignatureRecord:
    """Sign an export-safe manifest dict and describe the signature."""
    return SignatureRecord(
        algorithm=provider.algorithm,
        signature=provider.sign(manifest),
        key_id=getattr(provider, "key_id", ""),
        signer=signer,
        verified=True,
    )
