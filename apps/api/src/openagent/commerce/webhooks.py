"""MP24: billing webhook security — verify, dedupe, order-safely.

Never trust an unsigned webhook. Required checks:

1. HMAC-SHA256 signature over the raw body (``sha256=<hex>`` or raw hex).
2. Timestamp freshness (replay window, default 300s).
3. Replay protection via persisted ``event_id`` uniqueness.
4. Idempotency via deterministic ``idempotency_key`` (provider + event_id).
5. Failure persistence + retry counters + dead-letter flag live in the
   service layer (``billing_webhook_events`` / ``commerce_webhook_events``).
"""

from __future__ import annotations

import hashlib
import hmac
import time


def verify_signature(*, secret: str, raw_body: bytes, signature: str) -> bool:
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    candidate = signature.split("=", 1)[-1].strip()
    return hmac.compare_digest(expected, candidate)


def verify_timestamp(timestamp: object,
                     *, now: float | None = None,
                     max_skew_seconds: int = 300) -> bool:
    try:
        moment = float(timestamp)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    return abs((now if now is not None else time.time()) - moment) <= max_skew_seconds


def idempotency_key(*, provider: str, event_id: str) -> str:
    return f"{provider}:{event_id}"


def extract_timestamp(headers: dict[str, str],
                      payload: dict[str, object]) -> str | None:
    for header in ("x-webhook-timestamp", "stripe-signature-timestamp",
                   "webhook-timestamp"):
        value = headers.get(header) or headers.get(header.lower())
        if value:
            # Stripe-style "t=123,v1=abc" — extract t.
            if "t=" in value:
                for part in value.split(","):
                    if part.strip().startswith("t="):
                        return part.strip()[2:]
            return value
    for key in ("timestamp", "created", "created_at"):
        if payload.get(key) is not None:
            return str(payload[key])
    return None
