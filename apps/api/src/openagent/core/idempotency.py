import hashlib
import secrets
import json
from datetime import datetime, timedelta, timezone
from typing import Optional, Any, Dict
from dataclasses import dataclass
from enum import Enum

from sqlalchemy import String, Text, ForeignKey, Index, Enum as SQLEnum, DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from openagent.db.models.base import Base, TimestampMixin, UUIDMixin
from openagent.core.config import get_settings
from openagent.core.security import hash_token, verify_token, generate_secure_token
from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openagent.db.session import get_db as _get_db_impl

def _get_db() -> AsyncSession:
    """Lazy import to avoid circular dependency with db.session."""
    from openagent.db.session import get_db as _get_db_impl
    return _get_db_impl()


class IdempotencyStatus(str, Enum):
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class IdempotencyKey(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "idempotency_keys"

    organization_id: Mapped[Optional[UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    user_id: Mapped[Optional[UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    key: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    endpoint: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_body: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    status: Mapped[IdempotencyStatus] = mapped_column(
        SQLEnum(IdempotencyStatus, name="idempotency_status", create_constraint=True),
        default=IdempotencyStatus.PROCESSING,
        nullable=False
    )
    response_status_code: Mapped[Optional[int]] = mapped_column(nullable=True)
    response_body: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    response_headers: Mapped[Optional[Dict[str, str]]] = mapped_column(JSON, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_idempotency_keys_key_hash", "key_hash"),
        Index("ix_idempotency_keys_organization_endpoint", "organization_id", "endpoint"),
        Index("ix_idempotency_keys_user_endpoint", "user_id", "endpoint"),
        Index("ix_idempotency_keys_expires_at", "expires_at"),
        Index("ix_idempotency_keys_status", "status"),
    )


class IdempotencyService:
    """Service for handling idempotent requests."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.settings = get_settings()

    def _generate_key(self) -> str:
        """Generate a new idempotency key."""
        return generate_secure_token()

    def _hash_key(self, key: str) -> str:
        """Hash the idempotency key for storage."""
        return hash_token(key)

    def _hash_request(self, method: str, endpoint: str, body: Optional[Dict[str, Any]]) -> str:
        """Create a hash of the request for comparison."""
        content = json.dumps({
            "method": method,
            "endpoint": endpoint,
            "body": body or {}
        }, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(content.encode()).hexdigest()

    async def check_idempotency(
        self,
        key: str,
        method: str,
        endpoint: str,
        body: Optional[Dict[str, Any]] = None,
        organization_id: Optional[UUID] = None,
        user_id: Optional[UUID] = None,
    ) -> tuple[Optional[IdempotencyKey], bool]:
        """
        Check if an idempotency key exists and matches.
        Returns (idempotency_key, is_new).
        If is_new is True, the key was created and caller should process the request.
        If is_new is False, the key exists and caller should return the stored response.
        """
        key_hash = self._hash_key(key)
        request_hash = self._hash_request(method, endpoint, body)

        result = await self.db.execute(
            select(IdempotencyKey).where(IdempotencyKey.key_hash == key_hash)
        )
        existing = result.scalar_one_or_none()

        if existing:
            # Check if expired
            if datetime.now(timezone.utc) > existing.expires_at:
                # Expired, treat as new
                return await self._create_idempotency_key(key, key_hash, method, endpoint, body, request_hash, organization_id, user_id), True

            # Check if request matches
            if existing.request_hash != request_hash:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "error": "Idempotency key already used with different request",
                        "code": "IDEMPOTENCY_CONFLICT",
                        "details": {
                            "existing_endpoint": existing.endpoint,
                            "existing_method": existing.method,
                        }
                    }
                )

            # Return existing response if completed
            if existing.status == IdempotencyStatus.COMPLETED:
                return existing, False
            
            if existing.status == IdempotencyStatus.FAILED:
                # Allow retry for failed requests
                return await self._create_idempotency_key(key, key_hash, method, endpoint, body, request_hash, organization_id, user_id), True

            # Still processing
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "Request with this idempotency key is still processing",
                    "code": "IDEMPOTENCY_PROCESSING",
                }
            )

        # New key
        return await self._create_idempotency_key(key, key_hash, method, endpoint, body, request_hash, organization_id, user_id), True

    async def _create_idempotency_key(
        self,
        key: str,
        key_hash: str,
        method: str,
        endpoint: str,
        body: Optional[Dict[str, Any]],
        request_hash: str,
        organization_id: Optional[UUID],
        user_id: Optional[UUID],
    ) -> IdempotencyKey:
        """Create a new idempotency key record."""
        # 24 hour expiry
        expires_at = datetime.now(timezone.utc) + timedelta(hours=24)

        idempotency_key = IdempotencyKey(
            organization_id=organization_id,
            user_id=user_id,
            key=key,
            key_hash=key_hash,
            endpoint=endpoint,
            method=method,
            request_hash=request_hash,
            request_body=body,
            expires_at=expires_at,
            status=IdempotencyStatus.PROCESSING,
        )
        self.db.add(idempotency_key)
        await self.db.flush()
        return idempotency_key

    async def complete_idempotency(
        self,
        idempotency_key: IdempotencyKey,
        status_code: int,
        response_body: Optional[Dict[str, Any]] = None,
        response_headers: Optional[Dict[str, str]] = None,
    ) -> None:
        """Mark idempotency key as completed with response."""
        idempotency_key.status = IdempotencyStatus.COMPLETED
        idempotency_key.response_status_code = status_code
        idempotency_key.response_body = response_body
        idempotency_key.response_headers = response_headers
        idempotency_key.completed_at = datetime.now(timezone.utc)
        await self.db.flush()

    async def fail_idempotency(
        self,
        idempotency_key: IdempotencyKey,
        error_message: str,
    ) -> None:
        """Mark idempotency key as failed."""
        idempotency_key.status = IdempotencyStatus.FAILED
        idempotency_key.error_message = error_message
        idempotency_key.completed_at = datetime.now(timezone.utc)
        await self.db.flush()

    async def cleanup_expired(self) -> int:
        """Clean up expired idempotency keys."""
        now = datetime.now(timezone.utc)
        result = await self.db.execute(
            update(IdempotencyKey)
            .where(
                IdempotencyKey.expires_at < now,
                IdempotencyKey.status == IdempotencyStatus.PROCESSING
            )
            .values(status=IdempotencyStatus.FAILED, error_message="Expired", completed_at=now)
        )
        return result.rowcount


# Dependency for idempotency - lazy import to avoid circular imports
async def get_idempotency_service(
    db: AsyncSession = Depends(lambda: _get_db()),
) -> IdempotencyService:
    return IdempotencyService(db)


def require_idempotency(
    required: bool = True,
    header_name: str = "Idempotency-Key"
):
    """Dependency factory for requiring idempotency key."""
    async def _check_idempotency(
        request: Request,
        db: AsyncSession = Depends(lambda: _get_db()),
        idempotency_service: IdempotencyService = Depends(get_idempotency_service),
    ) -> Optional[IdempotencyKey]:
        key = request.headers.get(header_name)
        
        if not key:
            if required:
                raise HTTPException(
                    status_code=400,
                    detail={"error": f"Missing required header: {header_name}", "code": "MISSING_IDEMPOTENCY_KEY"}
                )
            return None
        
        # Validate key format (UUID or 32+ char string)
        if len(key) < 16:
            raise HTTPException(
                status_code=400,
                detail={"error": "Invalid idempotency key format", "code": "INVALID_IDEMPOTENCY_KEY"}
            )
        
        body = None
        if request.method in ("POST", "PUT", "PATCH"):
            try:
                body = await request.json()
            except Exception:
                body = None
        
        organization_id = None
        org_header = request.headers.get("X-Organization-ID")
        if org_header:
            try:
                organization_id = UUID(org_header)
            except ValueError:
                pass
        
        user_id = None
        # Could extract from auth context if available
        
        idempotency_key, is_new = await idempotency_service.check_idempotency(
            key=key,
            method=request.method,
            endpoint=request.url.path,
            body=body,
            organization_id=organization_id,
            user_id=user_id,
        )
        
        # Store in request state for later use
        request.state.idempotency_key = idempotency_key
        request.state.idempotency_is_new = is_new
        
        if not is_new:
            # Return stored response
            if idempotency_key.response_body is not None:
                from fastapi.responses import JSONResponse
                return JSONResponse(
                    content=idempotency_key.response_body,
                    status_code=idempotency_key.response_status_code or 200,
                    headers=idempotency_key.response_headers or {}
                )
        
        return idempotency_key
    
    return _check_idempotency


# Import needed for HTTPException
from fastapi import HTTPException
from uuid import UUID