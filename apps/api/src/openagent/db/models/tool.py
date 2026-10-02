import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any, TYPE_CHECKING
from sqlalchemy import String, Text, JSON, ForeignKey, Index, Enum as SQLEnum, UniqueConstraint, Boolean, Integer, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
import enum

from openagent.db.models.base import Base, TimestampMixin, SoftDeleteMixin, UUIDMixin

if TYPE_CHECKING:
    from openagent.db.models.organization import Organization
    from openagent.db.models.credential import Credential


class ToolType(str, enum.Enum):
    BUILTIN = "builtin"
    CUSTOM = "custom"
    MCP = "mcp"
    API = "api"
    COMMUNITY = "community"


class ToolCategory(str, enum.Enum):
    COMMUNICATION = "communication"
    WEB = "web"
    BROWSER = "browser"
    HTTP = "http"
    DATABASE = "database"
    FILESYSTEM = "filesystem"
    CODE = "code"
    SHELL = "shell"
    SEARCH = "search"
    DOCUMENTS = "documents"
    MEDIA = "media"
    CALENDAR = "calendar"
    EMAIL = "email"
    MESSAGING = "messaging"
    CRM = "crm"
    ANALYTICS = "analytics"
    FINANCE = "finance"
    DEVELOPER = "developer"
    SYSTEM = "system"
    AI = "ai"
    UTILITY = "utility"
    CUSTOM = "custom"


class ToolCapability(str, enum.Enum):
    READ = "read"
    WRITE = "write"
    DELETE = "delete"
    NETWORK = "network"
    FILESYSTEM = "filesystem"
    PROCESS_EXECUTION = "process_execution"
    BROWSER_CONTROL = "browser_control"
    DATABASE_ACCESS = "database_access"
    CREDENTIAL_ACCESS = "credential_access"
    EXTERNAL_API = "external_api"
    MESSAGE_SEND = "message_send"
    EMAIL_SEND = "email_send"
    CODE_EXECUTION = "code_execution"
    SYSTEM_CONTROL = "system_control"
    FINANCIAL_ACTION = "financial_action"


class ToolRiskLevel(str, enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ToolExecutionMode(str, enum.Enum):
    SYNC = "SYNC"
    ASYNC = "ASYNC"
    STREAMING = "STREAMING"
    BACKGROUND = "BACKGROUND"
    WAITING = "WAITING"


class ToolLifecycleStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"
    DEPRECATED = "DEPRECATED"
    REVOKED = "REVOKED"


class ToolTrustLevel(str, enum.Enum):
    CORE = "CORE"
    VERIFIED = "VERIFIED"
    ORGANIZATION = "ORGANIZATION"
    COMMUNITY = "COMMUNITY"
    UNTRUSTED = "UNTRUSTED"


class ToolProviderType(str, enum.Enum):
    BUILTIN = "BUILTIN"
    HTTP_API = "HTTP_API"
    PYTHON_PACKAGE = "PYTHON_PACKAGE"
    JAVASCRIPT_PACKAGE = "JAVASCRIPT_PACKAGE"
    EXTERNAL_SERVICE = "EXTERNAL_SERVICE"
    MCP = "MCP"
    MARKETPLACE = "MARKETPLACE"
    BROWSER = "BROWSER"
    CODING_RUNTIME = "CODING_RUNTIME"
    CUSTOM = "CUSTOM"


class Tool(TimestampMixin, SoftDeleteMixin, UUIDMixin, Base):
    __tablename__ = "tools"

    organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tool_type: Mapped[ToolType] = mapped_column(
        SQLEnum(ToolType, name="tool_type", create_constraint=True),
        default=ToolType.CUSTOM,
        nullable=False
    )
    category: Mapped[ToolCategory] = mapped_column(
        SQLEnum(ToolCategory, name="tool_category", create_constraint=True),
        default=ToolCategory.CUSTOM,
        nullable=False
    )
    status: Mapped[ToolLifecycleStatus] = mapped_column(
        SQLEnum(ToolLifecycleStatus, name="tool_lifecycle_status", create_constraint=True),
        default=ToolLifecycleStatus.DRAFT,
        nullable=False
    )
    display_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    icon: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    documentation_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    provider: Mapped[str] = mapped_column(String(100), default="builtin", nullable=False)
    provider_type: Mapped[ToolProviderType] = mapped_column(
        SQLEnum(ToolProviderType, name="tool_provider_type", create_constraint=True),
        default=ToolProviderType.BUILTIN,
        nullable=False
    )
    version: Mapped[str] = mapped_column(String(50), default="1.0.0", nullable=False)
    capabilities: Mapped[List[ToolCapability]] = mapped_column(
        JSON, default=list, nullable=False
    )
    risk_level: Mapped[ToolRiskLevel] = mapped_column(
        SQLEnum(ToolRiskLevel, name="tool_risk_level", create_constraint=True),
        default=ToolRiskLevel.LOW,
        nullable=False
    )
    execution_mode: Mapped[ToolExecutionMode] = mapped_column(
        SQLEnum(ToolExecutionMode, name="tool_execution_mode", create_constraint=True),
        default=ToolExecutionMode.SYNC,
        nullable=False
    )
    timeout: Mapped[int] = mapped_column(Integer, default=30000, nullable=False)
    retry_policy: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    supports_streaming: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    supports_cancellation: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    supports_idempotency: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    trust_level: Mapped[ToolTrustLevel] = mapped_column(
        SQLEnum(ToolTrustLevel, name="tool_trust_level", create_constraint=True),
        default=ToolTrustLevel.ORGANIZATION,
        nullable=False
    )
    input_schema: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    output_schema: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    configuration: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    metadata: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    tags: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)

    organization: Mapped[Optional["Organization"]] = relationship(back_populates="tools")
    versions: Mapped[List["ToolVersion"]] = relationship(back_populates="tool", cascade="all, delete-orphan")
    executions: Mapped[List["ToolExecution"]] = relationship(back_populates="tool", cascade="all, delete-orphan")
    policies: Mapped[List["ToolPolicy"]] = relationship(back_populates="tool", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("organization_id", "slug", "version", name="uq_tool_org_slug_version"),
        Index("ix_tools_organization_id", "organization_id"),
        Index("ix_tools_tool_type", "tool_type"),
        Index("ix_tools_category", "category"),
        Index("ix_tools_status", "status"),
        Index("ix_tools_risk_level", "risk_level"),
        Index("ix_tools_trust_level", "trust_level"),
        Index("ix_tools_provider", "provider"),
        Index("ix_tools_deleted_at", "deleted_at"),
    )


