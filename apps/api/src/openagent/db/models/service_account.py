import uuid
from datetime import datetime
from typing import Optional, List, TYPE_CHECKING
from sqlalchemy import String, Text, ForeignKey, Index, Enum as SQLEnum, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
import enum

from openagent.db.models.base import Base, TimestampMixin, SoftDeleteMixin, UUIDMixin

if TYPE_CHECKING:
    from openagent.db.models.organization import Organization
    from openagent.db.models.user import User
    from openagent.db.models.permission import Permission


class ServiceAccountStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    REVOKED = "revoked"
    EXPIRED = "expired"


class ServiceAccount(TimestampMixin, SoftDeleteMixin, UUIDMixin, Base):
    __tablename__ = "service_accounts"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[ServiceAccountStatus] = mapped_column(
        SQLEnum(ServiceAccountStatus, name="service_account_status", create_constraint=True),
        default=ServiceAccountStatus.ACTIVE, nullable=False
    )
    key_hash: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    key_prefix: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    permissions: Mapped[List["Permission"]] = relationship(
        secondary="service_account_permissions", back_populates="service_accounts"
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(nullable=True, index=True)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    organization: Mapped["Organization"] = relationship(back_populates="service_accounts")
    creator: Mapped[Optional["User"]] = relationship()
    account_permissions: Mapped[List["ServiceAccountPermission"]] = relationship(
        back_populates="service_account", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_service_accounts_organization_id", "organization_id"),
        Index("ix_service_accounts_key_hash", "key_hash"),
        Index("ix_service_accounts_key_prefix", "key_prefix"),
        Index("ix_service_accounts_status", "status"),
        Index("ix_service_accounts_expires_at", "expires_at"),
        Index("ix_service_accounts_deleted_at", "deleted_at"),
    )