"""MP28: package signing + verification (§54-55).

Ed25519 (established primitive via `cryptography`) over the canonical
package digest. Key rotation via key_ids; revocation enforced at verify
time. SBOM + provenance helpers live in packaging.py.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from dataclasses import dataclass


def _ed25519():
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey,
            Ed25519PublicKey,
        )
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "package signing requires the 'cryptography' package"
        ) from exc
    return Ed25519PrivateKey, Ed25519PublicKey


@dataclass(frozen=True)
class KeyPair:
    key_id: str
    private_pem: str
    public_pem: str


def generate_keypair(key_id: str = "") -> KeyPair:
    Ed25519PrivateKey, _ = _ed25519()
    from cryptography.hazmat.primitives import serialization

    private = Ed25519PrivateKey.generate()
    public = private.public_key()
    kid = key_id or f"ed25519-{secrets.token_hex(4)}"
    return KeyPair(
        key_id=kid,
        private_pem=private.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode(),
        public_pem=public.public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode(),
    )


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sign_digest(digest_hex: str, private_pem: str, key_id: str) -> dict:
    """Sign a hex digest; returns signature metadata (no crypto invented)."""
    Ed25519PrivateKey, _ = _ed25519()
    from cryptography.hazmat.primitives import serialization

    private = serialization.load_pem_private_key(private_pem.encode(), password=None)
    assert isinstance(private, Ed25519PrivateKey)
    signature = private.sign(bytes.fromhex(digest_hex))
    return {
        "key_id": key_id,
        "algorithm": "ed25519",
        "digest_sha256": digest_hex,
        "signature_b64": base64.b64encode(signature).decode(),
    }


def verify_digest(
    digest_hex: str,
    signature_b64: str,
    public_pem: str,
    *,
    revoked_key_ids: frozenset[str] = frozenset(),
    key_id: str = "",
) -> bool:
    """Return True iff the signature is valid and the key is not revoked."""
    if key_id and key_id in revoked_key_ids:
        return False
    _, Ed25519PublicKey = _ed25519()
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import serialization

    public = serialization.load_pem_public_key(public_pem.encode())
    assert isinstance(public, Ed25519PublicKey)
    try:
        signature = base64.b64decode(signature_b64)
        public.verify(signature, bytes.fromhex(digest_hex))
        return True
    except (InvalidSignature, ValueError):
        return False


def canonical_digest(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256_hex(raw)
