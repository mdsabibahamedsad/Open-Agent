import uuid
from typing import Optional, List, TYPE_CHECKING
from sqlalchemy import String, Text, ForeignKey, Index, UniqueConstraint, Enum as SQLEnum, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
import enum

from openagent.db.models.base import Base, TimestampMixin, SoftDeleteMixin, UUIDMixin

if TYPE_CHECKING:
    from openagent.db.models.organization import Organization
    from openagent.db.models.membership import Membership
    from openagent.db.models.team import Team


class RoleType(str, enum.Enum):
    SYSTEM = "system"
    CUSTOM = "custom"


class Role(TimestampMixin, SoftDeleteMixin, UUIDMixin, Base):
    __tablename__ = "roles"

    organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    role_type: Mapped[RoleType] = mapped_column(
        SQLEnum(RoleType, name="role_type", create_constraint=True),
        default=RoleType.CUSTOM, nullable=False
    )
    is_system: Mapped[bool] = mapped_column(default=False, nullable=False)
    priority: Mapped[int] = mapped_column(default=0, nullable=False)
    metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    organization: Mapped[Optional["Organization"]] = relationship(back_populates="roles")
    role_permissions: Mapped[List["RolePermission"]] = relationship(
        back_populates="role", cascade="all, delete-orphan"
    )
    memberships: Mapped[List["Membership"]] = relationship(back_populates="role")
    teams: Mapped[List["Team"]] = relationship(back_populates="default_role")

    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_role_org_name"),
        Index("ix_roles_organization_id", "organization_id"),
        Index("ix_roles_role_type", "role_type"),
        Index("ix_roles_is_system", "is_system"),
        Index("ix_roles_deleted_at", "deleted_at"),
    )


