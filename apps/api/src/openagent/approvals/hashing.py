"""Secret redaction + canonical hashing for approvals (MP19).

Single implementation: redacts sensitive params before persistence/logging,
and produces tamper-evident canonical hashes binding approvals to exact actions.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

SENSITIVE_KEYS = frozenset({
    "password", "passwd", "secret", "api_key", "apikey", "token",
    "access_token", "refresh_token", "session", "cookie", "auth",
    "authorization", "private_key", "client_secret", "credit_card",
    "card_number", "cvv", "ssn", "ssn_number", "bank_account",
    "privatekey", "publickey_credential", "otp", "pin",
})

REDACTED = "[REDACTED]"


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    if lowered in SENSITIVE_KEYS:
        return True
    return any(h in lowered for h in ("password", "secret", "api_key", "apikey",
                                      "private_key", "client_secret", "credit_card",
                                      "ssn", "bank_account"))


def redact_params(params: Any) -> Any:
    if isinstance(params, dict):
        out: dict[str, Any] = {}
        for key, value in params.items():
            if _is_sensitive_key(str(key)):
                out[key] = REDACTED
            else:
                out[key] = redact_params(value)
        return out
    if isinstance(params, list):
        return [redact_params(item) for item in params]
    if isinstance(params, str) and len(params) > 0:
        lowered = params.lower()
        if any(t in lowered for t in ("sk-", "ghp_", "akia", "bearer ")):
            return REDACTED
    return params


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, default=str)


def envelope_payload(*, action_type: str, action_category: str, target_type: str,
                     target_id: str, redacted_params: Any, environment: str,
                     organization_id: str) -> dict[str, Any]:
    return {"action_type": action_type, "action_category": action_category,
            "target_type": target_type, "target_id": target_id,
            "params": redacted_params, "environment": environment,
            "organization_id": organization_id}


def action_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def approval_token() -> str:
    import secrets
    return secrets.token_urlsafe(32)
