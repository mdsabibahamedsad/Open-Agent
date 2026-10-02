import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, List
from sqlalchemy import select, update, delete, func
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from openagent.db.models import (
    User,
    UserStatus,
    Session,
    EmailVerificationToken,
    PasswordResetToken,
    PlatformOwner,
    PlatformOwnerStatus,
    SecurityEvent,
    SecurityEventType,
    Organization,
    Membership,
    MembershipRole,
    MembershipStatus,
)
from openagent.db.repositories import UserRepository, SessionRepository
from openagent.core.security import (
    hash_password,
    verify_password,
    needs_rehash,
    create_token_pair,
    hash_token,
    verify_token,
    generate_recovery_codes,
    hash_recovery_codes,
)
from openagent.core.config import get_settings
from openagent.services.email import EmailService, create_email_provider_from_settings

logger = structlog.get_logger("openagent.auth")


class AuthenticationError(Exception):
    """Base authentication error."""
    def __init__(self, message: str, code: str = "AUTH_ERROR"):
        self.message = message
        self.code = code
        super().__init__(message)


class InvalidCredentialsError(AuthenticationError):
    def __init__(self):
        super().__init__("Invalid email or password", "INVALID_CREDENTIALS")


class AccountNotVerifiedError(AuthenticationError):
    def __init__(self):
        super().__init__("Please verify your email address before logging in", "ACCOUNT_NOT_VERIFIED")


class AccountSuspendedError(AuthenticationError):
    def __init__(self):
        super().__init__("Your account has been suspended", "ACCOUNT_SUSPENDED")


class AccountLockedError(AuthenticationError):
    def __init__(self):
        super().__init__("Your account has been locked due to too many failed attempts", "ACCOUNT_LOCKED")


class TokenExpiredError(AuthenticationError):
    def __init__(self):
        super().__init__("Token has expired", "TOKEN_EXPIRED")


class TokenInvalidError(AuthenticationError):
    def __init__(self):
        super().__init__("Invalid or already used token", "TOKEN_INVALID")


class PasswordPolicyError(AuthenticationError):
    def __init__(self, message: str):
        super().__init__(message, "PASSWORD_POLICY_VIOLATION")


class EmailAlreadyExistsError(AuthenticationError):
    def __init__(self):
        super().__init__("An account with this email already exists", "EMAIL_ALREADY_EXISTS")


