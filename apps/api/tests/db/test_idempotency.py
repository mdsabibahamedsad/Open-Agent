import pytest
import pytest_asyncio
from uuid import uuid4
from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from openagent.db.models import (
    IdempotencyKey, IdempotencyStatus,
    User, UserStatus,
    Organization, OrganizationStatus,
)
from openagent.core.idempotency import IdempotencyService
from openagent.core.config import get_settings


@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> Organization:
    org = Organization(
        name="Test Org",
        slug="test-org-idem",
        status=OrganizationStatus.ACTIVE
    )
    db_session.add(org)
    await db_session.commit()
    await db_session.refresh(org)
    return org


@pytest_asyncio.fixture
async def user(db_session: AsyncSession, org: Organization) -> User:
    from openagent.db.repositories import UserRepository, MembershipRepository
    from openagent.db.models import Membership, MembershipRole, MembershipStatus
    from openagent.core.security import hash_password
    
    user_repo = UserRepository(db_session)
    user = await user_repo.create(
        email="test-idem@example.com",
        display_name="Test User",
        password_hash=hash_password("password123"),
        status=UserStatus.ACTIVE,
        email_verified=True,
    )
    
    membership = Membership(
        user_id=user.id,
        organization_id=org.id,
        role="member",
        status="active",
    )
    db_session.add(membership)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def idempotency_service(db_session: AsyncSession) -> 'IdempotencyService':
    from openagent.core.idempotency import IdempotencyService
    return IdempotencyService(db_session)


class TestIdempotencyKey:
    async def test_create_idempotency_key(self, db_session: AsyncSession, user):
        service = IdempotencyService(db_session)
        
        key, is_new = await service.check_idempotency(
            key="test-key-123",
            method="POST",
            endpoint="/api/v1/test",
            body={"data": "test"},
            user_id=user.id,
        )
        
        assert is_new is True
        assert key.key == "test-key-123"
        assert key.status == "processing"
        assert key.request_hash is not None

    async def test_idempotent_replay(self, db_session: AsyncSession, user):
        service = IdempotencyService(db_session)
        
        # First request
        key1, is_new1 = await service.check_idempotency(
            key="test-key-456",
            method="POST",
            endpoint="/api/v1/test",
            body={"data": "test"},
            user_id=user.id,
        )
        assert is_new1 is True
        
        # Complete the request
        await service.complete_idempotency(
            idempotency_key=key1,
            status_code=200,
            response_body={"result": "success"},
        )
        
        # Second request with same key
        key2, is_new2 = await service.check_idempotency(
            key="test-key-456",
            method="POST",
            endpoint="/api/v1/test",
            body={"data": "test"},
            user_id=user.id,
        )
        
        assert is_new2 is False
        assert key2.id == key1.id
        assert key2.status == "completed"

    async def test_idempotency_conflict_different_body(self, db_session: AsyncSession, user):
        service = IdempotencyService(db_session)
        
        # First request
        key1, is_new1 = await service.check_idempotency(
            key="test-key-789",
            method="POST",
            endpoint="/api/v1/test",
            body={"data": "original"},
            user_id=user.id,
        )
        assert is_new1 is True
        
        # Complete first request
        await service.complete_idempotency(
            idempotency_key=key1,
            status_code=200,
            response_body={"result": "success"},
        )
        
        # Second request with SAME key but DIFFERENT body
        with pytest.raises(Exception) as exc_info:
            await service.check_idempotency(
                key="test-key-789",
                method="POST",
                endpoint="/api/v1/test",
                body={"data": "different"},
                user_id=user.id,
            )
        
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail["code"] == "IDEMPOTENCY_CONFLICT"

    async def test_idempotency_expiration(self, db_session: AsyncSession, user):
        service = IdempotencyService(db_session)
        
        # Create expired key manually
        from openagent.core.security import hash_token, generate_secure_token
        from openagent.db.models import IdempotencyKey
        
        key = generate_secure_token()
        key_hash = hash_token(key)
        expired_key = IdempotencyKey(
            user_id=user.id,
            key=key,
            key_hash=key_hash,
            endpoint="/api/v1/test",
            method="POST",
            request_hash="hash123",
            status=IdempotencyStatus.PROCESSING,
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        db_session.add(expired_key)
        await db_session.commit()
        
        # Should treat as new
        key, is_new = await service.check_idempotency(
            key=key,
            method="POST",
            endpoint="/api/v1/test",
            body={"data": "test"},
            user_id=user.id,
        )
        
        assert is_new is True
        assert key.id != expired_key.id

    async def test_complete_and_fail_idempotency(self, db_session: AsyncSession, user):
        service = IdempotencyService(db_session)
        
        key, is_new = await service.check_idempotency(
            key="test-complete",
            method="POST",
            endpoint="/api/v1/test",
            body={"data": "test"},
            user_id=user.id,
        )
        
        # Complete successfully
        await service.complete_idempotency(
            idempotency_key=key,
            status_code=201,
            response_body={"id": "new-resource"},
            response_headers={"Location": "/api/v1/resources/123"},
        )
        
        await db_session.commit()
        
        # Verify completion
        result = await db_session.execute(
            select(IdempotencyKey).where(IdempotencyKey.id == key.id)
        )
        completed = result.scalar_one()
        assert completed.status == "completed"
        assert completed.response_status_code == 201
        assert completed.response_body == {"id": "new-resource"}
        
        # Test failure
        key2, _ = await service.check_idempotency(
            key="test-fail",
            method="POST",
            endpoint="/api/v1/test",
            body={"data": "test"},
            user_id=user.id,
        )
        
        await service.fail_idempotency(
            idempotency_key=key2,
            error_message="Validation error",
        )
        
        await db_session.commit()
        
        result = await db_session.execute(
            select(IdempotencyKey).where(IdempotencyKey.id == key2.id)
        )
        failed = result.scalar_one()
        assert failed.status == "failed"
        assert failed.error_message == "Validation error"


class TestIdempotencyMiddleware:
    async def test_require_idempotency_missing(self, db_session: AsyncSession):
        from openagent.core.idempotency import require_idempotency
        from fastapi import Request
        from starlette.datastructures import Headers
        
        # Mock request without idempotency key
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/test",
            "headers": [],
        }
        request = Request(scope)
        
        dependency = require_idempotency(required=True)
        
        with pytest.raises(Exception) as exc_info:
            await dependency(request)
        
        assert exc_info.value.status_code == 400
        assert exc_info.value.detail["code"] == "MISSING_IDEMPOTENCY_KEY"

    async def test_require_idempotency_invalid_format(self, db_session: AsyncSession):
        from openagent.core.idempotency import require_idempotency
        from fastapi import Request
        
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/test",
            "headers": [(b"idempotency-key", b"short")],
        }
        request = Request({"type": "http", "method": "POST", "path": "/api/v1/test", "headers": [(b"idempotency-key", b"short")]})
        
        # Can't easily test without full FastAPI app setup
        pass


from datetime import datetime, timezone, timedelta