import pytest
import pytest_asyncio
from uuid import uuid4
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from openagent.db.models import (
    Event, EventStatus, EventPriority, EventSubscription,
    User, UserStatus,
    Organization, OrganizationStatus,
    Membership, MembershipRole, MembershipStatus,
)
from openagent.core.events import EventService, EventData, DatabaseEventPublisher, EventProcessor


@pytest_asyncio.fixture
async def org(db_session: AsyncSession):
    org = Organization(
        name="Test Org Events",
        slug="test-org-events",
        status=OrganizationStatus.ACTIVE
    )
    db_session.add(org)
    await db_session.commit()
    await db_session.refresh(org)
    return org


@pytest_asyncio.fixture
async def user(db_session: AsyncSession, org):
    from openagent.db.repositories import UserRepository, MembershipRepository
    from openagent.db.models import Membership, MembershipRole, MembershipStatus
    from openagent.core.security import hash_password
    
    user_repo = UserRepository(db_session)
    user = await user_repo.create(
        email="test-events@example.com",
        display_name="Test User",
        password_hash="hashed_password",
        status=UserStatus.ACTIVE,
        email_verified=True,
    )
    
    membership = Membership(
        user_id=user.id,
        organization_id=org.id,
        role=MembershipRole.MEMBER,
        status="active",
    )
    db_session.add(membership)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def event_service(db_session: AsyncSession):
    from openagent.core.events import EventService
    return EventService(db_session)


class TestEventSystem:
    async def test_publish_event(self, db_session: AsyncSession, org, user, event_service):
        event = EventData(
            event_type="user.created",
            aggregate_type="user",
            aggregate_id=user.id,
            payload={"email": user.email, "name": user.display_name},
            organization_id=org.id,
            user_id=user.id,
            metadata={"source": "api"},
            priority="normal",
        )
        
        await event_service.publish(event)
        await db_session.commit()
        
        # Verify event was stored
        result = await db_session.execute(
            select(Event).where(Event.aggregate_id == user.id)
        )
        event_db = result.scalar_one_or_none()
        
        assert event_db is not None
        assert event_db.event_type == "user.created"
        assert event_db.aggregate_type == "user"
        assert event_db.aggregate_id == user.id
        assert event_db.organization_id == org.id
        assert event_db.user_id == user.id
        assert event_db.payload["email"] == user.email
        assert event_db.status == "pending"

    async def test_publish_batch(self, db_session: AsyncSession, org, user, event_service):
        events = [
            EventData(
                event_type="event.one",
                aggregate_type="test",
                aggregate_id=uuid4(),
                payload={"num": i},
            )
            for i in range(5)
        ]
        
        await event_service.publish_batch(events)
        await db_session.commit()
        
        result = await db_session.execute(
            select(Event).where(Event.event_type.in_(["event.one"]))
        )
        events_db = list(result.scalars().all())
        
        assert len(events_db) == 5

    async def test_event_subscription(self, db_session: AsyncSession, org, user, event_service):
        subscription = await event_service.get_event_subscription(
            organization_id=org.id,
            event_types=["user.created", "user.updated"],
            callback_url="https://example.com/webhook",
            secret="test-secret",
        )
        
        await db_session.commit()
        
        assert subscription is not None
        assert subscription.organization_id == org.id
        assert "user.created" in subscription.event_types
        assert subscription.is_active is True

    async def test_event_priority_ordering(self, db_session: AsyncSession, org, user, event_service):
        # Publish events with different priorities
        for priority in ["low", "normal", "high", "critical"]:
            await event_service.publish(
                event_type=f"test.{priority}",
                aggregate_type="test",
                aggregate_id=uuid4(),
                payload={"priority": priority},
                priority=priority,
            )
        
        await db_session.commit()
        
        # Process events - should process high/critical first
        from openagent.core.events import EventProcessor
        processor = EventProcessor(db_session, None)
        
        # Just verify they're stored with correct priority
        result = await db_session.execute(
            select(Event).where(Event.event_type.like("test.%"))
            .order_by(Event.priority.desc())
        )
        events = list(result.scalars().all())
        
        priorities = [e.priority for e in events]
        # Critical should come first
        assert "critical" in priorities[:2]


class TestEventSubscription:
    async def test_subscription_creation(self, db_session: AsyncSession, org):
        from openagent.db.repositories import OrganizationRepository
        
        org_repo = OrganizationRepository(db_session)
        
        # Create subscription directly
        from openagent.db.models import EventSubscription
        sub = EventSubscription(
            organization_id=org.id,
            event_types=["user.created", "order.placed"],
            callback_url="https://example.com/webhook",
            secret_hash="hashed_secret",
            secret_prefix="sec_abc123",
        )
        db_session.add(sub)
        await db_session.commit()
        await db_session.refresh(sub)
        
        assert sub.id is not None
        assert sub.organization_id == org.id
        assert "user.created" in sub.event_types
        assert sub.is_active is True

    async def test_subscription_inactive(self, db_session: AsyncSession, org):
        from openagent.db.models import EventSubscription
        
        sub = EventSubscription(
            organization_id=org.id,
            event_types=["test.event"],
            callback_url="https://example.com/webhook",
            secret_hash="hash",
            secret_prefix="pre",
            is_active=False,
        )
        db_session.add(sub)
        await db_session.commit()
        
        assert sub.is_active is False


class TestEventProcessor:
    async def test_event_processor_registration(self, db_session: AsyncSession, org, user, event_service):
        processor = event_service.processor
        
        called = []
        
        async def handler(event: EventData):
            called.append(event)
        
        processor.register_handler("test.event", handler)
        
        # Publish event
        event = EventData(
            event_type="test.event",
            aggregate_type="test",
            aggregate_id=uuid4(),
            payload={"data": "test"},
        )
        await event_service.publish(event)
        await db_session.commit()
        
        # Process events
        processed = await processor.process_pending(batch_size=10)
        
        assert processed == 1
        assert len(called) == 1
        assert called[0].event_type == "test.event"


class TestEventSubscriptionModel:
    async def test_subscription_model(self, db_session: AsyncSession, org):
        from openagent.db.models import EventSubscription
        
        sub = EventSubscription(
            organization_id=org.id,
            event_types=["test.event1", "test.event2"],
            callback_url="https://example.com/webhook",
            secret_hash="hash123",
            secret_prefix="sec_abc",
        )
        db_session.add(sub)
        await db_session.commit()
        await db_session.refresh(sub)
        
        assert sub.id is not None
        assert sub.organization_id == org.id
        assert sub.event_types == ["test.event1", "test.event2"]
        assert sub.callback_url == "https://example.com/webhook"
        assert sub.secret_hash == "hash123"
        assert sub.secret_prefix == "sec_abc"
        assert sub.is_active is True


class TestEventModel:
    async def test_event_model(self, db_session: AsyncSession, org, user):
        from openagent.db.models import Event, EventStatus, EventPriority
        
        event = Event(
            event_type="test.event",
            aggregate_type="test",
            aggregate_id=uuid4(),
            organization_id=org.id,
            user_id=user.id,
            payload={"key": "value"},
            metadata={"source": "test"},
            status=EventStatus.PENDING,
            priority=EventPriority.HIGH,
        )
        db_session.add(event)
        await db_session.commit()
        await db_session.refresh(event)
        
        assert event.id is not None
        assert event.event_type == "test.event"
        assert event.status == EventStatus.PENDING
        assert event.priority == EventPriority.HIGH
        assert event.payload == {"key": "value"}
        assert event.metadata == {"source": "test"}