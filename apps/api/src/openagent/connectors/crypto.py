"""Credential cryptography (MP21).

Envelope encryption with Fernet (AES-128-CBC + HMAC-SHA256) keyed by the
platform ENCRYPTION_KEY via HKDF-SHA256 domain separation. Fail-closed:
no backend, no key, no storage. Masking helpers ensure secrets never reach
logs, models, or API responses.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from typing import Any

import structlog

logger = structlog.get_logger("openagent.connectors.crypto")


class CredentialCryptoError(Exception):
    def __init__(self, message: str, code: str = "CRYPTO_ERROR"):
        super().__init__(message)
        self.code = code


ENVELOPE_VERSION = "oa1"
_MASK_KEEP = 4


def derive_fernet_key(master_key: str, *, context: str = "connector-credentials-v1") -> bytes:
    """Derive a Fernet key from the platform master key (HKDF-SHA256)."""
    if not master_key or len(master_key) < 32:
        raise CredentialCryptoError("ENCRYPTION_KEY must be at least 32 chars",
                                    code="NO_KEY")
    prk = hmac.new(b"oa-hkdf-salt-v1", master_key.encode(),
                    hashlib.sha256).digest()
    okm = hmac.new(prk, context.encode() + b"\x01", hashlib.sha256).digest()
    return base64.urlsafe_b64encode(okm)


def _fernet(master_key: str):
    try:
        from cryptography.fernet import Fernet, InvalidToken
    except ImportError as exc:
        raise CredentialCryptoError("cryptography library unavailable",
                                    code="NO_BACKEND") from exc
    return Fernet(derive_fernet_key(master_key)), InvalidToken


def encrypt_secret(master_key: str, plaintext: str, *,
                   associated: str = "") -> str:
    """Encrypt to a versioned envelope. Associated org/credential id binds ciphertext."""
    if plaintext is None:
        raise CredentialCryptoError("Nothing to encrypt", code="EMPTY_SECRET")
    fernet, _ = _fernet(master_key)
    body = json.dumps({"v": ENVELOPE_VERSION, "aad": associated,
                       "data": plaintext}, separators=(",", ":")).encode()
    token = fernet.encrypt(body).decode()
    return f"{ENVELOPE_VERSION}.{token}"


def decrypt_secret(master_key: str, envelope: str, *,
                   associated: str = "") -> str:
    fernet, InvalidToken = _fernet(master_key)
    try:
        version, _, token = envelope.partition(".")
        if version != ENVELOPE_VERSION or not token:
            raise CredentialCryptoError("Unknown envelope version",
                                        code="BAD_ENVELOPE")
        body = json.loads(fernet.decrypt(token.encode()))
    except CredentialCryptoError:
        raise
    except InvalidToken as exc:
        raise CredentialCryptoError("Decryption failed (wrong key or tampered)",
                                    code="DECRYPT_FAILED") from exc
    except Exception as exc:
        raise CredentialCryptoError("Malformed envelope", code="BAD_ENVELOPE") from exc
    if body.get("v") != ENVELOPE_VERSION:
        raise CredentialCryptoError("Envelope version mismatch", code="BAD_ENVELOPE")
    stored_aad = str(body.get("aad", "") or "")
    # Binding is mandatory when the envelope carries it; callers that omit
    # `associated` cannot decrypt cross-credential blobs.
    if stored_aad and associated != stored_aad:
        raise CredentialCryptoError("Envelope binding mismatch (wrong credential scope)",
                                    code="BINDING_MISMATCH")
    return str(body.get("data", ""))


def needs_rotation_hint(encrypted: str) -> bool:
    """True when stored envelope predates the current version (rotate on read)."""
    version, _, _ = (encrypted or "").partition(".")
    return version != ENVELOPE_VERSION


def mask_secret(value: Any, *, keep: int = 0) -> str:
    """Mask for display: fully redacted by default. Empty stays empty."""
    text = str(value or "")
    if not text:
        return ""
    if keep and keep > 0:
        # Explicit opt-in only (e.g. non-secret prefixes); never the default.
        if len(text) <= keep:
            return "*" * len(text)
        return f"{'*' * 8}…{text[-keep:]}"
    return "••••••••"


def mask_credential_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a display-safe copy: every secret-bearing leaf masked."""
    from openagent.browser.security import redact_dict
    masked = redact_dict(payload or {})
    # redact_dict uses [REDACTED]; for credential display use bullets instead
    # only where a real value existed.
    def _walk(node: Any) -> Any:
        if isinstance(node, dict):
            return {k: _walk(v) for k, v in node.items()}
        if isinstance(node, list):
            return [_walk(v) for v in node]
        if isinstance(node, str) and node == "[REDACTED]":
            return "••••••••"
        return node
    return _walk(masked)


def generate_webhook_secret() -> tuple[str, str]:
    """Return (plaintext_once, sha256_hex_for_storage). Plaintext shown once."""
    raw = secrets.token_urlsafe(32)
    digest = hashlib.sha256(raw.encode()).hexdigest()
    return raw, digest
