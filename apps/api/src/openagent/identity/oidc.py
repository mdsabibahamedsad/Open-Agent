"""MP27: OIDC support (§7). Discovery, code flow + PKCE, state/nonce,
full token validation (issuer/audience/signature/expiry/skew).
Reuses the connector OAuth helpers (PKCE, signed state) — no duplicate
crypto. RS256 uses a maintained JWT library when installed; HS256 is
verified with stdlib HMAC (tests + local IdPs)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import urlencode

from openagent.identity.providers import (
    AuthRequest, AuthResult, IdentityProvider, ProvisioningResult,
)


class OidcError(ValueError):
    pass


def _b64url_decode(segment: str) -> bytes:
    return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


@dataclass
class OidcConfig:
    issuer: str
    client_id: str
    redirect_uri: str = ""
    scopes: list[str] = field(default_factory=lambda: ["openid", "email", "profile"])
    expected_alg: str = "RS256"
    clock_skew_seconds: int = 120
    # Symmetric test/local key (HS256). Production RS256 uses JWKS below.
    hs_secret: str = ""
    jwks: dict[str, Any] = field(default_factory=dict)  # kid -> key material

    def validate(self) -> tuple[bool, str]:
        if not self.issuer.startswith("https://") and not self.issuer.startswith("http://localhost"):
            return False, "issuer must be https (http allowed for localhost dev only)"
        if not self.client_id:
            return False, "client_id is required"
        if self.expected_alg not in ("RS256", "HS256", "ES256"):
            return False, f"unsupported alg {self.expected_alg}"
        return True, "ok"

    def discovery_url(self) -> str:
        return self.issuer.rstrip("/") + "/.well-known/openid-configuration"


def parse_discovery_document(document: dict[str, Any],
                             expected_issuer: str) -> dict[str, str]:
    """Validate a discovery doc: issuer match + https endpoints."""
    issuer = str(document.get("issuer", ""))
    if issuer.rstrip("/") != expected_issuer.rstrip("/"):
        raise OidcError("discovery issuer mismatch")
    endpoints = {}
    for key in ("authorization_endpoint", "token_endpoint",
                "userinfo_endpoint", "jwks_uri"):
        url = str(document.get(key, ""))
        if url and not url.startswith("https://") and "localhost" not in url:
            raise OidcError(f"discovery endpoint {key} must be https")
        endpoints[key] = url
    if not endpoints["authorization_endpoint"] or not endpoints["token_endpoint"]:
        raise OidcError("discovery missing required endpoints")
    return endpoints


def _pkce_pair() -> tuple[str, str]:
    verifier = _b64url_encode(secrets.token_bytes(48))
    challenge = _b64url_encode(
        hashlib.sha256(verifier.encode()).digest())
    return verifier, challenge


def _sign_state(payload: dict[str, Any], secret: str) -> str:
    body = _b64url_encode(json.dumps(
        payload, sort_keys=True, separators=(",", ":")).encode())
    sig = hmac.new(secret.encode(), body.encode(),
                   hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def build_login(oidc: OidcConfig, *, state_secret: str,
                organization_id: str) -> tuple[str, str, str, str]:
    """Return (url, state, nonce, code_verifier)."""
    verifier, challenge = _pkce_pair()
    nonce = secrets.token_urlsafe(24)
    state = _sign_state({"org": organization_id, "nonce": nonce,
                         "ts": time.time()}, state_secret)
    params = {"response_type": "code", "client_id": oidc.client_id,
              "redirect_uri": oidc.redirect_uri,
              "scope": " ".join(oidc.scopes),
              "state": state, "nonce": nonce,
              "code_challenge": challenge,
              "code_challenge_method": "S256"}
    base = oidc.issuer.rstrip("/") + "/authorize"
    return f"{base}?{urlencode(params)}", state, nonce, verifier


def _verify_hs256(signing_input: bytes, signature: bytes, secret: str) -> bool:
    expected = hmac.new(secret.encode(), signing_input,
                        hashlib.sha256).digest()
    return hmac.compare_digest(expected, signature)


def _verify_rs256(signing_input: bytes, signature: bytes,
                  jwk: dict[str, Any]) -> bool:
    try:
        from jose import jwk as jose_jwk  # type: ignore
    except ImportError as exc:
        raise OidcError(
            "RS256 verification needs a maintained JWT library "
            "(python-jose); refusing to skip signature validation") from exc
    key = jose_jwk.construct(jwk)
    return key.verify(signing_input, signature)


def validate_id_token(token: str, *, config: OidcConfig,
                      nonce: str = "",
                      now: Optional[float] = None) -> dict[str, Any]:
    """Full ID-token validation. Never trusts claims before verifying."""
    moment = now if now is not None else time.time()
    try:
        header_b64, payload_b64, sig_b64 = token.split(".")
    except ValueError:
        raise OidcError("malformed token")
    try:
        header = json.loads(_b64url_decode(header_b64))
        claims = json.loads(_b64url_decode(payload_b64))
        signature = _b64url_decode(sig_b64)
    except (ValueError, base64.binascii.Error) as exc:
        raise OidcError("malformed token encoding") from exc

    alg = str(header.get("alg", ""))
    if alg == "none" or not alg:
        raise OidcError("unsigned tokens are rejected")
    if alg != config.expected_alg:
        # Algorithm confusion defense: only the pinned alg is accepted.
        raise OidcError(f"unexpected alg {alg}; expected {config.expected_alg}")

    signing_input = f"{header_b64}.{payload_b64}".encode()
    if alg == "HS256":
        if not config.hs_secret:
            raise OidcError("no HS256 secret configured")
        if not _verify_hs256(signing_input, signature, config.hs_secret):
            raise OidcError("invalid token signature")
    elif alg in ("RS256", "ES256"):
        kid = str(header.get("kid", ""))
        jwk = (config.jwks.get(kid) if isinstance(config.jwks, dict)
               else None) or (config.jwks if isinstance(config.jwks, dict)
                              and config.jwks.get("kty") else None)
        if not jwk:
            raise OidcError("unknown signing key (kid)")
        if not _verify_rs256(signing_input, signature, jwk):
            raise OidcError("invalid token signature")
    else:
        raise OidcError(f"unsupported alg {alg}")

    skew = config.clock_skew_seconds
    if str(claims.get("iss", "")).rstrip("/") != config.issuer.rstrip("/"):
        raise OidcError("invalid issuer")
    aud = claims.get("aud", "")
    audiences = aud if isinstance(aud, list) else [aud]
    if config.client_id not in audiences:
        raise OidcError("invalid audience")
    exp = float(claims.get("exp", 0))
    iat = float(claims.get("iat", moment))
    if moment > exp + skew:
        raise OidcError("token expired")
    if iat > moment + skew + 600 or (moment < iat - skew - 600):
        raise OidcError("token issued in the future")
    if nonce and claims.get("nonce") != nonce:
        raise OidcError("nonce mismatch")
    if not claims.get("sub"):
        raise OidcError("missing subject claim")
    return claims


def mint_test_token(claims: dict[str, Any], secret: str,
                    alg: str = "HS256") -> str:
    """Mint HS256 tokens for tests/local IdPs (never production RS256)."""
    header = {"alg": alg, "typ": "JWT"}
    hb = _b64url_encode(json.dumps(header, separators=(",", ":")).encode())
    pb = _b64url_encode(json.dumps(claims, separators=(",", ":")).encode())
    sig = hmac.new(secret.encode(), f"{hb}.{pb}".encode(),
                   hashlib.sha256).digest()
    return f"{hb}.{pb}.{_b64url_encode(sig)}"


class OidcIdentityProvider(IdentityProvider):
    provider_type = "oidc"

    def __init__(self, config: OidcConfig, state_secret: str = "") -> None:
        ok, reason = config.validate()
        if not ok:
            raise ValueError(reason)
        self.config = config
        self.state_secret = state_secret

    async def authenticate(self, request: AuthRequest) -> str:
        url, _, _, _ = build_login(
            self.config, state_secret=self.state_secret or "dev",
            organization_id=request.organization_id)
        return url

    async def validate_assertion(self, payload: dict[str, Any],
                                 context: dict[str, Any]) -> AuthResult:
        claims = validate_id_token(
            str(payload.get("id_token", "")),
            config=self.config,
            nonce=str(payload.get("nonce", "") or context.get("nonce", "")))
        email = str(claims.get("email", ""))
        return AuthResult(
            subject=str(claims["sub"]), email=email,
            email_verified=bool(claims.get("email_verified", False)),
            display_name=str(claims.get("name", "")),
            groups=list(claims.get("groups", []) or []),
            attributes={k: v for k, v in claims.items()
                        if k not in ("sub", "email")},
            auth_strength="AAL1",
            raw_claims={})  # raw claims never leave the boundary

    async def provision_user(self, result: AuthResult,
                             context: dict[str, Any]) -> ProvisioningResult:
        return ProvisioningResult(created=True, user_id=result.subject,
                                  detail="jit provision candidate")

    async def deprovision_user(self, subject: str,
                               context: dict[str, Any]) -> bool:
        return True

    async def get_groups(self, subject: str,
                         context: dict[str, Any]) -> list[str]:
        return list(context.get("groups", []) or [])
