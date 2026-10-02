"""Webhook signing, verification, and parsing.

Wire-compatible with the backend helpers in
``apps/api/src/openagent/developer/errors.py``: HMAC-SHA256 over
``v1.{timestamp}.{delivery_id}.{sha256(body)}`` with header format
``v1,t=..,id=..,sig=..``, constant-time comparison, and a 5-minute
replay window.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any, Dict

from .errors import ValidationError

SIGNATURE_VERSION = "v1"
REPLAY_TOLERANCE_SECONDS = 300

__all__ = [
    "SIGNATURE_VERSION",
    "REPLAY_TOLERANCE_SECONDS",
    "sign_webhook",
    "verify_webhook",
    "parse_webhook",
]


def sign_webhook(
    secret: str,
    body: bytes,
    delivery_id: str = "",
    timestamp: int = 0,
) -> str:
    """Sign a webhook body. Returns the value for the signature header."""
    ts = timestamp or int(time.time())
    body_hash = hashlib.sha256(body).hexdigest()
    base = f"{SIGNATURE_VERSION}.{ts}.{delivery_id}.{body_hash}".encode()
    digest = hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()
    return f"{SIGNATURE_VERSION},t={ts},id={delivery_id},sig={digest}"


def verify_webhook(
    secret: str,
    body: bytes,
    header: str,
    now: int = 0,
    tolerance: int = REPLAY_TOLERANCE_SECONDS,
) -> Dict[str, Any]:
    """Verify a webhook signature header.

    Returns ``{"ok": bool, "reason": str, "delivery_id": str}``.
    """
    try:
        parts: Dict[str, str] = {}
        for chunk in (header or "").split(","):
            chunk = chunk.strip()
            if chunk == SIGNATURE_VERSION:
                parts["v"] = chunk
            elif "=" in chunk:
                key, _, value = chunk.partition("=")
                parts[key.strip()] = value.strip()
        if (
            parts.get("v") != SIGNATURE_VERSION
            or not parts.get("sig")
            or not parts.get("t")
        ):
            return {
                "ok": False,
                "reason": "malformed signature header",
                "delivery_id": parts.get("id", ""),
            }
        ts = int(parts["t"])
        current = now or int(time.time())
        if abs(current - ts) > tolerance:
            return {
                "ok": False,
                "reason": "timestamp outside tolerance",
                "delivery_id": parts.get("id", ""),
            }
        expected = sign_webhook(
            secret, body, delivery_id=parts.get("id", ""), timestamp=ts
        )
        if not hmac.compare_digest(expected, (header or "").strip()):
            return {
                "ok": False,
                "reason": "signature mismatch",
                "delivery_id": parts.get("id", ""),
            }
        return {"ok": True, "reason": "", "delivery_id": parts.get("id", "")}
    except (ValueError, TypeError) as exc:
        return {"ok": False, "reason": f"verification error: {exc}", "delivery_id": ""}


def parse_webhook(body: bytes) -> Dict[str, Any]:
    """Parse a webhook body; requires a JSON object with an ``event`` field."""
    try:
        data = json.loads(body.decode())
    except Exception as exc:
        raise ValidationError(f"invalid webhook JSON: {exc}") from exc
    if not isinstance(data, dict) or "event" not in data:
        raise ValidationError(
            "webhook body must be a JSON object with an 'event' field"
        )
    return data
