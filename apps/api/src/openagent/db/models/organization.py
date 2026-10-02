import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any, TYPE_CHECKING
from sqlalchemy import String, Text, JSON, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
import enum

from openagent.db.models.base import Base, TimestampMixin, SoftDeleteMixin, UUIDMixin

if TYPE_CHECKING:
    from openagent.db.models.membership import Membership
    from openagent.db.models.api_key import ApiKey
    from openagent.db.models.agent import Agent
    from openagent.db.models.workflow import Workflow
    from openagent.db.models.credential import Credential
    from openagent.db.models.integration import Integration
    from openagent.db.models.mcp import MCPServer
    from openagent.db.models.tool import Tool
    from openagent.db.models.memory import Memory
    from openagent.db.models.conversation import Conversation
    from openagent.db.models.approval import Approval
    from openagent.db.models.evaluation import Evaluation
    from openagent.db.models.audit_log import AuditLog
    from openagent.db.models.webhook import Webhook
    from openagent.db.models.role import Role
    from openagent.db.models.team import Team
    from openagent.db.models.organization_invitation import OrganizationInvitation
    from openagent.db.models.service_account import ServiceAccount


class OrganizationStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    DELETED = "deleted"


class Organization(TimestampMixin, SoftDeleteMixin, UUIDMixin, Base):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    avatar_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    status: Mapped[OrganizationStatus] = mapped_column(
        default=OrganizationStatus.ACTIVE, nullable=False
    )
    settings: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    memberships: Mapped[List["Membership"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    api_keys: Mapped[List["ApiKey"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    agents: Mapped[List["Agent"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    workflows: Mapped[List["Workflow"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    credentials: Mapped[List["Credential"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    integrations: Mapped[List["Integration"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    mcp_servers: Mapped[List["MCPServer"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    tools: Mapped[List["Tool"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    memories: Mapped[List["Memory"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    conversations: Mapped[List["Conversation"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    approvals: Mapped[List["Approval"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    evaluations: Mapped[List["Evaluation"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    audit_logs: Mapped[List["AuditLog"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    webhooks: Mapped[List["Webhook"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    roles: Mapped[List["Role"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    teams: Mapped[List["Team"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    invitations: Mapped[List["OrganizationInvitation"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    service_accounts: Mapped[List["ServiceAccount"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    memory_policy: Mapped[Optional["MemoryPolicy"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan", uselist=False
    )

    __table_args__ = (
        Index("ix_organizations_slug", "slug"),
        Index("ix_organizations_status", "status"),
        Index("ix_organizations_deleted_at", "deleted_at"),
    )