class AuthenticationService:
    """Core authentication service."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.user_repo = UserRepository(db)
        self.session_repo = SessionRepository(db)
        self.settings = get_settings()
        self.email_service = EmailService(create_email_provider_from_settings())
    
    async def _log_security_event(
        self,
        event_type: SecurityEventType,
        user_id: Optional[uuid.UUID] = None,
        organization_id: Optional[uuid.UUID] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        metadata: Optional[dict] = None,
        request_id: Optional[str] = None,
    ) -> None:
        """Log a security event."""
        event = SecurityEvent(
            user_id=user_id,
            organization_id=organization_id,
            event_type=event_type,
            ip_address=ip_address,
            user_agent=user_agent,
            metadata=metadata or {},
            request_id=request_id,
        )
        self.db.add(event)
        await self.db.flush()
    
    def _validate_password(self, password: str) -> None:
        """Validate password against policy."""
        settings = self.settings
        
        if len(password) < settings.PASSWORD_MIN_LENGTH:
            raise PasswordPolicyError(f"Password must be at least {settings.PASSWORD_MIN_LENGTH} characters")
        
        if len(password) > settings.PASSWORD_MAX_LENGTH:
            raise PasswordPolicyError(f"Password must not exceed {settings.PASSWORD_MAX_LENGTH} characters")
        
        if settings.PASSWORD_REQUIRE_UPPERCASE and not any(c.isupper() for c in password):
            raise PasswordPolicyError("Password must contain at least one uppercase letter")
        
        if settings.PASSWORD_REQUIRE_LOWERCASE and not any(c.islower() for c in password):
            raise PasswordPolicyError("Password must contain at least one lowercase letter")
        
        if settings.PASSWORD_REQUIRE_NUMBERS and not any(c.isdigit() for c in password):
            raise PasswordPolicyError("Password must contain at least one number")
        
        if settings.PASSWORD_REQUIRE_SPECIAL and not any(not c.isalnum() for c in password):
            raise PasswordPolicyError("Password must contain at least one special character")
    
    async def register(
        self,
        email: str,
        password: str,
        display_name: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> tuple[User, str]:
        """Register a new user. Returns (user, verification_token)."""
        # Check if email already exists
        existing_user = await self.user_repo.get_by_email(email.lower())
        if existing_user:
            await self._log_security_event(
                SecurityEventType.REGISTRATION,
                ip_address=ip_address,
                user_agent=user_agent,
                metadata={"email": email, "success": False, "reason": "email_exists"},
                request_id=request_id,
            )
            raise EmailAlreadyExistsError()
        
        # Validate password
        self._validate_password(password)
        
        # Hash password
        password_hash = hash_password(password)
        
        # Create user
        user = await self.user_repo.create(
            email=email.lower(),
            display_name=display_name,
            password_hash=password_hash,
            status=UserStatus.PENDING_VERIFICATION,
            email_verified=False,
        )
        
        # Create email verification token
        verification_token, token_hash, expires_at = create_token_pair()
        ev_token = EmailVerificationToken(
            user_id=user.id,
            token_hash=token_hash,
            email=email.lower(),
            expires_at=expires_at,
        )
        self.db.add(ev_token)
        
        await self.db.flush()
        
        # Send verification email
        verification_url = f"{self.settings.FRONTEND_VERIFY_EMAIL_URL}?token={verification_token}"
        await self.email_service.send_verification_email(
            to=email,
            verification_url=verification_url,
            display_name=display_name,
        )
        
        await self._log_security_event(
            SecurityEventType.REGISTRATION,
            user_id=user.id,
            ip_address=ip_address,
            user_agent=user_agent,
            metadata={"email": email, "success": True},
            request_id=request_id,
        )
        
        await self._log_security_event(
            SecurityEventType.EMAIL_VERIFICATION_SENT,
            user_id=user.id,
            ip_address=ip_address,
            user_agent=user_agent,
            metadata={"email": email},
            request_id=request_id,
        )
        
        return user, verification_token
    
    async def verify_email(self, token: str, request_id: Optional[str] = None) -> User:
        """Verify email with token."""
        token_hash = hash_token(token)
        
        result = await self.db.execute(
            select(EmailVerificationToken)
            .where(EmailVerificationToken.token_hash == token_hash)
        )
        ev_token = result.scalar_one_or_none()
        
        if not ev_token:
            raise TokenInvalidError()
        
        if ev_token.used_at:
            raise TokenInvalidError()
        
        if datetime.now(timezone.utc) > ev_token.expires_at:
            raise TokenExpiredError()
        
        # Get user
        result = await self.db.execute(
            select(User).where(User.id == ev_token.user_id)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            raise TokenInvalidError()
        
        # Mark token as used
        ev_token.used_at = datetime.now(timezone.utc)
        
        # Update user
        user.email_verified = True
        user.status = UserStatus.ACTIVE
        
        await self.db.flush()
        
        await self._log_security_event(
            SecurityEventType.EMAIL_VERIFICATION_COMPLETED,
            user_id=user.id,
            metadata={"email": user.email},
            request_id=request_id,
        )
        
        return user
    
    async def login(
        self,
        email: str,
        password: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> tuple[User, Session, str]:
        """Login user. Returns (user, session, session_token)."""
        email = email.lower()
        
        # Get user
        result = await self.db.execute(
            select(User).where(User.email == email)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            await self._log_security_event(
                SecurityEventType.LOGIN_FAILED,
                ip_address=ip_address,
                user_agent=user_agent,
                metadata={"email": email, "reason": "user_not_found"},
                request_id=request_id,
            )
            # Use generic error to prevent account enumeration
            raise InvalidCredentialsError()
        
        # Check account status
        if user.status == UserStatus.PENDING_VERIFICATION:
            await self._log_security_event(
                SecurityEventType.LOGIN_FAILED,
                user_id=user.id,
                ip_address=ip_address,
                user_agent=user_agent,
                metadata={"email": email, "reason": "not_verified"},
                request_id=request_id,
            )
            raise AccountNotVerifiedError()
        
        if user.status in (UserStatus.SUSPENDED, UserStatus.INACTIVE):
            await self._log_security_event(
                SecurityEventType.LOGIN_FAILED,
                user_id=user.id,
                ip_address=ip_address,
                user_agent=user_agent,
                metadata={"email": email, "reason": "suspended"},
                request_id=request_id,
            )
            raise AccountSuspendedError()
        
        # Verify password
        if not user.password_hash or not verify_password(password, user.password_hash):
            await self._log_security_event(
                SecurityEventType.LOGIN_FAILED,
                user_id=user.id,
                ip_address=ip_address,
                user_agent=user_agent,
                metadata={"email": email, "reason": "invalid_password"},
                request_id=request_id,
            )
            raise InvalidCredentialsError()
        
        # Rehash password if needed
        if needs_rehash(user.password_hash):
            user.password_hash = hash_password(password)
        
        # Create session
        session_token, token_hash, expires_at = create_token_pair()
        session = Session(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=expires_at,
            user_agent=user_agent,
            ip_address=ip_address,
            last_seen_at=datetime.now(timezone.utc),
        )
        self.db.add(session)
        
        await self.db.flush()
        
        await self._log_security_event(
            SecurityEventType.LOGIN_SUCCESS,
            user_id=user.id,
            ip_address=ip_address,
            user_agent=user_agent,
            metadata={"email": email},
            request_id=request_id,
        )
        
        return user, session, session_token
    
    async def logout(
        self,
        session: Session,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> None:
        """Logout (revoke session)."""
        session.revoked_at = datetime.now(timezone.utc)
        await self.db.flush()
        
        await self._log_security_event(
            SecurityEventType.LOGOUT,
            user_id=session.user_id,
            ip_address=ip_address,
            user_agent=user_agent,
            metadata={"session_id": str(session.id)},
            request_id=request_id,
        )
    
    async def logout_all(
        self,
        user_id: uuid.UUID,
        except_session_id: Optional[uuid.UUID] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> int:
        """Revoke all sessions for a user except optionally one."""
        query = update(Session).where(
            Session.user_id == user_id,
            Session.revoked_at.is_(None),
        )
        
        if except_session_id:
            query = query.where(Session.id != except_session_id)
        
        query = query.values(revoked_at=datetime.now(timezone.utc))
        result = await self.db.execute(query)
        
        await self._log_security_event(
            SecurityEventType.LOGOUT_ALL,
            user_id=user_id,
            ip_address=ip_address,
            user_agent=user_agent,
            metadata={"revoked_count": result.rowcount, "except_session_id": str(except_session_id) if except_session_id else None},
            request_id=request_id,
        )
        
        return result.rowcount
    
    async def request_password_reset(
        self,
        email: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> None:
        """Request password reset. Always succeeds to prevent enumeration."""
        email = email.lower()
        
        result = await self.db.execute(
            select(User).where(User.email == email)
        )
        user = result.scalar_one_or_none()
        
        if user and user.status not in (UserStatus.SUSPENDED, UserStatus.INACTIVE):
            # Create reset token
            reset_token, token_hash, expires_at = create_token_pair()
            pr_token = PasswordResetToken(
                user_id=user.id,
                token_hash=token_hash,
                expires_at=expires_at,
            )
            self.db.add(pr_token)
            
            await self.db.flush()
            
            # Send reset email
            reset_url = f"{self.settings.FRONTEND_RESET_PASSWORD_URL}?token={reset_token}"
            await self.email_service.send_password_reset_email(
                to=email,
                reset_url=reset_url,
                display_name=user.display_name,
            )
            
            await self._log_security_event(
                SecurityEventType.PASSWORD_RESET_REQUESTED,
                user_id=user.id,
                ip_address=ip_address,
                user_agent=user_agent,
                metadata={"email": email},
                request_id=request_id,
            )
            
            await self._log_security_event(
                SecurityEventType.PASSWORD_RESET_EMAIL_SENT,
                user_id=user.id,
                ip_address=ip_address,
                user_agent=user_agent,
                metadata={"email": email},
                request_id=request_id,
            )
        else:
            # Log but don't reveal if email exists
            await self._log_security_event(
                SecurityEventType.PASSWORD_RESET_REQUESTED,
                ip_address=ip_address,
                user_agent=user_agent,
                metadata={"email": email, "user_found": user is not None},
                request_id=request_id,
            )
    
    async def reset_password(
        self,
        token: str,
        new_password: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> User:
        """Reset password with token."""
        token_hash = hash_token(token)
        
        result = await self.db.execute(
            select(PasswordResetToken)
            .where(PasswordResetToken.token_hash == token_hash)
        )
        pr_token = result.scalar_one_or_none()
        
        if not pr_token:
            raise TokenInvalidError()
        
        if pr_token.used_at:
            raise TokenInvalidError()
        
        if datetime.now(timezone.utc) > pr_token.expires_at:
            raise TokenExpiredError()
        
        # Get user
        result = await self.db.execute(
            select(User).where(User.id == pr_token.user_id)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            raise TokenInvalidError()
        
        # Validate new password
        self._validate_password(new_password)
        
        # Hash new password
        password_hash = hash_password(new_password)
        
        # Update user
        user.password_hash = password_hash
        
        # Mark token as used
        pr_token.used_at = datetime.now(timezone.utc)
        
        # Revoke all sessions
        await self.logout_all(user.id, ip_address=ip_address, user_agent=user_agent, request_id=request_id)
        
        await self.db.flush()
        
        # Send notification
        await self.email_service.send_password_changed_notification(
            to=user.email,
            display_name=user.display_name,
        )
        
        await self._log_security_event(
            SecurityEventType.PASSWORD_RESET_COMPLETED,
            user_id=user.id,
            ip_address=ip_address,
            user_agent=user_agent,
            metadata={"email": user.email},
            request_id=request_id,
        )
        
        return user
    
    async def change_password(
        self,
        user_id: uuid.UUID,
        current_password: str,
        new_password: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> User:
        """Change password for authenticated user."""
        # Get user
        result = await self.db.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            raise AuthenticationError("User not found", "USER_NOT_FOUND")
        
        # Verify current password
        if not user.password_hash or not verify_password(current_password, user.password_hash):
            raise InvalidCredentialsError()
        
        # Validate new password
        self._validate_password(new_password)
        
        # Hash new password
        password_hash = hash_password(new_password)
        
        # Update user
        user.password_hash = password_hash
        
        # Revoke all other sessions
        await self.logout_all(user.id, ip_address=ip_address, user_agent=user_agent, request_id=request_id)
        
        await self.db.flush()
        
        # Send notification
        await self.email_service.send_password_changed_notification(
            to=user.email,
            display_name=user.display_name,
        )
        
        await self._log_security_event(
            SecurityEventType.PASSWORD_CHANGED,
            user_id=user.id,
            ip_address=ip_address,
            user_agent=user_agent,
            metadata={"email": user.email},
            request_id=request_id,
        )
        
        return user
    
    async def get_session(self, session_token: str) -> Optional[Session]:
        """Get session by token."""
        token_hash = hash_token(session_token)
        
        result = await self.db.execute(
            select(Session)
            .where(Session.token_hash == token_hash)
        )
        session = result.scalar_one_or_none()
        
        if not session:
            return None
        
        if session.revoked_at:
            return None
        
        if datetime.now(timezone.utc) > session.expires_at:
            return None
        
        # Update last_seen_at
        session.last_seen_at = datetime.now(timezone.utc)
        await self.db.flush()
        
        return session
    
    async def get_user_sessions(self, user_id: uuid.UUID) -> List[Session]:
        """Get all active sessions for a user."""
        result = await self.db.execute(
            select(Session)
            .where(
                Session.user_id == user_id,
                Session.revoked_at.is_(None),
                Session.expires_at > datetime.now(timezone.utc)
            )
            .order_by(Session.last_seen_at.desc())
        )
        return list(result.scalars().all())
    
    async def revoke_session(
        self,
        session_id: uuid.UUID,
        user_id: uuid.UUID,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> bool:
        """Revoke a specific session."""
        result = await self.db.execute(
            select(Session).where(
                Session.id == session_id,
                Session.user_id == user_id,
            )
        )
        session = result.scalar_one_or_none()
        
        if not session or session.revoked_at:
            return False
        
        session.revoked_at = datetime.now(timezone.utc)
        await self.db.flush()
        
        await self._log_security_event(
            SecurityEventType.SESSION_REVOKED,
            user_id=user_id,
            ip_address=ip_address,
            user_agent=user_agent,
            metadata={"session_id": str(session_id)},
            request_id=request_id,
        )
        
        return True
    
    async def is_platform_owner(self, user_id: uuid.UUID) -> bool:
        """Check if user is platform owner."""
        result = await self.db.execute(
            select(PlatformOwner)
            .where(
                PlatformOwner.user_id == user_id,
                PlatformOwner.status == PlatformOwnerStatus.ACTIVE
            )
        )
        return result.scalar_one_or_none() is not None


class MasterAccountService:
    """Service for master account operations."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.auth_service = AuthenticationService(db)
    
    async def initialize_master_account(
        self,
        email: str,
        password: str,
        display_name: Optional[str] = None,
    ) -> tuple[User, PlatformOwner]:
        """Initialize the master account. Only works if no master account exists."""
        # Check if master account already exists
        result = await self.db.execute(
            select(PlatformOwner)
            .join(User, PlatformOwner.user_id == User.id)
            .where(PlatformOwner.status == PlatformOwnerStatus.ACTIVE)
        )
        existing = result.scalar_one_or_none()
        
        if existing:
            raise AuthenticationError("Master account already initialized", "MASTER_EXISTS")
        
        # Validate password
        self.auth_service._validate_password(password)
        
        # Create user
        password_hash = hash_password(password)
        user = await self.auth_service.user_repo.create(
            email=email.lower(),
            display_name=display_name or "Platform Owner",
            password_hash=password_hash,
            status=UserStatus.ACTIVE,
            email_verified=True,
            is_superadmin=True,
        )
        
        # Create platform owner record
        platform_owner = PlatformOwner(
            user_id=user.id,
            status=PlatformOwnerStatus.ACTIVE,
            mfa_enabled=False,
        )
        self.db.add(platform_owner)
        
        await self.db.flush()
        
        await self.auth_service._log_security_event(
            SecurityEventType.MASTER_LOGIN,
            user_id=user.id,
            metadata={"email": email, "action": "initialize"},
        )
        
        return user, platform_owner
    
    async def master_login(
        self,
        email: str,
        password: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> tuple[User, Session, str]:
        """Master account login with stricter checks."""
        user, session, session_token = await self.auth_service.login(
            email=email,
            password=password,
            ip_address=ip_address,
            user_agent=user_agent,
            request_id=request_id,
        )
        
        # Verify user is platform owner
        is_owner = await self.auth_service.is_platform_owner(user.id)
        if not is_owner:
            # Revoke the session we just created
            session.revoked_at = datetime.now(timezone.utc)
            await self.db.flush()
            raise AuthenticationError("Not authorized for master access", "NOT_MASTER")
        
        # Update platform owner last login
        result = await self.db.execute(
            select(PlatformOwner).where(PlatformOwner.user_id == user.id)
        )
        platform_owner = result.scalar_one_or_none()
        if platform_owner:
            platform_owner.last_login_at = datetime.now(timezone.utc)
        
        await self._log_master_event(
            SecurityEventType.MASTER_SESSION_CREATED,
            user_id=user.id,
            ip_address=ip_address,
            user_agent=user_agent,
            metadata={"session_id": str(session.id)},
            request_id=request_id,
        )
        
        return user, session, session_token
    
    async def _log_master_event(
        self,
        event_type: SecurityEventType,
        user_id: uuid.UUID,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        metadata: Optional[dict] = None,
        request_id: Optional[str] = None,
    ) -> None:
        """Log a master account security event."""
        event = SecurityEvent(
            user_id=user_id,
            event_type=event_type,
            ip_address=ip_address,
            user_agent=user_agent,
            metadata=metadata or {},
            request_id=request_id,
        )
        self.db.add(event)
        await self.db.flush()