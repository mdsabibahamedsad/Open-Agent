import pytest
import pytest_asyncio
from uuid import uuid4
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.db.models import (
    User, UserStatus,
    Organization, OrganizationStatus,
    Membership, MembershipRole, MembershipStatus,
    Session,
    EmailVerificationToken,
    PasswordResetToken,
    PlatformOwner, PlatformOwnerStatus,
    SecurityEvent, SecurityEventType,
)
from openagent.db.repositories import (
    UserRepository,
    SessionRepository,
)
from openagent.services.auth import (
    AuthenticationService,
    MasterAccountService,
    AuthenticationError,
    InvalidCredentialsError,
    AccountNotVerifiedError,
    AccountSuspendedError,
    TokenExpiredError,
    TokenInvalidError,
    PasswordPolicyError,
    EmailAlreadyExistsError,
)
from openagent.core.security import hash_password, verify_password, create_token_pair, hash_token, verify_token


@pytest_asyncio.fixture
async def auth_service(db_session: AsyncSession) -> AuthenticationService:
    return AuthenticationService(db_session)


@pytest_asyncio.fixture
async def master_service(db_session: AsyncSession) -> MasterAccountService:
    return MasterAccountService(db_session)


@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession) -> User:
    repo = UserRepository(db_session)
    user = await repo.create(
        email="test@example.com",
        display_name="Test User",
        password_hash=hash_password("securepassword123"),
        status=UserStatus.ACTIVE,
        email_verified=True,
    )
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def unverified_user(db_session: AsyncSession) -> User:
    repo = UserRepository(db_session)
    user = await repo.create(
        email="unverified@example.com",
        display_name="Unverified User",
        password_hash=hash_password("securepassword123"),
        status=UserStatus.PENDING_VERIFICATION,
        email_verified=False,
    )
    await db_session.commit()
    await db_session.refresh(user)
    return user


class TestPasswordSecurity:
    def test_hash_password(self):
        password = "securepassword123"
        hash1 = hash_password(password)
        hash2 = hash_password(password)
        
        # Hashes should be different (due to salt)
        assert hash1 != hash2
        
        # Both should verify
        assert verify_password(password, hash1)
        assert verify_password(password, hash2)
    
    def test_verify_wrong_password(self):
        password = "securepassword123"
        hash1 = hash_password(password)
        
        assert not verify_password("wrongpassword", hash1)
    
    def test_empty_password_raises(self):
        with pytest.raises(ValueError):
            hash_password("")
    
    def test_long_password_raises(self):
        with pytest.raises(ValueError):
            hash_password("a" * 5000)


class TestTokenManagement:
    def test_create_token_pair(self):
        token, token_hash, expires_at = create_token_pair()
        
        assert token is not None
        assert token_hash is not None
        assert expires_at is not None
        assert verify_token(token, token_hash)
        assert not verify_token("wrong", token_hash)
    
    def test_token_expiration(self):
        from openagent.core.security.tokens import is_expired, create_expiration
        
        future = create_expiration(60)
        past = create_expiration(-60)
        
        assert not is_expired(future)
        assert is_expired(past)


class TestUserRegistration:
    async def test_register_success(self, auth_service: AuthenticationService, db_session: AsyncSession):
        user, token = await auth_service.register(
            email="newuser@example.com",
            password="securepassword123",
            display_name="New User",
            ip_address="127.0.0.1",
            user_agent="Test Agent",
        )
        
        await db_session.commit()
        
        assert user is not None
        assert user.email == "newuser@example.com"
        assert user.display_name == "New User"
        assert user.status == UserStatus.PENDING_VERIFICATION
        assert user.email_verified is False
        assert token is not None
        
        # Verify email verification token was created
        result = await db_session.execute(
            select(EmailVerificationToken).where(EmailVerificationToken.user_id == user.id)
        )
        ev_token = result.scalar_one_or_none()
        assert ev_token is not None
        assert ev_token.email == "newuser@example.com"
        assert ev_token.used_at is None
    
    async def test_register_duplicate_email(self, auth_service: AuthenticationService, test_user: User):
        with pytest.raises(EmailAlreadyExistsError):
            await auth_service.register(
                email=test_user.email,
                password="securepassword123",
            )
    
    async def test_register_weak_password(self, auth_service: AuthenticationService):
        with pytest.raises(PasswordPolicyError):
            await auth_service.register(
                email="weak@example.com",
                password="weak",
            )


