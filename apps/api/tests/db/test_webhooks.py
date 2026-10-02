import pytest
import pytest_asyncio
from uuid import uuid4
from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from openagent.db.models import (
    Webhook, WebhookStatus, WebhookEvent, WebhookEventStatus,
    User, UserStatus,
    Organization, OrganizationStatus,
    Membership, MembershipRole, MembershipStatus,
)
from openagent.core.webhooks import WebhookService


@pytest_asyncio.fixture
async def org(db_session: AsyncSession):
    org = Organization(
        name="Test Org Webhooks",
        slug="test-org-webhooks",
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
        email="test-webhooks@example.com",
        display_name="Test User",
        password_hash="hashed_password",
        status=UserStatus.ACTIVE,
        email_verified=True,
    )
    
    from openagent.db.models import Membership, MembershipRole, MembershipStatus
    membership = Membership(
        user_id=user.id,
        organization_id=org.id,
        role=MembershipRole.MEMBER,
        status=MembershipStatus.ACTIVE,
    )
    db_session.add(membership)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def webhook_service(db_session: AsyncSession):
    from openagent.core.webhooks import WebhookService
    return WebhookService(db_session)


class TestWebhookService:
    async def test_create_webhook(self, db_session: AsyncSession, org, user, webhook_service):
        webhook, secret = await webhook_service.create_webhook(
            organization_id=org.id,
            name="Test Webhook",
            url="https://example.com/webhook",
            event_types=["user.created", "user.updated"],
            invited_by=user.id,
        )
        
        await db_session.commit()
        
        assert webhook.id is not None
        assert webhook.name == "Test Webhook"
        assert webhook.url == "https://example.com/webhook"
        assert webhook.event_types == ["user.created", "user.updated"]
        assert webhook.is_active is True
        assert webhook.secret_hash is not None
        assert webhook.secret_prefix == secret[:8]
        assert secret is not None
        assert len(secret) > 20

    async def test_update_webhook(self, db_session: AsyncSession, org, user, webhook_service):
        webhook, secret = await webhook_service.create_webhook(
            organization_id=org.id,
            name="Original",
            url="https://example.com/webhook",
            event_types=["user.created"],
        )
        await db_session.commit()
        
        updated = await webhook_service.update_webhook(
            webhook_id=webhook.id,
            organization_id=org.id,
            name="Updated",
            url="https://newexample.com/webhook",
            event_types=["user.created", "user.updated"],
            is_active=False,
        )
        
        await db_session.commit()
        
        assert updated.name == "Updated"
        assert updated.url == "https://newexample.com/webhook"
        assert updated.event_types == ["user.created", "user.updated"]
        assert updated.is_active is False

    async def test_delete_webhook(self, db_session: AsyncSession, org, user, webhook_service):
        webhook, secret = await webhook_service.create_webhook(
            organization_id=org.id,
            name="To Delete",
            url="https://example.com/webhook",
            event_types=["user.created"],
        )
        await db_session.commit()
        
        success = await webhook_service.delete_webhook(webhook.id, org.id)
        assert success is True
        
        # Verify deleted
        deleted = await webhook_service.get_webhook(webhook.id, org.id)
        assert deleted is None

    async def test_get_webhook(self, db_session: AsyncSession, org, user, webhook_service):
        webhook, secret = await webhook_service.create_webhook(
            organization_id=org.id,
            name="Test Webhook",
            url="https://example.com/webhook",
            event_types=["user.created"],
        )
        await db_session.commit()
        
        found = await webhook_service.get_webhook(webhook.id, org.id)
        
        assert found is not None
        assert found.id == webhook.id
        assert found.name == "Test Webhook"

    async def test_list_webhooks(self, db_session: AsyncSession, org, user, webhook_service):
        # Create multiple webhooks
        for i in range(3):
            await webhook_service.create_webhook(
                organization_id=org.id,
                name=f"Webhook {i}",
                url=f"https://example.com/webhook/{i}",
                event_types=["user.created"],
            )
        
        await db_session.commit()
        
        webhooks = await webhook_service.list_webhooks(org.id, limit=10)
        
        assert len(webhooks) >= 3

    async def test_list_webhooks_filter_active(self, db_session: AsyncSession, org, user, webhook_service):
        # Create active
        await webhook_service.create_webhook(
            organization_id=org.id,
            name="Active",
            url="https://example.com/active",
            event_types=["user.created"],
            is_active=True,
        )
        
        # Create inactive
        webhook, _ = await webhook_service.create_webhook(
            organization_id=org.id,
            name="Inactive",
            url="https://example.com/inactive",
            event_types=["user.created"],
            is_active=False,
        )
        await db_session.commit()
        
        # List active only
        active = await webhook_service.list_webhooks(org.id, is_active=True)
        assert all(w.is_active for w in active)
        
        # List inactive only
        inactive = await webhook_service.list_webhooks(org.id, is_active=False)
        assert all(not w.is_active for w in inactive)


class TestWebhookDelivery:
    async def test_sign_payload(self, webhook_service):
        payload = b'{"test": "data"}'
        secret = "test-secret"
        
        signature = webhook_service._sign_payload(payload, secret)
        
        assert signature.startswith("sha256=")
        assert len(signature) == 71  # "sha256=" + 64 hex chars

    async def test_verify_signature(self, webhook_service):
        payload = b'{"test": "data"}'
        secret = "test-secret"
        
        signature = webhook_service._sign_payload(payload, secret)
        
        # Valid signature
        assert webhook_service._verify_signature(payload, signature, secret) is True
        
        # Invalid signature
        assert webhook_service._verify_signature(payload, "sha256=invalid", secret) is False
        
        # Wrong payload
        assert webhook_service._verify_signature(b"different", signature, secret) is False


class TestWebhookEventModel:
    async def test_webhook_event_model(self, db_session: AsyncSession, org, user):
        from openagent.db.models import Webhook, WebhookEvent, WebhookEventStatus, WebhookStatus
        from openagent.core.security import hash_token
        
        # Create webhook
        webhook = Webhook(
            organization_id=org.id,
            name="Test",
            url="https://example.com/webhook",
            event_types=["test.event"],
            secret_hash="hashed",
            secret_prefix="sec_",
        )
        db_session.add(webhook)
        await db_session.flush()
        
        # Create event
        event = WebhookEvent(
            webhook_id=webhook.id,
            event_type="test.event",
            payload={"key": "value"},
            status=WebhookEventStatus.PENDING,
            max_attempts=3,
        )
        db_session.add(event)
        await db_session.commit()
        
        assert event.id is not None
        assert event.webhook_id == webhook.id
        assert event.event_type == "test.event"
        assert event.payload == {"key": "value"}
        assert event.status == WebhookEventStatus.PENDING
        assert event.attempt == 0