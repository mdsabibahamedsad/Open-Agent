from typing import Optional, List, TYPE_CHECKING
from sqlalchemy import String, Text, Index, Enum as SQLEnum, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
import enum

from openagent.db.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from openagent.db.models.role import RolePermission
    from openagent.db.models.service_account import ServiceAccount


class PermissionAction(str, enum.Enum):
    CREATE = "create"
    READ = "read"
    UPDATE = "update"
    DELETE = "delete"
    EXECUTE = "execute"
    MANAGE = "manage"
    INVITE = "invite"
    APPROVE = "approve"
    RUN = "run"
    USE = "use"


class PermissionResource(str, enum.Enum):
    ORGANIZATION = "organization"
    MEMBER = "member"
    ROLE = "role"
    TEAM = "team"
    AGENT = "agent"
    WORKFLOW = "workflow"
    EXECUTION = "execution"
    TOOL = "tool"
    INTEGRATION = "integration"
    CONNECTOR = "connector"
    CREDENTIAL = "credential"
    API_KEY = "api_key"
    AUDIT_LOG = "audit_log"
    INVITATION = "invitation"
    SERVICE_ACCOUNT = "service_account"
    MEMORY = "memory"
    CONVERSATION = "conversation"
    APPROVAL = "approval"
    EVALUATION = "evaluation"
    WEBHOOK = "webhook"
    MCP_SERVER = "mcp_server"
    PACKAGE = "package"
    SKILL = "skill"
    PRESET = "preset"
    MARKETPLACE = "marketplace"
    PUBLISHER = "publisher"
    REVIEW = "review"
    BILLING = "billing"
    PAYOUT = "payout"
    REGISTRY = "registry"
    PLATFORM = "platform"


class PermissionScope(str, enum.Enum):
    ORGANIZATION = "organization"
    TEAM = "team"
    OWN = "own"
    PLATFORM = "platform"


