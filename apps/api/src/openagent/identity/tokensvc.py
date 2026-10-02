"""MP27: token service (§40). Every sensitive token carries expiry,
scope, issuer, audience, revocation (jti registry) and rotation. No
perpetual admin tokens. JWT verification reuses the OIDC validator so
issuer/audience/signature rules stay in one place."""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from openagent.identity.oidc import OidcConfig, mint_test_token


def _hash_token(token: str) -> str:
    import hashlib
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass
class TokenRecord:
    jti: str
    kind: str
    subject: str
    organization_id: str = ""
    scope: str = ""
    issuer: str = "openagent"
    audience: str = ""
    issued_at: float = field(default_factory=time.time)
    expires_at: float = 0.0
    revoked: bool = False
    rotated_to: str = ""

    def live(self, now: Optional[float] = None) -> tuple[bool, str]:
        moment = now if now is not None else time.time()
        if self.revoked:
            return False, "token revoked"
        if self.expires_at and moment >= self.expires_at:
            return False, "token expired"
        return True, "live"


DEFAULT_TTL = {
    "session": 7 * 24 * 3600, "access": 900, "refresh": 30 * 24 * 3600,
    "scim": 365 * 24 * 3600, "enrollment": 3600, "email": 24 * 3600,
    "reset": 3600, "invitation": 7 * 24 * 3600, "workload": 600,
}


class TokenService:
    def __init__(self, issuer: str = "openagent") -> None:
        self.issuer = issuer
        self._records: dict[str, TokenRecord] = {}

    def mint(self, kind: str, subject: str, *,
             organization_id: str = "", scope: str = "",
             audience: str = "", ttl_seconds: float = 0.0,
             perpetual: bool = False) -> tuple[str, TokenRecord]:
        from openagent.identity.types import TokenKind
        if kind not in TokenKind.ALL:
            raise ValueError(f"unknown token kind {kind}")
        if perpetual:
            # Perpetual admin tokens are never created by default.
            raise ValueError("perpetual tokens are not issued")
        ttl = ttl_seconds or DEFAULT_TTL.get(kind, 900)
        raw = f"oa_{kind}_{secrets.token_urlsafe(32)}"
        now = time.time()
        record = TokenRecord(
            jti=_hash_token(raw), kind=kind, subject=subject,
            organization_id=organization_id, scope=scope,
            issuer=self.issuer, audience=audience,
            issued_at=now, expires_at=now + ttl)
        self._records[record.jti] = record
        return raw, record

    def verify(self, raw: str, *, kind: str = "",
               audience: str = "",
               now: Optional[float] = None) -> TokenRecord:
        record = self._records.get(_hash_token(raw))
        if record is None:
            raise ValueError("unknown token")
        if kind and record.kind != kind:
            raise ValueError("token kind mismatch")
        ok, reason = record.live(now)
        if not ok:
            raise ValueError(reason)
        if audience and record.audience and record.audience != audience:
            raise ValueError("token audience mismatch")
        return record

    def revoke(self, raw: str) -> bool:
        record = self._records.get(_hash_token(raw))
        if record is None:
            return False
        record.revoked = True
        return True

    def rotate(self, raw: str) -> tuple[str, TokenRecord]:
        """Rotation: new token issued, old revoked atomically."""
        old = self.verify(raw)
        replacement, record = self.mint(
            old.kind, old.subject, organization_id=old.organization_id,
            scope=old.scope, audience=old.audience)
        old.revoked = True
        old.rotated_to = record.jti
        return replacement, record

    def mint_jwt(self, record: TokenRecord, secret: str,
                 extra_claims: Optional[dict[str, Any]] = None) -> str:
        claims = {"iss": record.issuer, "sub": record.subject,
                  "aud": record.audience or "openagent",
                  "iat": int(record.issued_at), "exp": int(record.expires_at),
                  "jti": record.jti, "scope": record.scope,
                  **(extra_claims or {})}
        return mint_test_token(claims, secret)

    def verify_jwt(self, token: str, *, secret: str,
                   audience: str = "") -> TokenRecord:
        from openagent.identity.oidc import validate_id_token
        config = OidcConfig(issuer=self.issuer,
                            client_id=audience or "openagent",
                            expected_alg="HS256", hs_secret=secret)
        claims = validate_id_token(token, config=config)
        record = self._records.get(str(claims.get("jti", "")))
        if record is None:
            raise ValueError("unknown token")
        ok, reason = record.live()
        if not ok:
            raise ValueError(reason)
        return record