class ToolVersion(TimestampMixin, SoftDeleteMixin, UUIDMixin, Base):
    __tablename__ = "tool_versions"

    tool_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tools.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    display_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    capabilities: Mapped[List[ToolCapability]] = mapped_column(JSON, default=list, nullable=False)
    risk_level: Mapped[ToolRiskLevel] = mapped_column(
        SQLEnum(ToolRiskLevel, name="tool_version_risk_level", create_constraint=True),
        default=ToolRiskLevel.LOW,
        nullable=False
    )
    execution_mode: Mapped[ToolExecutionMode] = mapped_column(
        SQLEnum(ToolExecutionMode, name="tool_version_execution_mode", create_constraint=True),
        default=ToolExecutionMode.SYNC,
        nullable=False
    )
    timeout: Mapped[int] = mapped_column(Integer, default=30000, nullable=False)
    retry_policy: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    supports_streaming: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    supports_cancellation: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    supports_idempotency: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    trust_level: Mapped[ToolTrustLevel] = mapped_column(
        SQLEnum(ToolTrustLevel, name="tool_version_trust_level", create_constraint=True),
        default=ToolTrustLevel.ORGANIZATION,
        nullable=False
    )
    input_schema: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    output_schema: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    configuration: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    metadata: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[ToolLifecycleStatus] = mapped_column(
        SQLEnum(ToolLifecycleStatus, name="tool_version_status", create_constraint=True),
        default=ToolLifecycleStatus.DRAFT,
        nullable=False
    )
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    deprecated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    tool: Mapped["Tool"] = relationship(back_populates="versions")
    executions: Mapped[List["ToolExecution"]] = relationship(back_populates="tool_version")

    __table_args__ = (
        UniqueConstraint("tool_id", "version", name="uq_tool_version_tool_version"),
        Index("ix_tool_versions_tool_id", "tool_id"),
        Index("ix_tool_versions_status", "status"),
        Index("ix_tool_versions_published_at", "published_at"),
    )


class ToolProvider(TimestampMixin, SoftDeleteMixin, UUIDMixin, Base):
    __tablename__ = "tool_providers"

    organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_type: Mapped[ToolProviderType] = mapped_column(
        SQLEnum(ToolProviderType, name="tool_provider_provider_type", create_constraint=True),
        nullable=False
    )
    configuration: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    supported_tool_types: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    health_status: Mapped[str] = mapped_column(String(20), default="UNKNOWN", nullable=False)
    last_health_check: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    organization: Mapped[Optional["Organization"]] = relationship()

    __table_args__ = (
        Index("ix_tool_providers_organization_id", "organization_id"),
        Index("ix_tool_providers_provider_type", "provider_type"),
        Index("ix_tool_providers_health_status", "health_status"),
    )


