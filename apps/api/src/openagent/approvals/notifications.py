from __future__ import annotations

"""Approval notification abstraction (MP19).

In-app is backed by the durable event outbox; email/webhook are extension
points sharing the same secret-free payload builder. Never includes secrets.

Webhook delivery reuses the existing signed pipeline (HMAC-SHA256 signature,
timestamp header, retry + delivery logs in WebhookService/EventSubscription):
subscribe to the APPROVAL_WEBHOOK_EVENTS below — no parallel webhook system.
"""

APPROVAL_WEBHOOK_EVENTS: tuple[str, ...] = (
    "approval.created",
    "approval.approved",
    "approval.rejected",
    "approval.expired",
    "approval.escalated",
    "approval.executed",
)

from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession


def approval_notice_payload(*, approval_id: UUID, action: str, requester: str | None,
                            risk_level: str, target: str, expires_at: str | None,
                            reason: str = "") -> dict[str, Any]:
    return {"approval_id": str(approval_id), "action": action,
            "requester": requester or "agent",
            "risk_level": risk_level, "target": target or "",
            "expires_at": expires_at, "reason": reason,
            "actions": ["approve", "reject", "escalate"]}


class NotificationChannel(Protocol):
    async def send(self, payload: dict[str, Any]) -> None: ...


class EventChannel:
    """Durable in-app fan-out via the event outbox (async, non-blocking)."""

    def __init__(self, db: AsyncSession, organization_id: UUID):
        self.db = db
        self.organization_id = organization_id

    async def send(self, payload: dict[str, Any]) -> None:
        from openagent.core.events import EventService
        svc = EventService(self.db)
        await svc.publish("approval.created", "approval",
                          UUID(payload["approval_id"]), dict(payload),
                          organization_id=self.organization_id)


class NotificationService:
    def __init__(self, channels: list[NotificationChannel] | None = None):
        self.channels = channels or []

    async def notify(self, payload: dict[str, Any]) -> None:
        for channel in self.channels:
            try:
                await channel.send(payload)
            except Exception:
                continue  # notifications never block approvals
