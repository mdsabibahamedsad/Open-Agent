"""OAuth 2.0 manager (MP21).

Authorization code + PKCE, refresh, revocation, disconnect. Protections:
CSRF via signed state, PKCE S256, redirect allowlisting, single-use
authorization codes (replay tracking left to the caller store), minimal
scope requests, token responses never logged.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import structlog

logger = structlog.get_logger("openagent.connectors.oauth")


class OAuthError(Exception):
    def __init__(self, message: str, code: str = "OAUTH_ERROR"):
        super().__init__(message)
        self.code = code


@dataclass
class OAuthConfig:
    authorize_url: str
    token_url: str
    client_id: str
    redirect_uri: str
    scopes: list[str] = field(default_factory=list)
    revoke_url: str = ""
    userinfo_url: str = ""
    allowed_redirect_hosts: list[str] = field(default_factory=list)


@dataclass
class TokenSet:
    access_token: str
    token_type: str = "Bearer"
    refresh_token: str = ""
    expires_in: int = 0
    obtained_at_epoch: float = field(default_factory=time.time)
    scope: str = ""

    def expired(self, *, skew_seconds: int = 60,
                now: Optional[float] = None) -> bool:
        if not self.expires_in:
            return False
        return (now if now is not None else time.time()) >= \
            self.obtained_at_epoch + self.expires_in - skew_seconds

    def to_storage(self) -> dict[str, Any]:
        return {"access_token": self.access_token, "token_type": self.token_type,
                "refresh_token": self.refresh_token, "expires_in": self.expires_in,
                "obtained_at_epoch": self.obtained_at_epoch, "scope": self.scope}

    @classmethod
    def from_storage(cls, data: dict[str, Any]) -> "TokenSet":
        return cls(access_token=str(data.get("access_token", "")),
                   token_type=str(data.get("token_type", "Bearer")),
                   refresh_token=str(data.get("refresh_token", "")),
                   expires_in=int(data.get("expires_in", 0) or 0),
                   obtained_at_epoch=float(data.get("obtained_at_epoch", time.time())),
                   scope=str(data.get("scope", "")))


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def pkce_pair() -> tuple[str, str]:
    """Return (verifier, S256 challenge)."""
    verifier = _b64url(secrets.token_bytes(48))
    challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
    return verifier, challenge


def sign_state(payload: dict[str, Any], secret: str) -> str:
    """HMAC-signed state token (CSRF + fixation defense)."""
    body = _b64url(json.dumps(payload, sort_keys=True,
                              separators=(",", ":")).encode())
    sig = hmac.new(secret.encode(), body.encode(),
                   hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def verify_state(token: str, secret: str, *, max_age_seconds: int = 600,
                 now: Optional[float] = None) -> dict[str, Any]:
    """Verify state token; raises OAuthError on CSRF/expiry/tamper."""
    now = now if now is not None else time.time()
    try:
        body, _, sig = token.partition(".")
        expected = hmac.new(secret.encode(), body.encode(),
                            hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, sig):
            raise OAuthError("Invalid state signature (possible CSRF)",
                             code="STATE_INVALID")
        payload = json.loads(base64.urlsafe_b64decode(body + "==").decode())
    except OAuthError:
        raise
    except Exception as exc:
        raise OAuthError("Malformed state", code="STATE_INVALID") from exc
    issued = float(payload.get("iat", 0) or 0)
    if issued <= 0 or now - issued > max_age_seconds:
        raise OAuthError("Expired state (possible replay)", code="STATE_EXPIRED")
    return payload


def build_authorize_url(config: OAuthConfig, *, state_secret: str,
                        connection_id: str, extra_scopes: Optional[list[str]] = None,
                        extra_params: Optional[dict[str, str]] = None) -> tuple[str, str, str]:
    """Return (url, state_token, code_verifier). Requested scopes are the
    manifest minimum plus explicitly requested extras — never silent extras."""
    if not config.authorize_url.startswith("https://"):
        raise OAuthError("OAuth authorize_url must be https")
    if not config.token_url.startswith("https://"):
        raise OAuthError("OAuth token_url must be https")
    verifier, challenge = pkce_pair()
    scopes = list(dict.fromkeys(list(config.scopes) + list(extra_scopes or [])))
    if len(scopes) > 64:
        raise OAuthError("Excessive scope request rejected")
    state = sign_state({"connection_id": connection_id, "iat": time.time(),
                        "nonce": secrets.token_hex(8)}, state_secret)
    query = {"response_type": "code", "client_id": config.client_id,
             "redirect_uri": config.redirect_uri, "scope": " ".join(scopes),
             "state": state, "code_challenge": challenge,
             "code_challenge_method": "S256"}
    query.update(extra_params or {})
    parts = urlparse(config.authorize_url)
    merged = dict(parse_qsl(parts.query))
    merged.update(query)
    url = urlunparse(parts._replace(query=urlencode(merged)))
    return url, state, verifier


def validate_callback_url(url: str, *, allowed_hosts: list[str]) -> None:
    """Redirect-target allowlist: callbacks only complete on known hosts."""
    host = (urlparse(url).hostname or "").lower()
    allowed = {h.lower() for h in allowed_hosts}
    if host not in allowed:
        raise OAuthError(f"Redirect host '{host}' not allowlisted",
                         code="REDIRECT_BLOCKED")


PostForm = Callable[[str, dict[str, str], dict[str, str]],
                    Awaitable[tuple[int, dict[str, Any]]]]


class OAuthManager:
    """Token lifecycle over an injected form-POST (no direct HTTP dependency)."""

    def __init__(self, config: OAuthConfig):
        self.config = config

    async def exchange_code(self, *, code: str, verifier: str,
                            client_secret: str,
                            post_form: PostForm) -> TokenSet:
        if not code or not verifier:
            raise OAuthError("Missing code/verifier (possible replay)",
                             code="CODE_INVALID")
        status, body = await post_form(
            self.config.token_url,
            {"grant_type": "authorization_code", "code": code,
             "redirect_uri": self.config.redirect_uri,
             "client_id": self.config.client_id,
             "code_verifier": verifier},
            {"client_secret": client_secret} if client_secret else {})
        if status != 200 or not isinstance(body, dict) or not body.get("access_token"):
            raise OAuthError("Token exchange failed", code="EXCHANGE_FAILED")
        return TokenSet(
            access_token=str(body["access_token"]),
            token_type=str(body.get("token_type", "Bearer")),
            refresh_token=str(body.get("refresh_token", "")),
            expires_in=int(body.get("expires_in", 0) or 0),
            scope=str(body.get("scope", "")))

    async def refresh(self, *, refresh_token: str, client_secret: str,
                      post_form: PostForm) -> TokenSet:
        if not refresh_token:
            raise OAuthError("No refresh token", code="NO_REFRESH_TOKEN")
        status, body = await post_form(
            self.config.token_url,
            {"grant_type": "refresh_token", "refresh_token": refresh_token,
             "client_id": self.config.client_id},
            {"client_secret": client_secret} if client_secret else {})
        if status != 200 or not isinstance(body, dict) or not body.get("access_token"):
            raise OAuthError("Token refresh failed", code="REFRESH_FAILED")
        return TokenSet(
            access_token=str(body["access_token"]),
            token_type=str(body.get("token_type", "Bearer")),
            refresh_token=str(body.get("refresh_token", "") or refresh_token),
            expires_in=int(body.get("expires_in", 0) or 0),
            scope=str(body.get("scope", "")))

    async def revoke(self, *, token: str, client_secret: str,
                     post_form: PostForm) -> bool:
        if not self.config.revoke_url or not token:
            return False
        try:
            status, _ = await post_form(
                self.config.revoke_url, {"token": token},
                {"client_secret": client_secret} if client_secret else {})
            return status in (200, 204)
        except Exception as exc:
            logger.warning("oauth revoke failed", error=str(exc))
            return False

    def validate_scopes(self, granted: str, *, required: list[str]) -> list[str]:
        """Return missing required scopes (empty = satisfied)."""
        have = set(granted.split())
        return [scope for scope in required if scope not in have]