class ToolPolicy(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "tool_policies"

    organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    team_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), nullable=True, index=True
    )
    agent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=True, index=True
    )
    workflow_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=True, index=True
    )
    tool_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tools.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    allowed_tools: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    blocked_tools: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    allowed_categories: Mapped[List[ToolCategory]] = mapped_column(JSON, default=list, nullable=False)
    blocked_categories: Mapped[List[ToolCategory]] = mapped_column(JSON, default=list, nullable=False)
    allowed_risk_levels: Mapped[List[ToolRiskLevel]] = mapped_column(JSON, default=list, nullable=False)
    max_risk_level: Mapped[Optional[ToolRiskLevel]] = mapped_column(
        SQLEnum(ToolRiskLevel, name="tool_policy_max_risk_level", create_constraint=True),
        nullable=True
    )
    allowed_capabilities: Mapped[List[ToolCapability]] = mapped_column(JSON, default=list, nullable=False)
    blocked_capabilities: Mapped[List[ToolCapability]] = mapped_column(JSON, default=list, nullable=False)
    allowed_domains: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    blocked_domains: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    allowed_organizations: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    approval_required: Mapped[Dict[str, bool]] = mapped_column(JSON, default=dict, nullable=False)
    execution_limits: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    organization: Mapped[Optional["Organization"]] = relationship()
    tool: Mapped[Optional["Tool"]] = relationship(back_populates="policies")

    __table_args__ = (
        Index("ix_tool_policies_organization_id", "organization_id"),
        Index("ix_tool_policies_team_id", "team_id"),
        Index("ix_tool_policies_agent_id", "agent_id"),
        Index("ix_tool_policies_workflow_id", "workflow_id"),
        Index("ix_tool_policies_tool_id", "tool_id"),
        Index("ix_tool_policies_priority", "priority"),
        Index("ix_tool_policies_is_active", "is_active"),
    )


class ToolExecution(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "tool_executions"

    tool_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tools.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tool_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tool_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    workflow_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflows.id", ondelete="SET NULL"), nullable=True, index=True
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    node_execution_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(30), default="QUEUED", nullable=False)
    input: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    output: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    error: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    estimated_cost: Mapped[Optional[float]] = mapped_column(nullable=True)
    actual_cost: Mapped[Optional[float]] = mapped_column(nullable=True)
    metadata: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)

    tool: Mapped["Tool"] = relationship(back_populates="executions")
    tool_version: Mapped["ToolVersion"] = relationship(back_populates="executions")
    events: Mapped[List["ToolExecutionEvent"]] = relationship(back_populates="execution", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_tool_executions_organization_id", "organization_id"),
        Index("ix_tool_executions_tool_id", "tool_id"),
        Index("ix_tool_executions_agent_id", "agent_id"),
        Index("ix_tool_executions_workflow_id", "workflow_id"),
        Index("ix_tool_executions_user_id", "user_id"),
        Index("ix_tool_executions_status", "status"),
        Index("ix_tool_executions_started_at", "started_at"),
        Index("ix_tool_executions_idempotency_key", "idempotency_key"),
    )


class ToolExecutionEvent(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "tool_execution_events"

    execution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tool_executions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    execution: Mapped["ToolExecution"] = relationship(back_populates="events")

    __table_args__ = (
        Index("ix_tool_execution_events_execution_id", "execution_id"),
        Index("ix_tool_execution_events_event_type", "event_type"),
        Index("ix_tool_execution_events_sequence", "sequence"),
    )


class ToolHealth(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "tool_health"

    tool_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tools.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(20), default="UNKNOWN", nullable=False)
    last_check: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    success_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failure_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    avg_latency_ms: Mapped[float] = mapped_column(default=0.0, nullable=False)
    last_success: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_failure: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    error_rate: Mapped[float] = mapped_column(default=0.0, nullable=False)

    __table_args__ = (
        Index("ix_tool_health_tool_id", "tool_id"),
        Index("ix_tool_health_status", "status"),
        Index("ix_tool_health_last_check", "last_check"),
    )


class ToolUsage(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "tool_usage"

    tool_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tools.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    execution_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    success_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failure_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_duration_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_cost: Mapped[float] = mapped_column(default=0.0, nullable=False)

    __table_args__ = (
        UniqueConstraint("tool_id", "organization_id", "date", name="uq_tool_usage_tool_org_date"),
        Index("ix_tool_usage_tool_id", "tool_id"),
        Index("ix_tool_usage_organization_id", "organization_id"),
        Index("ix_tool_usage_date", "date"),
    )