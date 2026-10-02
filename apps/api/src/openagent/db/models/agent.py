import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any, TYPE_CHECKING
from sqlalchemy import String, Text, JSON, ForeignKey, Index, UniqueConstraint, Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
import enum

from openagent.db.models.base import Base, TimestampMixin, SoftDeleteMixin, UUIDMixin

if TYPE_CHECKING:
    from openagent.db.models.organization import Organization
    from openagent.db.models.agent_version import AgentVersion
    from openagent.db.models.agent_run import AgentRun
    from openagent.db.models.conversation import Conversation
    from openagent.db.models.memory import Memory


class AgentType(str, enum.Enum):
    CHAT = "chat"
    WORKFLOW = "workflow"
    AUTONOMOUS = "autonomous"
    ASSISTANT = "assistant"


class AgentStatus(str, enum.Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"
    DEPRECATED = "deprecated"


class Agent(TimestampMixin, SoftDeleteMixin, UUIDMixin, Base):
    __tablename__ = "agents"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[AgentStatus] = mapped_column(
        SQLEnum(AgentStatus, name="agent_status", create_constraint=True),
        default=AgentStatus.DRAFT,
        nullable=False
    )
    agent_type: Mapped[AgentType] = mapped_column(
        SQLEnum(AgentType, name="agent_type", create_constraint=True),
        default=AgentType.CHAT,
        nullable=False
    )
    metadata: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    organization: Mapped["Organization"] = relationship(back_populates="agents")
    versions: Mapped[List["AgentVersion"]] = relationship(
        back_populates="agent", cascade="all, delete-orphan"
    )
    runs: Mapped[List["AgentRun"]] = relationship(
        back_populates="agent", cascade="all, delete-orphan"
    )
    conversations: Mapped[List["Conversation"]] = relationship(
        back_populates="agent", cascade="all, delete-orphan"
    )
    memories: Mapped[List["Memory"]] = relationship(
        back_populates="agent", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("organization_id", "slug", name="uq_agent_org_slug"),
        Index("ix_agents_organization_id", "organization_id"),
        Index("ix_agents_status", "status"),
        Index("ix_agents_deleted_at", "deleted_at"),
    )


class AgentVersion(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "agent_versions"

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    instructions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    configuration: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="draft", nullable=False)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    agent: Mapped["Agent"] = relationship(back_populates="versions")
    runs: Mapped[List["AgentRun"]] = relationship(
        back_populates="agent_version", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("agent_id", "version", name="uq_agent_version"),
        Index("ix_agent_versions_agent_id", "agent_id"),
        Index("ix_agent_versions_status", "status"),
    )