class Permission(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "permissions"

    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    resource: Mapped[PermissionResource] = mapped_column(
        SQLEnum(PermissionResource, name="permission_resource", create_constraint=True),
        nullable=False, index=True
    )
    action: Mapped[PermissionAction] = mapped_column(
        SQLEnum(PermissionAction, name="permission_action", create_constraint=True),
        nullable=False, index=True
    )
    scope: Mapped[PermissionScope] = mapped_column(
        SQLEnum(PermissionScope, name="permission_scope", create_constraint=True),
        default=PermissionScope.ORGANIZATION, nullable=False
    )
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_system: Mapped[bool] = mapped_column(default=False, nullable=False)
    danger_level: Mapped[int] = mapped_column(default=1, nullable=False)
    metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    role_permissions: Mapped[List["RolePermission"]] = relationship(
        back_populates="permission", cascade="all, delete-orphan"
    )
    service_account_permissions: Mapped[List["ServiceAccountPermission"]] = relationship(
        back_populates="permission", cascade="all, delete-orphan"
    )
    # Reverse side of ServiceAccount.permissions (pre-existing gap).
    service_accounts: Mapped[List["ServiceAccount"]] = relationship(
        secondary="service_account_permissions", back_populates="permissions"
    )

    __table_args__ = (
        Index("ix_permissions_resource_action", "resource", "action"),
        Index("ix_permissions_scope", "scope"),
        Index("ix_permissions_is_system", "is_system"),
    )

    @property
    def full_name(self) -> str:
        return f"{self.resource.value}:{self.action.value}"


SYSTEM_PERMISSIONS = [
    ("organization", "read", "Read organization details", 1),
    ("organization", "update", "Update organization settings", 2),
    ("organization", "delete", "Delete organization", 5),
    ("member", "read", "View organization members", 1),
    ("member", "invite", "Invite new members", 2),
    ("member", "update", "Update member details", 2),
    ("member", "remove", "Remove members", 3),
    ("role", "read", "View roles and permissions", 1),
    ("role", "create", "Create custom roles", 3),
    ("role", "update", "Update role permissions", 3),
    ("role", "delete", "Delete custom roles", 3),
    ("team", "read", "View teams", 1),
    ("team", "create", "Create teams", 2),
    ("team", "update", "Update team details", 2),
    ("team", "delete", "Delete teams", 3),
    ("team", "manage_members", "Manage team members", 2),
    ("agent", "read", "View agents", 1),
    ("agent", "create", "Create agents", 2),
    ("agent", "update", "Update agents", 2),
    ("agent", "delete", "Delete agents", 3),
    ("agent", "run", "Run agents", 2),
    ("workflow", "read", "View workflows", 1),
    ("workflow", "create", "Create workflows", 2),
    ("workflow", "update", "Update workflows", 2),
    ("workflow", "delete", "Delete workflows", 3),
    ("workflow", "execute", "Execute workflows", 2),
    ("execution", "read", "View executions", 1),
    ("execution", "cancel", "Cancel executions", 2),
    ("execution", "retry", "Retry executions", 2),
    ("tool", "read", "View tools", 1),
    ("tool", "create", "Create tools", 2),
    ("tool", "update", "Update tools", 2),
    ("tool", "delete", "Delete tools", 3),
    ("tool", "use", "Use tools", 2),
    ("integration", "read", "View integrations", 1),
    ("integration", "create", "Create integrations", 2),
    ("integration", "update", "Update integrations", 2),
    ("integration", "delete", "Delete integrations", 3),
    ("connector", "read", "View connectors and connections", 1),
    ("connector", "create", "Create connector connections", 2),
    ("connector", "update", "Update connector connections", 2),
    ("connector", "delete", "Delete connector connections", 3),
    ("connector", "execute", "Execute connector actions", 2),
    ("connector", "admin", "Manage connector definitions and policies", 4),
    ("credential", "read", "View credentials", 2),
    ("credential", "create", "Create credentials", 3),
    ("credential", "update", "Update credentials", 3),
    ("credential", "delete", "Delete credentials", 3),
    ("credential", "rotate", "Rotate credentials", 3),
    ("api_key", "read", "View API keys", 1),
    ("api_key", "create", "Create API keys", 2),
    ("api_key", "revoke", "Revoke API keys", 2),
    ("audit_log", "read", "View audit logs", 2),
    ("invitation", "read", "View invitations", 1),
    ("invitation", "create", "Create invitations", 2),
    ("invitation", "revoke", "Revoke invitations", 2),
    ("service_account", "read", "View service accounts", 1),
    ("service_account", "create", "Create service accounts", 3),
    ("service_account", "update", "Update service accounts", 3),
    ("service_account", "delete", "Delete service accounts", 3),
    ("memory", "read", "View memories", 1),
    ("memory", "create", "Create memories", 2),
    ("memory", "update", "Update memories", 2),
    ("memory", "delete", "Delete memories", 2),
    ("conversation", "read", "View conversations", 1),
    ("conversation", "create", "Create conversations", 2),
    ("conversation", "update", "Update conversations", 2),
    ("conversation", "delete", "Delete conversations", 2),
    ("approval", "read", "View approvals", 1),
    ("approval", "approve", "Approve/reject approvals", 2),
    ("approval", "create", "Request approvals", 1),
    ("approval", "cancel", "Cancel approvals", 2),
    ("approval", "escalate", "Escalate approvals", 2),
    ("approval", "admin", "Manage approval policies", 3),
    ("evaluation", "read", "View evaluations", 1),
    ("evaluation", "create", "Create evaluations", 2),
    ("evaluation", "decide", "Decide evaluations and trigger corrections", 2),
    ("evaluation", "admin", "Manage rubrics, quality gates and benchmarks", 3),
    ("webhook", "read", "View webhooks", 1),
    ("webhook", "create", "Create webhooks", 2),
    ("webhook", "update", "Update webhooks", 2),
    ("webhook", "delete", "Delete webhooks", 3),
    ("mcp_server", "read", "View MCP servers", 1),
    ("mcp_server", "create", "Create MCP servers", 2),
    ("mcp_server", "update", "Update MCP servers", 2),
    ("mcp_server", "delete", "Delete MCP servers", 3),
    ("package", "read", "View reusable packages and catalog", 1),
    ("package", "create", "Create packages and versions", 2),
    ("package", "update", "Update packages and versions", 2),
    ("package", "delete", "Delete packages", 3),
    ("package", "execute", "Install, update and roll back packages", 2),
    ("package", "manage", "Publish, revoke and verify packages", 4),
    ("skill", "read", "View skills", 1),
    ("skill", "create", "Create skills", 2),
    ("skill", "update", "Update skills", 2),
    ("skill", "delete", "Delete skills", 3),
    ("preset", "read", "View presets", 1),
    ("preset", "create", "Create presets", 2),
    ("preset", "update", "Update presets", 2),
    ("preset", "delete", "Delete presets", 3),
    ("marketplace", "read", "View marketplaces and listings", 1),
    ("marketplace", "create", "Create marketplaces and listings", 2),
    ("marketplace", "update", "Update marketplaces and listings", 2),
    ("marketplace", "delete", "Delete marketplaces and listings", 3),
    ("marketplace", "manage", "Moderate listings, policies and featured content", 4),
    ("publisher", "read", "View publisher profiles", 1),
    ("publisher", "create", "Create publisher profiles", 2),
    ("publisher", "update", "Update publisher profiles", 2),
    ("publisher", "delete", "Delete publisher profiles", 3),
    ("publisher", "manage", "Verify, suspend and moderate publishers", 4),
    ("review", "read", "View reviews", 1),
    ("review", "create", "Write reviews", 1),
    ("review", "update", "Update own reviews and respond", 2),
    ("review", "delete", "Delete reviews", 3),
    ("review", "manage", "Moderate reviews and reports", 4),
    ("platform", "read", "View platform (platform owner only)", 3),
    ("platform", "manage_users", "Manage platform users (platform owner only)", 5),
    ("platform", "manage_organizations", "Manage organizations (platform owner only)", 5),
    ("platform", "manage_integrations", "Manage platform integrations (platform owner only)", 4),
    ("platform", "manage_marketplace", "Manage marketplace (platform owner only)", 4),
    ("platform", "manage_system", "Manage system settings (platform owner only)", 5),
    ("platform", "view_audit_logs", "View platform audit logs (platform owner only)", 3),
    ("platform", "manage_billing", "Manage billing (platform owner only)", 4),
]

def get_default_permissions() -> list[dict]:
    return [
        {
            "name": f"{resource}:{action}",
            "resource": resource,
            "action": action,
            "description": desc,
            "scope": "organization" if resource != "platform" else "platform",
            "is_system": True,
            "danger_level": danger,
        }
        for resource, action, desc, danger in SYSTEM_PERMISSIONS
    ]