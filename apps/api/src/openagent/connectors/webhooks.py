"""Inbound webhook verification + normalization (MP21).

Provider-agnostic pipeline: size cap -> signature verify (HMAC/provider
schemes) -> timestamp tolerance -> replay dedupe -> normalize to
{event_type, provider, resource_id, timestamp, payload_reference}.
Raw payloads are preserved only as references unless policy allows storage.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import structlog

logger = structlog.get_logger("openagent.connectors.webhooks")

MAX_WEBHOOK_BYTES = 1 * 1024 * 1024
DEFAULT_TIMESTAMP_TOLERANCE = 300


class WebhookError(Exception):
    def __init__(self, message: str, code: str = "WEBHOOK_REJECTED"):
        super().__init__(message)
        self.code = code


@dataclass
class NormalizedEvent:
    event_type: str  # e.g. pull_request.created
    provider: str  # connector id
    resource_id: str = ""
    timestamp: str = ""
    payload_reference: str = ""  # event-row id, not raw payload
    attributes: dict[str, Any] = field(default_factory=dict)


def verify_hmac(secret: str, payload: bytes, signature: str, *,
                prefix: str = "sha256=") -> bool:
    """Constant-time HMAC-SHA256 compare (GitHub/Stripe/Slack style)."""
    if not secret or not signature:
        return False
    digest = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    expected = f"{prefix}{digest}" if prefix else digest
    return hmac.compare_digest(expected, signature)


def verify_github(secret: str, payload: bytes, headers: dict[str, str]) -> bool:
    lowered = {k.lower(): v for k, v in headers.items()}
    return verify_hmac(secret, payload, lowered.get("x-hub-signature-256", ""))


def verify_slack(signing_secret: str, payload: bytes, headers: dict[str, str],
                 *, tolerance: int = DEFAULT_TIMESTAMP_TOLERANCE,
                 now: Optional[float] = None) -> bool:
    """Slack v0 signing: HMAC over 'v0:timestamp:body' + timestamp check."""
    lowered = {k.lower(): v for k, v in headers.items()}
    timestamp = lowered.get("x-slack-request-timestamp", "")
    signature = lowered.get("x-slack-signature", "")
    try:
        age = abs((now if now is not None else time.time()) - int(timestamp))
    except ValueError:
        return False
    if age > tolerance:
        return False
    base = f"v0:{timestamp}:".encode() + payload
    digest = hmac.new(signing_secret.encode(), base, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"v0={digest}", signature)


def verify_stripe(secret: str, payload: bytes, headers: dict[str, str], *,
                  tolerance: int = DEFAULT_TIMESTAMP_TOLERANCE,
                  now: Optional[float] = None) -> bool:
    """Stripe header: t=...,v1=...[,v1=...] with timestamp tolerance."""
    lowered = {k.lower(): v for k, v in headers.items()}
    header = lowered.get("stripe-signature", "")
    parts: dict[str, list[str]] = {}
    for chunk in header.split(","):
        key, _, value = chunk.partition("=")
        parts.setdefault(key.strip(), []).append(value.strip())
    if not parts.get("t") or not parts.get("v1"):
        return False
    try:
        age = abs((now if now is not None else time.time()) - int(parts["t"][0]))
    except ValueError:
        return False
    if age > tolerance:
        return False
    signed = f"{parts['t'][0]}.".encode() + payload
    expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, candidate) for candidate in parts["v1"])


def verify_telegram(secret_token: str, headers: dict[str, str]) -> bool:
    lowered = {k.lower(): v for k, v in headers.items()}
    presented = lowered.get("x-telegram-bot-api-secret-token", "")
    if not secret_token or not presented:
        return False
    return hmac.compare_digest(secret_token, presented)


def verify_generic(secret: str, payload: bytes, headers: dict[str, str],
                   *, header: str = "x-openagent-signature") -> bool:
    lowered = {k.lower(): v for k, v in headers.items()}
    return verify_hmac(secret, payload, lowered.get(header.lower(), ""))


VERIFY_MODES = {"hmac_sha256", "github", "slack", "stripe", "telegram",
                "generic", "none"}


def verify_signature(mode: str, secret: str, payload: bytes,
                     headers: dict[str, str]) -> bool:
    mode = (mode or "hmac_sha256").lower()
    if mode not in VERIFY_MODES:
        raise WebhookError(f"Unknown verify mode '{mode}'")
    if mode == "none":
        return False  # never accept unsigned webhooks
    if mode in ("hmac_sha256", "generic", "github"):
        if mode == "github":
            return verify_github(secret, payload, headers)
        return verify_generic(secret, payload, headers)
    if mode == "slack":
        return verify_slack(secret, payload, headers)
    if mode == "stripe":
        return verify_stripe(secret, payload, headers)
    if mode == "telegram":
        return verify_telegram(secret, headers)
    return False


def check_timestamp(event_time_epoch: float, *,
                    tolerance: int = DEFAULT_TIMESTAMP_TOLERANCE,
                    now: Optional[float] = None) -> None:
    now = now if now is not None else time.time()
    if abs(now - event_time_epoch) > tolerance:
        raise WebhookError("Webhook timestamp outside tolerance (possible replay)",
                           code="STALE_EVENT")


class ReplayGuard:
    """Single-use delivery IDs with bounded memory (caller persists as needed)."""

    def __init__(self, capacity: int = 10000):
        self.capacity = capacity
        self._seen: dict[str, float] = {}

    def check_and_mark(self, delivery_id: str, *,
                       now: Optional[float] = None) -> None:
        now = now if now is not None else time.time()
        if not delivery_id:
            raise WebhookError("Missing delivery ID", code="NO_DELIVERY_ID")
        if delivery_id in self._seen:
            raise WebhookError("Duplicate delivery (replay blocked)",
                               code="REPLAY")
        self._seen[delivery_id] = now
        if len(self._seen) > self.capacity:
            oldest = sorted(self._seen.items(), key=lambda kv: kv[1])
            for key, _ in oldest[: len(self._seen) - self.capacity]:
                del self._seen[key]


def normalize_event(*, provider: str, event_type: str,
                    resource_id: str = "", timestamp: str = "",
                    payload_reference: str = "",
                    attributes: Optional[dict[str, Any]] = None) -> NormalizedEvent:
    if not event_type or not provider:
        raise WebhookError("Event requires provider + event_type")
    return NormalizedEvent(event_type=event_type, provider=provider,
                           resource_id=str(resource_id)[:256],
                           timestamp=timestamp,
                           payload_reference=payload_reference,
                           attributes=dict(attributes or {}))


def github_event_name(headers: dict[str, str], payload: dict[str, Any]) -> str:
    lowered = {k.lower(): v for k, v in headers.items()}
    name = lowered.get("x-github-event", "unknown")
    action = str(payload.get("action", ""))
    return f"{name}.{action}" if action else name
