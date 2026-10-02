import json
import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Callable, Awaitable
from dataclasses import dataclass, field
from enum import Enum
from abc import ABC, abstractmethod

from sqlalchemy import String, Text, ForeignKey, Index, Enum as SQLEnum, DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from openagent.db.models.base import Base, TimestampMixin, UUIDMixin
from openagent.core.config import get_settings
from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openagent.db.session import get_db as _get_db_impl

def _get_db() -> AsyncSession:
    """Lazy import to avoid circular dependency with db.session."""
    from openagent.db.session import get_db as _get_db_impl
    return _get_db_impl()


class EventStatus(str, Enum):
    PENDING = "pending"
    PUBLISHED = "published"
    FAILED = "failed"
    ARCHIVED = "archived"


class EventPriority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class Event(Base, TimestampMixin):
    """Event outbox table for reliable event publishing."""
    
    __tablename__ = "events"
    
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    event_type: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    aggregate_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    payload: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    metadata: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(
        SQLEnum(EventStatus.PENDING, EventStatus.PUBLISHED, EventStatus.FAILED, EventStatus.ARCHIVED,
                name="event_status", create_constraint=True),
        default=EventStatus.PENDING,
        nullable=False,
        index=True
    )
    priority: Mapped[str] = mapped_column(
        SQLEnum(EventPriority.LOW, EventPriority.NORMAL, EventPriority.HIGH, EventPriority.CRITICAL,
                name="event_priority", create_constraint=True),
        default=EventPriority.NORMAL,
        nullable=False,
        index=True
    )
    retry_count: Mapped[int] = mapped_column(default=0, nullable=False)
    max_retries: Mapped[int] = mapped_column(default=3, nullable=False)
    last_error: Mapped[Optional[str]] = mapped_column(nullable=True)
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(nullable=True, index=True)
    published_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    
    __table_args__ = (
        Index("ix_events_status_priority", "status", "priority"),
        Index("ix_events_aggregate", "aggregate_type", "aggregate_id"),
        Index("ix_events_scheduled", "scheduled_at"),
        Index("ix_events_org_status", "organization_id", "status"),
    )


