import uuid
from datetime import datetime
from typing import Optional, List, TYPE_CHECKING
from sqlalchemy import String, Text, JSON, ForeignKey, Index, UniqueConstraint, Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
import enum

from openagent.db.models.base import Base, TimestampMixin, SoftDeleteMixin, UUIDMixin

if TYPE_CHECKING:
    from openagent.db.models.organization import Organization
    from openagent.db.models.user import User
    from openagent.db.models.role import Role
    from openagent.db.models.memory import Memory


class Team(TimestampMixin, SoftDeleteMixin, UUIDMixin, Base):
    __tablename__ = "teams"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    avatar_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    default_role_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id", ondelete="SET NULL"), nullable=True
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=False
    )
    metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    organization: Mapped["Organization"] = relationship(back_populates="teams")
    default_role: Mapped[Optional["Role"]] = relationship(back_populates="teams")
    creator: Mapped["User"] = relationship(foreign_keys=[created_by])
    memberships: Mapped[List["TeamMembership"]] = relationship(
        back_populates="team", cascade="all, delete-orphan"
    )
    memories: Mapped[List["Memory"]] = relationship(
        back_populates="team", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("organization_id", "slug", name="uq_team_org_slug"),
        UniqueConstraint("organization_id", "name", name="uq_team_org_name"),
        Index("ix_teams_organization_id", "organization_id"),
        Index("ix_teams_slug", "slug"),
        Index("ix_teams_deleted_at", "deleted_at"),
    )


class TeamMembershipRole(str, enum.Enum):
    LEAD = "lead"
    MEMBER = "member"


class TeamMembership(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "team_memberships"

    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[TeamMembershipRole] = mapped_column(
        SQLEnum(TeamMembershipRole, name="team_membership_role", create_constraint=True),
        default=TeamMembershipRole.MEMBER, nullable=False
    )

    team: Mapped["Team"] = relationship(back_populates="memberships")
    user: Mapped["User"] = relationship()

    __table_args__ = (
        UniqueConstraint("team_id", "user_id", name="uq_team_membership_user_team"),
        Index("ix_team_memberships_team_id", "team_id"),
        Index("ix_team_memberships_user_id", "user_id"),
    )