import uuid
from datetime import datetime
from typing import Optional, TYPE_CHECKING
from sqlalchemy import String, ForeignKey, Index, Enum as SQLEnum, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
import enum

from openagent.db.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from openagent.db.models.user import User


class PlatformOwnerStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"


class PlatformOwner(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "platform_owners"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    status: Mapped[PlatformOwnerStatus] = mapped_column(
        SQLEnum(PlatformOwnerStatus, name="platform_owner_status", create_constraint=True),
        default=PlatformOwnerStatus.ACTIVE,
        nullable=False
    )
    last_login_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    mfa_enabled: Mapped[bool] = mapped_column(default=False, nullable=False)
    mfa_secret_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    recovery_codes_hash: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    user: Mapped["User"] = relationship(back_populates="platform_owner")

    __table_args__ = (
        Index("ix_platform_owners_user_id", "user_id"),
        Index("ix_platform_owners_status", "status"),
    )