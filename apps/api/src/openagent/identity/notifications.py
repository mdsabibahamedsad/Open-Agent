"""MP27: security notifications (§103-104). Event payload builders
for email/Slack/webhook delivery THROUGH the existing connector
framework. This module never sends anything itself and never includes
sensitive values."""

from __future__ import annotations

from typing import Any

NOTIFICATION_EVENTS = (
    "sso.configured", "api_key.created", "mfa.disabled",
    "password.reset", "service_account.created", "privilege.changed",
    "suspicious.login", "device.registered",
)


def notification_payload(event: str, *, organization_id: str,
                         actor: str = "",
                         summary: str = "",
                         metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    if event not in NOTIFICATION_EVENTS:
        raise ValueError(f"unknown notification event {event}")
    from openagent.control.observability import redact
    return {"event": event, "organization_id": organization_id,
            "actor": actor, "summary": summary,
            "metadata": redact(dict(metadata or {})),
            "channels": ["email", "slack", "webhook"],
            "note": "deliver via connector framework; no new infra"}


def suspicious_login_payload(*, organization_id: str, user_id: str,
                             reason: str, ip: str = "") -> dict[str, Any]:
    return notification_payload(
        "suspicious.login", organization_id=organization_id,
        actor=user_id, summary=f"Unusual sign-in detected: {reason}",
        metadata={"ip": ip})