SYSTEM_ROLES = [
    {
        "name": "organization_owner",
        "display_name": "Organization Owner",
        "description": "Full control over the organization including ownership transfer",
        "role_type": "system",
        "is_system": True,
        "priority": 100,
        "permissions": [
            "organization:read", "organization:update", "organization:delete",
            "member:read", "member:invite", "member:update", "member:remove",
            "role:read", "role:create", "role:update", "role:delete",
            "team:read", "team:create", "team:update", "team:delete", "team:manage_members",
            "agent:read", "agent:create", "agent:update", "agent:delete", "agent:run",
            "workflow:read", "workflow:create", "workflow:update", "workflow:delete", "workflow:execute",
            "execution:read", "execution:cancel", "execution:retry",
            "tool:read", "tool:create", "tool:update", "tool:delete", "tool:use",
            "integration:read", "integration:create", "integration:update", "integration:delete",
            "credential:read", "credential:create", "credential:update", "credential:delete",
            "api_key:read", "api_key:create", "api_key:revoke",
            "audit_log:read",
            "invitation:read", "invitation:create", "invitation:revoke",
            "service_account:read", "service_account:create", "service_account:update", "service_account:delete",
            "memory:read", "memory:create", "memory:update", "memory:delete",
            "conversation:read", "conversation:create", "conversation:update", "conversation:delete",
            "approval:read", "approval:approve",
            "evaluation:read", "evaluation:create",
            "webhook:read", "webhook:create", "webhook:update", "webhook:delete",
            "mcp_server:read", "mcp_server:create", "mcp_server:update", "mcp_server:delete",
            "package:read", "package:create", "package:update", "package:delete", "package:execute", "package:manage",
            "skill:read", "skill:create", "skill:update", "skill:delete",
            "preset:read", "preset:create", "preset:update", "preset:delete",
            "marketplace:read", "marketplace:create", "marketplace:update", "marketplace:delete", "marketplace:manage",
            "publisher:read", "publisher:create", "publisher:update", "publisher:delete", "publisher:manage",
            "review:read", "review:create", "review:update", "review:delete", "review:manage",
        ]
    },
    {
        "name": "organization_admin",
        "display_name": "Organization Admin",
        "description": "Administrative access to manage organization resources and members",
        "role_type": "system",
        "is_system": True,
        "priority": 80,
        "permissions": [
            "organization:read", "organization:update",
            "member:read", "member:invite", "member:update", "member:remove",
            "role:read",
            "team:read", "team:create", "team:update", "team:delete", "team:manage_members",
            "agent:read", "agent:create", "agent:update", "agent:delete", "agent:run",
            "workflow:read", "workflow:create", "workflow:update", "workflow:delete", "workflow:execute",
            "execution:read", "execution:cancel", "execution:retry",
            "tool:read", "tool:create", "tool:update", "tool:delete", "tool:use",
            "integration:read", "integration:create", "integration:update", "integration:delete",
            "credential:read", "credential:create", "credential:update", "credential:delete",
            "api_key:read", "api_key:create", "api_key:revoke",
            "audit_log:read",
            "invitation:read", "invitation:create", "invitation:revoke",
            "service_account:read", "service_account:create", "service_account:update", "service_account:delete",
            "memory:read", "memory:create", "memory:update", "memory:delete",
            "conversation:read", "conversation:create", "conversation:update", "conversation:delete",
            "approval:read", "approval:approve",
            "evaluation:read", "evaluation:create",
            "webhook:read", "webhook:create", "webhook:update", "webhook:delete",
            "mcp_server:read", "mcp_server:create", "mcp_server:update", "mcp_server:delete",
            "package:read", "package:create", "package:update", "package:delete", "package:execute", "package:manage",
            "skill:read", "skill:create", "skill:update", "skill:delete",
            "preset:read", "preset:create", "preset:update", "preset:delete",
            "marketplace:read", "marketplace:create", "marketplace:update", "marketplace:delete", "marketplace:manage",
            "publisher:read", "publisher:create", "publisher:update", "publisher:delete", "publisher:manage",
            "review:read", "review:create", "review:update", "review:delete", "review:manage",
        ]
    },
    {
        "name": "developer",
        "display_name": "Developer",
        "description": "Can create and manage agents, workflows, and development resources",
        "role_type": "system",
        "is_system": True,
        "priority": 60,
        "permissions": [
            "organization:read",
            "member:read",
            "role:read",
            "team:read",
            "agent:read", "agent:create", "agent:update", "agent:run",
            "workflow:read", "workflow:create", "workflow:update", "workflow:execute",
            "execution:read", "execution:retry",
            "tool:read", "tool:create", "tool:update", "tool:use",
            "integration:read", "integration:create", "integration:update",
            "credential:read",
            "api_key:read", "api_key:create",
            "memory:read", "memory:create", "memory:update",
            "conversation:read", "conversation:create", "conversation:update",
            "approval:read",
            "evaluation:read", "evaluation:create",
            "webhook:read", "webhook:create", "webhook:update",
            "mcp_server:read", "mcp_server:create", "mcp_server:update",
            "package:read", "package:create", "package:update", "package:execute",
            "skill:read", "skill:create", "skill:update",
            "preset:read", "preset:create", "preset:update",
            "marketplace:read", "marketplace:create", "marketplace:update",
            "publisher:read", "publisher:create", "publisher:update",
            "review:read", "review:create", "review:update",
        ]
    },
    {
        "name": "operator",
        "display_name": "Operator",
        "description": "Can run and monitor workflows and agents in production",
        "role_type": "system",
        "is_system": True,
        "priority": 50,
        "permissions": [
            "organization:read",
            "member:read",
            "role:read",
            "team:read",
            "agent:read", "agent:run",
            "workflow:read", "workflow:execute",
            "execution:read", "execution:cancel", "execution:retry",
            "tool:read", "tool:use",
            "integration:read",
            "credential:read",
            "api_key:read",
            "memory:read",
            "conversation:read",
            "approval:read", "approval:approve",
            "evaluation:read",
            "webhook:read",
            "mcp_server:read",
            "package:read", "package:execute",
            "skill:read",
            "preset:read",
            "marketplace:read",
            "publisher:read",
            "review:read",
        ]
    },
    {
        "name": "member",
        "display_name": "Member",
        "description": "Basic access to view and use permitted resources",
        "role_type": "system",
        "is_system": True,
        "priority": 10,
        "permissions": [
            "organization:read",
            "member:read",
            "role:read",
            "team:read",
            "agent:read", "agent:run",
            "workflow:read", "workflow:execute",
            "execution:read",
            "tool:read", "tool:use",
            "integration:read",
            "memory:read",
            "conversation:read", "conversation:create",
            "approval:read",
            "package:read", "package:execute",
            "skill:read",
            "preset:read",
            "marketplace:read",
            "publisher:read",
            "review:read", "review:create",
        ]
    },
    {
        "name": "viewer",
        "display_name": "Viewer",
        "description": "Read-only access to permitted resources",
        "role_type": "system",
        "is_system": True,
        "priority": 5,
        "permissions": [
            "organization:read",
            "member:read",
            "role:read",
            "team:read",
            "agent:read",
            "workflow:read",
            "execution:read",
            "tool:read",
            "integration:read",
            "memory:read",
            "conversation:read",
            "package:read",
            "skill:read",
            "preset:read",
            "marketplace:read",
            "publisher:read",
            "review:read",
        ]
    },
]

def get_default_roles() -> list[dict]:
    return [
        {
            "name": role["name"],
            "display_name": role["display_name"],
            "description": role["description"],
            "role_type": role["role_type"],
            "is_system": role["is_system"],
            "priority": role["priority"],
            "permissions": role["permissions"],
        }
        for role in SYSTEM_ROLES
    ]