class TestEmailVerification:
    async def test_verify_email_success(self, auth_service: AuthenticationService, db_session: AsyncSession):
        # Create user and verification token
        user, token = await auth_service.register(
            email="verify@example.com",
            password="securepassword123",
        )
        await db_session.commit()
        
        # Verify email
        verified_user = await auth_service.verify_email(token)
        await db_session.commit()
        
        assert verified_user.id == user.id
        assert verified_user.email_verified is True
        assert verified_user.status == UserStatus.ACTIVE
        
        # Token should be marked as used
        result = await db_session.execute(
            select(EmailVerificationToken).where(EmailVerificationToken.user_id == user.id)
        )
        ev_token = result.scalar_one_or_none()
        assert ev_token.used_at is not None
    
    async def test_verify_email_expired_token(self, auth_service: AuthenticationService, db_session: AsyncSession):
        from openagent.db.models import EmailVerificationToken
        from openagent.core.security import hash_token
        
        # Create expired token
        user = await UserRepository(db_session).create(
            email="expired@example.com",
            password_hash=hash_password("securepassword123"),
            status=UserStatus.PENDING_VERIFICATION,
        )
        await db_session.flush()
        
        expired_token = EmailVerificationToken(
            user_id=user.id,
            token_hash=hash_token("expired_token"),
            email="expired@example.com",
            expires_at=datetime.now(timezone.utc),
        )
        db_session.add(expired_token)
        await db_session.commit()
        
        with pytest.raises(TokenExpiredError):
            await auth_service.verify_email("expired_token")
    
    async def test_verify_email_used_token(self, auth_service: AuthenticationService, db_session: AsyncSession):
        user, token = await auth_service.register(
            email="used@example.com",
            password="securepassword123",
        )
        await db_session.commit()
        
        # First verification
        await auth_service.verify_email(token)
        await db_session.commit()
        
        # Second verification should fail
        with pytest.raises(TokenInvalidError):
            await auth_service.verify_email(token)


class TestUserLogin:
    async def test_login_success(self, auth_service: AuthenticationService, test_user: User, db_session: AsyncSession):
        user, session, session_token = await auth_service.login(
            email=test_user.email,
            password="securepassword123",
            ip_address="127.0.0.1",
            user_agent="Test Agent",
        )
        
        await db_session.commit()
        
        assert user.id == test_user.id
        assert session is not None
        assert session_token is not None
        assert session.user_id == test_user.id
        assert session.revoked_at is None
    
    async def test_login_invalid_credentials(self, auth_service: AuthenticationService, test_user: User):
        with pytest.raises(InvalidCredentialsError):
            await auth_service.login(
                email=test_user.email,
                password="wrongpassword",
            )
    
    async def test_login_unverified_user(self, auth_service: AuthenticationService, unverified_user: User):
        with pytest.raises(AccountNotVerifiedError):
            await auth_service.login(
                email=unverified_user.email,
                password="securepassword123",
            )
    
    async def test_login_suspended_user(self, auth_service: AuthenticationService, db_session: AsyncSession):
        repo = UserRepository(db_session)
        suspended = await repo.create(
            email="suspended@example.com",
            password_hash=hash_password("securepassword123"),
            status=UserStatus.SUSPENDED,
            email_verified=True,
        )
        await db_session.commit()
        
        with pytest.raises(AccountSuspendedError):
            await auth_service.login(
                email=suspended.email,
                password="securepassword123",
            )
    
    async def test_login_nonexistent_user(self, auth_service: AuthenticationService):
        with pytest.raises(InvalidCredentialsError):
            await auth_service.login(
                email="nonexistent@example.com",
                password="securepassword123",
            )


class TestLogout:
    async def test_logout_single(self, auth_service: AuthenticationService, test_user: User, db_session: AsyncSession):
        # Login first
        user, session, session_token = await auth_service.login(
            email=test_user.email,
            password="securepassword123",
        )
        await db_session.commit()
        
        # Logout
        await auth_service.logout(session)
        await db_session.commit()
        
        # Session should be revoked
        result = await db_session.execute(
            select(Session).where(Session.id == session.id)
        )
        revoked_session = result.scalar_one_or_none()
        assert revoked_session.revoked_at is not None
    
    async def test_logout_all(self, auth_service: AuthenticationService, test_user: User, db_session: AsyncSession):
        # Create multiple sessions
        session_repo = SessionRepository(db_session)
        
        for i in range(3):
            session_token, token_hash, expires_at = create_token_pair()
            session = Session(
                user_id=test_user.id,
                token_hash=token_hash,
                expires_at=expires_at,
            )
            db_session.add(session)
        await db_session.commit()
        
        # Logout all
        revoked_count = await auth_service.logout_all(test_user.id)
        await db_session.commit()
        
        assert revoked_count == 3


