import uuid
from datetime import datetime
from typing import Optional, List, TYPE_CHECKING
from sqlalchemy import String, Text, Enum as SQLEnum, ForeignKey, Index, UniqueConstraint, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
import enum

from openagent.db.models.base import Base, TimestampMixin, SoftDeleteMixin, UUIDMixin

if TYPE_CHECKING:
    from openagent.db.models.membership import Membership
    from openagent.db.models.api_key import ApiKey
    from openagent.db.models.email_verification import EmailVerificationToken
    from openagent.db.models.password_reset import PasswordResetToken
    from openagent.db.models.session import Session
    from openagent.db.models.platform_owner import PlatformOwner
    from openagent.db.models.team import TeamMembership


class UserStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    PENDING_VERIFICATION = "pending_verification"


class User(TimestampMixin, SoftDeleteMixin, UUIDMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    display_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    avatar_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    password_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[UserStatus] = mapped_column(
        SQLEnum(UserStatus, name="user_status", create_constraint=True),
        default=UserStatus.PENDING_VERIFICATION,
        nullable=False
    )
    is_superadmin: Mapped[bool] = mapped_column(default=False, nullable=False)

    memberships: Mapped[List["Membership"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    api_keys: Mapped[List["ApiKey"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    email_verification_tokens: Mapped[List["EmailVerificationToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    password_reset_tokens: Mapped[List["PasswordResetToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    sessions: Mapped[List["Session"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    platform_owner: Mapped[Optional["PlatformOwner"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    team_memberships: Mapped[List["TeamMembership"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    memories: Mapped[List["Memory"]] = relationship(
        back_populates="user", cascade="all, delete-orphan",
        foreign_keys="Memory.user_id",
    )

    __table_args__ = (
        Index("ix_users_email", "email"),
        Index("ix_users_status", "status"),
        Index("ix_users_deleted_at", "deleted_at"),
    )