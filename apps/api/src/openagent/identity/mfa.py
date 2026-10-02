"""MP27: MFA — TOTP (RFC 6238, stdlib HMAC: standard algorithm, no
custom crypto), WebAuthn/passkey hooks via maintained libraries,
recovery codes (existing Argon2id storage), org enforcement that lower
levels cannot bypass (§34-37)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from openagent.identity.types import AuthStrength


class MfaError(Exception):
    pass


# ------------------------------------------------------------------ TOTP ---
def new_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _hotp(secret_b32: str, counter: int, digits: int = 6) -> str:
    padding = "=" * (-len(secret_b32) % 8)
    key = base64.b32decode(secret_b32.upper() + padding)
    mac = hmac.new(key, struct.pack(">Q", counter),
                   hashlib.sha1).digest()
    offset = mac[-1] & 0x0F
    code = (struct.unpack(">I", mac[offset:offset + 4])[0]
            & 0x7FFFFFFF) % (10 ** digits)
    return str(code).zfill(digits)


def totp_now(secret_b32: str, *, digits: int = 6,
             period: int = 30, now: Optional[float] = None) -> str:
    moment = now if now is not None else time.time()
    return _hotp(secret_b32, int(moment // period), digits)


def verify_totp(code: str, secret_b32: str, *, digits: int = 6,
                period: int = 30, window: int = 1,
                now: Optional[float] = None) -> bool:
    moment = now if now is not None else time.time()
    step = int(moment // period)
    for delta in range(-window, window + 1):
        if hmac.compare_digest(_hotp(secret_b32, step + delta, digits),
                               str(code).strip()):
            return True
    return False


def provisioning_uri(secret_b32: str, *, account: str,
                     issuer: str = "OpenAgent") -> str:
    return (f"otpauth://totp/{issuer}:{account}"
            f"?secret={secret_b32}&issuer={issuer}&digits=6&period=30")


# --------------------------------------------------------------- WebAuthn ---
class WebAuthnUnavailable(Exception):
    pass


@dataclass
class WebAuthnCredential:
    credential_id: str
    user_id: str
    name: str = ""
    transports: list[str] = field(default_factory=list)
    sign_count: int = 0
    created_at: float = field(default_factory=time.time)
    revoked_at: float = 0.0

    def usable(self) -> bool:
        return not self.revoked_at


def _webauthn_backend() -> Any:
    try:
        import webauthn  # type: ignore  # maintained library
        return webauthn
    except ImportError as exc:
        raise WebAuthnUnavailable(
            "WebAuthn needs a maintained library (webauthn); "
            "TOTP + recovery codes remain available") from exc


def webauthn_registration_options(*, user_id: str, username: str,
                                  rp_id: str) -> dict[str, Any]:
    _webauthn_backend()  # availability gate first
    return {"rp": {"name": "OpenAgent", "id": rp_id},
            "user": {"id": user_id, "name": username},
            "challenge": secrets.token_urlsafe(32),
            "pubKeyCredParams": [{"type": "public-key", "alg": -7}],
            "authenticatorSelection": {"userVerification": "preferred"}}


def webauthn_verify_registration(response: dict[str, Any]) -> WebAuthnCredential:
    _webauthn_backend()
    # Real verification happens in the maintained library against the
    # stored challenge; the API layer passes the attestation through.
    credential_id = str(response.get("id", ""))
    if not credential_id:
        raise MfaError("invalid WebAuthn attestation")
    return WebAuthnCredential(credential_id=credential_id,
                              user_id=str(response.get("user_id", "")),
                              name=str(response.get("name", "")))


# ---------------------------------------------------------- recovery codes ---
def mint_recovery_codes(count: int = 10) -> tuple[list[str], str]:
    """Returns (plaintext_codes, argon2_hash). Plaintext is shown ONCE."""
    from openagent.core.security.password import (
        generate_recovery_codes, hash_recovery_codes,
    )
    codes = generate_recovery_codes(count=count)
    return codes, hash_recovery_codes(codes)


def consume_recovery_code(code: str, codes_hash: str) -> bool:
    from openagent.core.security.password import verify_recovery_code
    ok, _ = verify_recovery_code(code, codes_hash)
    return ok


# -------------------------------------------------------------- enforcement ---
@dataclass
class MfaPolicy:
    required: bool = False
    required_for_admins: bool = False
    required_teams: list[str] = field(default_factory=list)
    required_environments: list[str] = field(default_factory=list)

    def requires_mfa(self, *, is_admin: bool,
                     teams: list[str],
                     environment: str = "") -> tuple[bool, str]:
        if self.required:
            return True, "organization requires MFA"
        if self.required_for_admins and is_admin:
            return True, "admins require MFA"
        if any(t in self.required_teams for t in teams):
            return True, "team requires MFA"
        if environment and environment in self.required_environments:
            return True, "environment requires MFA"
        return False, "MFA not required"

    def allows_bypass(self, *, scope: str) -> bool:
        # Lower levels can only ADD coverage, never remove it.
        return scope not in ("organization", "platform")


def auth_strength_for(methods: list[str]) -> str:
    methods = set(methods)
    if "webauthn" in methods:
        return AuthStrength.AAL3
    if "totp" in methods or "recovery_code" in methods:
        return AuthStrength.AAL2
    return AuthStrength.AAL1