class TestPasswordReset:
    async def test_request_password_reset(self, auth_service: AuthenticationService, test_user: User, db_session: AsyncSession):
        await auth_service.request_password_reset(
            email=test_user.email,
            ip_address="127.0.0.1",
        )
        await db_session.commit()
        
        # Reset token should be created
        result = await db_session.execute(
            select(PasswordResetToken).where(PasswordResetToken.user_id == test_user.id)
        )
        pr_token = result.scalar_one_or_none()
        assert pr_token is not None
        assert pr_token.used_at is None
    
    async def test_request_password_reset_nonexistent(self, auth_service: AuthenticationService):
        # Should not raise error (prevents enumeration)
        await auth_service.request_password_reset(email="nonexistent@example.com")
    
    async def test_reset_password_success(self, auth_service: AuthenticationService, test_user: User, db_session: AsyncSession):
        # Create reset token
        token, token_hash, expires_at = create_token_pair()
        pr_token = PasswordResetToken(
            user_id=test_user.id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        db_session.add(pr_token)
        await db_session.commit()
        
        # Reset password
        user = await auth_service.reset_password(token, "newsecurepassword123")
        await db_session.commit()
        
        assert user.id == test_user.id
        assert verify_password("newsecurepassword123", user.password_hash)
        
        # Token should be marked as used
        result = await db_session.execute(
            select(PasswordResetToken).where(PasswordResetToken.id == pr_token.id)
        )
        used_token = result.scalar_one_or_none()
        assert used_token.used_at is not None
        
        # All sessions should be revoked
        sessions = await auth_service.get_user_sessions(test_user.id)
        assert len(sessions) == 0
    
    async def test_reset_password_expired_token(self, auth_service: AuthenticationService, test_user: User, db_session: AsyncSession):
        expired_token = PasswordResetToken(
            user_id=test_user.id,
            token_hash=hash_token("expired"),
            expires_at=datetime.now(timezone.utc),
        )
        db_session.add(expired_token)
        await db_session.commit()
        
        with pytest.raises(TokenExpiredError):
            await auth_service.reset_password("expired", "newpassword123")
    
    async def test_reset_password_invalid_token(self, auth_service: AuthenticationService):
        with pytest.raises(TokenInvalidError):
            await auth_service.reset_password("invalid", "newpassword123")


class TestChangePassword:
    async def test_change_password_success(self, auth_service: AuthenticationService, test_user: User, db_session: AsyncSession):
        user = await auth_service.change_password(
            user_id=test_user.id,
            current_password="securepassword123",
            new_password="newsecurepassword123",
        )
        await db_session.commit()
        
        assert user.id == test_user.id
        assert verify_password("newsecurepassword123", user.password_hash)
    
    async def test_change_password_wrong_current(self, auth_service: AuthenticationService, test_user: User):
        with pytest.raises(InvalidCredentialsError):
            await auth_service.change_password(
                user_id=test_user.id,
                current_password="wrongpassword",
                new_password="newsecurepassword123",
            )


class TestSessionManagement:
    async def test_get_session(self, auth_service: AuthenticationService, test_user: User, db_session: AsyncSession):
        user, session, session_token = await auth_service.login(
            email=test_user.email,
            password="securepassword123",
        )
        await db_session.commit()
        
        retrieved = await auth_service.get_session(session_token)
        assert retrieved is not None
        assert retrieved.id == session.id
    
    async def test_get_session_invalid(self, auth_service: AuthenticationService):
        retrieved = await auth_service.get_session("invalid_token")
        assert retrieved is None
    
    async def test_get_session_expired(self, auth_service: AuthenticationService, test_user: User, db_session: AsyncSession):
        # Create expired session
        session_token, token_hash, expires_at = create_token_pair()
        expired_session = Session(
            user_id=test_user.id,
            token_hash=token_hash,
            expires_at=datetime.now(timezone.utc),
        )
        db_session.add(expired_session)
        await db_session.commit()
        
        retrieved = await auth_service.get_session(session_token)
        assert retrieved is None
    
    async def test_get_user_sessions(self, auth_service: AuthenticationService, test_user: User, db_session: AsyncSession):
        # Create multiple sessions
        for i in range(3):
            session_token, token_hash, expires_at = create_token_pair()
            session = Session(
                user_id=test_user.id,
                token_hash=token_hash,
                expires_at=expires_at,
            )
            db_session.add(session)
        await db_session.commit()
        
        sessions = await auth_service.get_user_sessions(test_user.id)
        assert len(sessions) == 3
    
    async def test_revoke_session(self, auth_service: AuthenticationService, test_user: User, db_session: AsyncSession):
        user, session, session_token = await auth_service.login(
            email=test_user.email,
            password="securepassword123",
        )
        await db_session.commit()
        
        success = await auth_service.revoke_session(session.id, test_user.id)
        await db_session.commit()
        
        assert success is True
        
        # Session should be revoked
        result = await db_session.execute(
            select(Session).where(Session.id == session.id)
        )
        revoked = result.scalar_one_or_none()
        assert revoked.revoked_at is not None
    
    async def test_revoke_session_not_owner(self, auth_service: AuthenticationService, test_user: User, db_session: AsyncSession):
        # Create another user
        repo = UserRepository(db_session)
        other_user = await repo.create(
            email="other@example.com",
            password_hash=hash_password("securepassword123"),
            status=UserStatus.ACTIVE,
            email_verified=True,
        )
        await db_session.commit()
        
        # Create session for other user
        session_token, token_hash, expires_at = create_token_pair()
        session = Session(
            user_id=other_user.id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        db_session.add(session)
        await db_session.commit()
        
        # Try to revoke other user's session
        success = await auth_service.revoke_session(session.id, test_user.id)
        
        assert success is False


class TestMasterAccount:
    async def test_initialize_master_account(self, master_service: MasterAccountService, db_session: AsyncSession):
        user, platform_owner = await master_service.initialize_master_account(
            email="master@example.com",
            password="mastersecurepassword123",
            display_name="Master Owner",
        )
        
        await db_session.commit()
        
        assert user.email == "master@example.com"
        assert user.is_superadmin is True
        assert user.email_verified is True
        assert user.status == UserStatus.ACTIVE
        
        assert platform_owner.user_id == user.id
        assert platform_owner.status == PlatformOwnerStatus.ACTIVE
        assert platform_owner.mfa_enabled is False
    
    async def test_initialize_master_account_already_exists(self, master_service: MasterAccountService, db_session: AsyncSession):
        # Create first master
        await master_service.initialize_master_account(
            email="master1@example.com",
            password="mastersecurepassword123",
        )
        await db_session.commit()
        
        # Try to create second
        with pytest.raises(AuthenticationError) as exc:
            await master_service.initialize_master_account(
                email="master2@example.com",
                password="mastersecurepassword123",
            )
        
        assert exc.value.code == "MASTER_EXISTS"
    
    async def test_master_login_success(self, master_service: MasterAccountService, db_session: AsyncSession):
        await master_service.initialize_master_account(
            email="master@example.com",
            password="mastersecurepassword123",
        )
        await db_session.commit()
        
        user, session, session_token = await master_service.master_login(
            email="master@example.com",
            password="mastersecurepassword123",
        )
        
        await db_session.commit()
        
        assert user.id == user.id
        assert session is not None
        
        # Platform owner last_login_at should be updated
        result = await db_session.execute(
            select(PlatformOwner).where(PlatformOwner.user_id == user.id)
        )
        po = result.scalar_one_or_none()
        assert po.last_login_at is not None
    
    async def test_master_login_not_owner(self, master_service: MasterAccountService, test_user: User):
        with pytest.raises(AuthenticationError) as exc:
            await master_service.master_login(
                email=test_user.email,
                password="securepassword123",
            )
        
        assert exc.value.code == "NOT_MASTER"


class TestSecurityEvents:
    async def test_security_event_logged_on_login(self, auth_service: AuthenticationService, test_user: User, db_session: AsyncSession):
        await auth_service.login(
            email=test_user.email,
            password="securepassword123",
            ip_address="127.0.0.1",
            user_agent="Test Agent",
        )
        await db_session.commit()
        
        result = await db_session.execute(
            select(SecurityEvent)
            .where(
                SecurityEvent.user_id == test_user.id,
                SecurityEvent.event_type == SecurityEventType.LOGIN_SUCCESS
            )
        )
        event = result.scalar_one_or_none()
        assert event is not None
        assert event.ip_address == "127.0.0.1"
        assert event.user_agent == "Test Agent"
    
    async def test_security_event_logged_on_failed_login(self, auth_service: AuthenticationService, test_user: User, db_session: AsyncSession):
        with pytest.raises(InvalidCredentialsError):
            await auth_service.login(
                email=test_user.email,
                password="wrongpassword",
                ip_address="127.0.0.1",
            )
        await db_session.commit()
        
        result = await db_session.execute(
            select(SecurityEvent)
            .where(
                SecurityEvent.user_id == test_user.id,
                SecurityEvent.event_type == SecurityEventType.LOGIN_FAILED
            )
        )
        event = result.scalar_one_or_none()
        assert event is not None
        assert event.metadata.get("reason") == "invalid_password"


from sqlalchemy import select