class EventSubscription(Base, TimestampMixin):
    """Event subscription for webhook/webhook-like delivery."""
    
    __tablename__ = "event_subscriptions"
    
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    event_types: Mapped[List[str]] = mapped_column(JSONB, nullable=False, default=list)
    callback_url: Mapped[str] = mapped_column(String(500), nullable=False)
    secret_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    secret_prefix: Mapped[str] = mapped_column(String(20), nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    retry_count: Mapped[int] = mapped_column(default=3, nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(default=30, nullable=False)
    last_delivery_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    last_delivery_status: Mapped[Optional[int]] = mapped_column(nullable=True)
    last_delivery_error: Mapped[Optional[str]] = mapped_column(nullable=True)
    
    __table_args__ = (
        Index("ix_event_subscriptions_org_active", "organization_id", "is_active"),
    )


@dataclass
class EventData:
    """Data class for event payload."""
    event_type: str
    aggregate_type: str
    aggregate_id: uuid.UUID
    payload: Dict[str, Any]
    organization_id: Optional[uuid.UUID] = None
    user_id: Optional[uuid.UUID] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    priority: EventPriority = EventPriority.NORMAL
    scheduled_at: Optional[datetime] = None


class EventPublisher(ABC):
    """Abstract base class for event publishers."""
    
    @abstractmethod
    async def publish(self, event: EventData) -> None:
        """Publish an event."""
        pass
    
    @abstractmethod
    async def publish_batch(self, events: List[EventData]) -> None:
        """Publish multiple events."""
        pass


class DatabaseEventPublisher(EventPublisher):
    """Database-backed event publisher using outbox pattern."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def publish(self, event: EventData) -> None:
        """Publish a single event to the outbox."""
        db_event = Event(
            event_type=event.event_type,
            aggregate_type=event.aggregate_type,
            aggregate_id=event.aggregate_id,
            organization_id=event.organization_id,
            user_id=event.user_id,
            payload=event.payload,
            metadata=event.metadata,
            priority=event.priority,
            scheduled_at=event.scheduled_at,
        )
        self.db.add(db_event)
        await self.db.flush()
    
    async def publish_batch(self, events: List[EventData]) -> None:
        """Publish multiple events to the outbox."""
        db_events = [
            Event(
                event_type=event.event_type,
                aggregate_type=event.aggregate_type,
                aggregate_id=event.aggregate_id,
                organization_id=event.organization_id,
                user_id=event.user_id,
                payload=event.payload,
                metadata=event.metadata,
                priority=event.priority,
                scheduled_at=event.scheduled_at,
            )
            for event in events
        ]
        self.db.add_all(db_events)
        await self.db.flush()


class EventProcessor:
    """Process events from the outbox and publish to subscribers."""
    
    def __init__(self, db: AsyncSession, publisher: EventPublisher):
        self.db = db
        self.publisher = publisher
        self.settings = get_settings()
        self._handlers: Dict[str, List[Callable[[EventData], Awaitable[None]]]] = {}
    
    def register_handler(self, event_type: str, handler: Callable[[EventData], Awaitable[None]]) -> None:
        """Register an event handler."""
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)
    
    async def process_pending(self, batch_size: int = 100) -> int:
        """Process pending events from the outbox."""
        from openagent.db.models import Event
        
        # Get pending events
        result = await self.db.execute(
            select(Event)
            .where(
                Event.status == "pending",
                (Event.scheduled_at.is_(None)) | (Event.scheduled_at <= datetime.now(timezone.utc))
            )
            .order_by(Event.priority.desc(), Event.created_at)
            .limit(batch_size)
        )
        events = list(result.scalars().all())
        
        if not events:
            return 0
        
        processed = 0
        for event in events:
            try:
                # Mark as processing
                event.status = "published"
                event.published_at = datetime.now(timezone.utc)
                await self.db.flush()
                
                # Create event data
                event_data = EventData(
                    event_type=event.event_type,
                    aggregate_type=event.aggregate_type,
                    aggregate_id=event.aggregate_id,
                    payload=event.payload,
                    organization_id=event.organization_id,
                    user_id=event.user_id,
                    metadata=event.metadata,
                    priority=EventPriority(event.priority),
                )
                
                # Call handlers
                handlers = self._handlers.get(event.event_type, [])
                for handler in handlers:
                    await handler(event_data)
                
                processed += 1
                
            except Exception as e:
                # Mark as failed
                event.retry_count += 1
                event.last_error = str(e)
                if event.retry_count >= event.max_retries:
                    event.status = "failed"
                else:
                    event.status = "pending"
                await self.db.flush()
        
        return processed
    
    async def process_event(self, event: EventData) -> None:
        """Process a single event immediately (for synchronous processing)."""
        handlers = self._handlers.get(event.event_type, [])
        for handler in handlers:
            await handler(event)


class EventService:
    """High-level event service for publishing and processing events."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.publisher = DatabaseEventPublisher(db)
        self.processor = EventProcessor(db, self.publisher)
    
    async def publish(
        self,
        event_type: str,
        aggregate_type: str,
        aggregate_id: uuid.UUID,
        payload: Dict[str, Any],
        organization_id: Optional[uuid.UUID] = None,
        user_id: Optional[uuid.UUID] = None,
        metadata: Optional[Dict[str, Any]] = None,
        priority: EventPriority = EventPriority.NORMAL,
        scheduled_at: Optional[datetime] = None,
    ) -> None:
        """Publish an event."""
        event = EventData(
            event_type=event_type,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            payload=payload,
            organization_id=organization_id,
            user_id=user_id,
            metadata=metadata or {},
            priority=priority,
            scheduled_at=scheduled_at,
        )
        await self.publisher.publish(event)
    
    async def publish_batch(
        self,
        events: List[EventData],
    ) -> None:
        """Publish multiple events."""
        await self.publisher.publish_batch(events)
    
    def register_handler(self, event_type: str, handler: Callable[[EventData], Awaitable[None]]) -> None:
        """Register an event handler."""
        self.processor.register_handler(event_type, handler)
    
    async def process_pending(self, batch_size: int = 100) -> int:
        """Process pending events from the outbox."""
        return await self.processor.process_pending(batch_size)
    
    async def get_event_subscription(
        self,
        organization_id: uuid.UUID,
        event_types: List[str],
        callback_url: str,
        secret: str,
    ) -> None:
        """Create an event subscription for webhook delivery."""
        from openagent.core.security import hash_token
        from openagent.db.models import EventSubscription
        
        secret_hash = hash_token(secret)
        secret_prefix = secret[:8]
        
        subscription = EventSubscription(
            organization_id=organization_id,
            event_types=event_types,
            callback_url=callback_url,
            secret_hash=secret_hash,
            secret_prefix=secret_prefix,
        )
        self.db.add(subscription)
        await self.db.flush()


# Dependency for event service - lazy import to avoid circular imports
async def get_event_service(db: AsyncSession = Depends(lambda: _get_db())) -> EventService:
    return EventService(db)


# Import for EventData
from fastapi import Depends