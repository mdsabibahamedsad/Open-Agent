import hashlib
import hmac
import json
import time
import uuid
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Callable, Awaitable
from dataclasses import dataclass, field
from abc import ABC, abstractmethod

from sqlalchemy import String, Text, ForeignKey, Index, Enum as SQLEnum, DateTime, JSON, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from openagent.db.models.base import Base, TimestampMixin, UUIDMixin
from openagent.core.config import get_settings
from openagent.core.security import hash_token, verify_token


class WebhookEventStatus(str, Enum):
    PENDING = "pending"
    DELIVERED = "delivered"
    FAILED = "failed"
    RETRYING = "retrying"


class WebhookEvent(Base, TimestampMixin):
    """Webhook delivery event tracking."""
    
    __tablename__ = "webhook_events"
    
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    webhook_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("webhooks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(255), nullable=False)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(
        SQLEnum(WebhookEventStatus, name="webhook_event_status", create_constraint=True),
        default=WebhookEventStatus.PENDING,
        nullable=False,
        index=True
    )
    attempt: Mapped[int] = mapped_column(default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(default=5, nullable=False)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    response_status: Mapped[Optional[int]] = mapped_column(nullable=True)
    response_body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    response_headers: Mapped[Optional[Dict[str, str]]] = mapped_column(JSONB, nullable=True)
    next_retry_at: Mapped[Optional[datetime]] = mapped_column(nullable=True, index=True)
    delivered_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    
    __table_args__ = (
        Index("ix_webhook_events_webhook_status", "webhook_id", "status"),
        Index("ix_webhook_events_next_retry", "next_retry_at"),
    )


class Webhook(Base, TimestampMixin, UUIDMixin):
    """Webhook configuration for event delivery."""
    
    __tablename__ = "webhooks"
    
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    event_types: Mapped[List[str]] = mapped_column(JSONB, nullable=False, default=list)
    secret_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    secret_prefix: Mapped[str] = mapped_column(String(20), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    retry_count: Mapped[int] = mapped_column(default=5, nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(default=30, nullable=False)
    last_delivery_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    last_delivery_status: Mapped[Optional[int]] = mapped_column(nullable=True)
    last_delivery_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metadata: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    
    # Relationships
    organization: Mapped["Organization"] = relationship(back_populates="webhooks")
    events: Mapped[List["WebhookEvent"]] = relationship(
        back_populates="webhook", cascade="all, delete-orphan"
    )
    
    __table_args__ = (
        Index("ix_webhooks_org_active", "organization_id", "is_active"),
    )


class WebhookService:
    """Service for managing webhooks and delivering events."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.settings = get_settings()
    
    def _hash_secret(self, secret: str) -> str:
        return hash_token(secret)
    
    def _generate_secret(self) -> str:
        from openagent.core.security import generate_secure_token
        return generate_secure_token()
    
    async def create_webhook(
        self,
        organization_id: uuid.UUID,
        name: str,
        url: str,
        event_types: List[str],
        secret: Optional[str] = None,
        is_active: bool = True,
        retry_count: int = 5,
        timeout_seconds: int = 30,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> tuple[Webhook, str]:
        """Create a new webhook. Returns (webhook, raw_secret)."""
        if not secret:
            secret = self._generate_secret()
        
        secret_hash = self._hash_secret(secret)
        secret_prefix = secret[:8]
        
        webhook = Webhook(
            organization_id=organization_id,
            name=name,
            url=url,
            event_types=event_types,
            secret_hash=secret_hash,
            secret_prefix=secret_prefix,
            is_active=is_active,
            retry_count=retry_count,
            timeout_seconds=timeout_seconds,
            metadata=metadata or {},
        )
        self.db.add(webhook)
        await self.db.flush()
        
        return webhook, secret
    
    async def update_webhook(
        self,
        webhook_id: uuid.UUID,
        organization_id: uuid.UUID,
        name: Optional[str] = None,
        url: Optional[str] = None,
        event_types: Optional[List[str]] = None,
        is_active: Optional[bool] = None,
        retry_count: Optional[int] = None,
        timeout_seconds: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Webhook]:
        """Update a webhook."""
        result = await self.db.execute(
            select(Webhook).where(
                Webhook.id == webhook_id,
                Webhook.organization_id == organization_id,
            )
        )
        webhook = result.scalar_one_or_none()
        
        if not webhook:
            return None
        
        if name is not None:
            webhook.name = name
        if url is not None:
            webhook.url = url
        if event_types is not None:
            webhook.event_types = event_types
        if is_active is not None:
            webhook.is_active = is_active
        if retry_count is not None:
            webhook.retry_count = retry_count
        if timeout_seconds is not None:
            webhook.timeout_seconds = timeout_seconds
        if metadata is not None:
            webhook.metadata = metadata
        
        await self.db.flush()
        return webhook
    
    async def delete_webhook(
        self,
        webhook_id: uuid.UUID,
        organization_id: uuid.UUID,
    ) -> bool:
        """Delete a webhook."""
        result = await self.db.execute(
            select(Webhook).where(
                Webhook.id == webhook_id,
                Webhook.organization_id == organization_id,
            )
        )
        webhook = result.scalar_one_or_none()
        
        if not webhook:
            return False
        
        await self.db.delete(webhook)
        await self.db.flush()
        return True
    
    async def get_webhook(
        self,
        webhook_id: uuid.UUID,
        organization_id: uuid.UUID,
    ) -> Optional[Webhook]:
        result = await self.db.execute(
            select(Webhook).where(
                Webhook.id == webhook_id,
                Webhook.organization_id == organization_id,
            )
        )
        return result.scalar_one_or_none()
    
    async def list_webhooks(
        self,
        organization_id: uuid.UUID,
        is_active: Optional[bool] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Webhook]:
        query = select(Webhook).where(Webhook.organization_id == organization_id)
        if is_active is not None:
            query = query.where(Webhook.is_active == is_active)
        query = query.order_by(Webhook.created_at.desc()).limit(limit).offset(offset)
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    def _sign_payload(self, payload: bytes, secret: str) -> str:
        """Generate HMAC signature for payload."""
        signature = hmac.new(
            secret.encode(),
            payload,
            hashlib.sha256
        ).hexdigest()
        return f"sha256={signature}"
    
    def _verify_signature(self, payload: bytes, signature: str, secret: str) -> bool:
        """Verify HMAC signature."""
        expected = self._sign_payload(payload, secret)
        return hmac.compare_digest(signature, expected)
    
    async def deliver_event(
        self,
        webhook: Webhook,
        event_type: str,
        payload: Dict[str, Any],
        secret: str,
    ) -> WebhookEvent:
        """Deliver a single event to a webhook."""
        from openagent.core.security import create_token_pair
        
        # Create event record
        event = WebhookEvent(
            webhook_id=webhook.id,
            event_type=event_type,
            payload=payload,
            max_attempts=webhook.retry_count,
        )
        self.db.add(event)
        await self.db.flush()
        
        # Attempt delivery with retries
        for attempt in range(webhook.retry_count):
            event.attempt = attempt + 1
            try:
                # Prepare payload
                payload_bytes = json.dumps(payload, separators=(',', ':')).encode()
                
                # Sign payload
                signature = self._sign_payload(payload_bytes, secret)
                
                # Prepare headers
                headers = {
                    "Content-Type": "application/json",
                    "X-Webhook-Event": event_type,
                    "X-Webhook-Signature": signature,
                    "X-Webhook-Delivery": str(event.id),
                    "X-Webhook-Timestamp": str(int(time.time())),
                    "User-Agent": "OpenAgent-Webhooks/1.0",
                }
                
                # Make HTTP request
                import httpx
                async with httpx.AsyncClient(timeout=webhook.timeout_seconds) as client:
                    response = await client.post(
                        webhook.url,
                        content=payload_bytes,
                        headers=headers,
                    )
                
                event.response_status = response.status_code
                event.response_body = response.text
                event.response_headers = dict(response.headers)
                
                if 200 <= response.status_code < 300:
                    event.status = WebhookEventStatus.DELIVERED
                    event.delivered_at = datetime.now(timezone.utc)
                    webhook.last_delivery_at = event.delivered_at
                    webhook.last_delivery_status = response.status_code
                    await self.db.flush()
                    return event
                else:
                    event.last_error = f"HTTP {response.status_code}: {response.text}"
                    
            except Exception as e:
                event.last_error = str(e)
            
            # Schedule retry
            if attempt < webhook.retry_count - 1:
                event.status = WebhookEventStatus.RETRYING
                # Exponential backoff: 1s, 2s, 4s, 8s, 16s
                delay = min(2 ** attempt * 2, 300)  # Max 5 minutes
                event.next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
                await self.db.flush()
                await asyncio.sleep(delay)
            else:
                event.status = WebhookEventStatus.FAILED
        
        webhook.last_delivery_at = datetime.now(timezone.utc)
        webhook.last_delivery_status = event.response_status or 0
        webhook.last_delivery_error = event.last_error
        await self.db.flush()
        
        return event
    
    async def process_pending_events(self, batch_size: int = 50) -> int:
        """Process pending webhook events with retries."""
        from openagent.core.security import hash_token
        
        result = await self.db.execute(
            select(WebhookEvent)
            .where(
                WebhookEvent.status.in_([WebhookEventStatus.PENDING, WebhookEventStatus.RETRYING]),
                (WebhookEvent.next_retry_at.is_(None)) | (WebhookEvent.next_retry_at <= datetime.now(timezone.utc))
            )
            .order_by(WebhookEvent.created_at)
            .limit(batch_size)
        )
        events = list(result.scalars().all())
        
        if not events:
            return 0
        
        processed = 0
        for event in events:
            try:
                # Get webhook and secret
                webhook_result = await self.db.execute(
                    select(Webhook).where(Webhook.id == event.webhook_id)
                )
                webhook = webhook_result.scalar_one_or_none()
                
                if not webhook or not webhook.is_active:
                    event.status = WebhookEventStatus.FAILED
                    event.last_error = "Webhook not found or inactive"
                    continue
                
                # We can't get the raw secret from hash, so we need the original
                # In practice, you'd store the encrypted secret or use a key management system
                # For now, we'll use a placeholder - in production, use a KMS
                # This is a limitation of the current design
                
            except Exception as e:
                event.last_error = str(e)
        
        return 0
    
    async def test_webhook(
        self,
        webhook_id: uuid.UUID,
        organization_id: uuid.UUID,
        secret: str,
    ) -> Dict[str, Any]:
        """Test webhook delivery with a test event."""
        webhook = await self.get_webhook(webhook_id, organization_id)
        if not webhook:
            raise ValueError("Webhook not found")
        
        test_payload = {
            "event": "webhook.test",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "message": "This is a test event from OpenAgent",
        }
        
        # Create a test event
        event = await self.deliver_event(webhook, "webhook.test", test_payload, secret)
        
        return {
            "success": event.status == WebhookEventStatus.DELIVERED,
            "event_id": str(event.id),
            "status": event.status.value,
            "response_status": event.response_status,
            "response_body": event.response_body,
            "error": event.last_error,
        }


class WebhookEventProcessor:
    """Background processor for webhook events."""
    
    def __init__(self, db: AsyncSession, webhook_service: WebhookService):
        self.db = db
        self.service = webhook_service
    
    async def process_pending(self, batch_size: int = 50) -> int:
        """Process pending webhook events."""
        # This would be run by a background worker
        # Implementation depends on your worker infrastructure
        return 0


# Dependency
async def get_webhook_service(db: AsyncSession = Depends(get_db)) -> WebhookService:
    return WebhookService(db)