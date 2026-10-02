import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any, TYPE_CHECKING
from sqlalchemy import String, Text, JSON, ForeignKey, Index, Enum as SQLEnum, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
import enum

from openagent.db.models.base import Base, TimestampMixin, SoftDeleteMixin, UUIDMixin

if TYPE_CHECKING:
    from openagent.db.models.organization import Organization
    from openagent.db.models.credential import Credential
    from openagent.db.models.team import Team
    from openagent.db.models.agent import Agent
    from openagent.db.models.workflow import Workflow


class MCPTransport(str, enum.Enum):
    STDIO = "stdio"
    STREAMABLE_HTTP = "streamable_http"
    SSE = "sse"
    WEBSOCKET = "websocket"


class MCPServerScope(str, enum.Enum):
    PLATFORM = "platform"
    ORGANIZATION = "organization"
    TEAM = "team"
    USER = "user"


class MCPTrustLevel(str, enum.Enum):
    CORE = "CORE"
    VERIFIED = "VERIFIED"
    ORGANIZATION = "ORGANIZATION"
    COMMUNITY = "COMMUNITY"
    UNTRUSTED = "UNTRUSTED"


class MCPServerStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    CONNECTING = "connecting"
    ERROR = "error"
    DISCONNECTED = "disconnected"
    DISABLED = "disabled"


class MCPConnectionState(str, enum.Enum):
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DEGRADED = "degraded"
    DISCONNECTED = "disconnected"
    FAILED = "failed"


class MCPCapabilityType(str, enum.Enum):
    TOOLS = "tools"
    RESOURCES = "resources"
    PROMPTS = "prompts"


class MCPServer(TimestampMixin, SoftDeleteMixin, UUIDMixin, Base):
    __tablename__ = "mcp_servers"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    scope: Mapped[MCPServerScope] = mapped_column(
        SQLEnum(MCPServerScope, name="mcp_server_scope", create_constraint=True),
        default=MCPServerScope.ORGANIZATION,
        nullable=False
    )
    transport: Mapped[MCPTransport] = mapped_column(
        SQLEnum(MCPTransport, name="mcp_transport", create_constraint=True),
        default=MCPTransport.STREAMABLE_HTTP,
        nullable=False
    )
    endpoint: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    command: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    args: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    env: Mapped[Dict[str, str]] = mapped_column(JSON, default=dict, nullable=False)
    working_directory: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    credential_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("credentials.id", ondelete="SET NULL"), nullable=True, index=True
    )
    trust_level: Mapped[MCPTrustLevel] = mapped_column(
        SQLEnum(MCPTrustLevel, name="mcp_trust_level", create_constraint=True),
        default=MCPTrustLevel.COMMUNITY,
        nullable=False
    )
    status: Mapped[MCPServerStatus] = mapped_column(
        SQLEnum(MCPServerStatus, name="mcp_server_status", create_constraint=True),
        default=MCPServerStatus.DISCONNECTED,
        nullable=False
    )
    enabled: Mapped[bool] = mapped_column(default=False, nullable=False)
    configuration: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    metadata: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    last_connected_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    connection_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    capability_version: Mapped[int] = mapped_column(default=0, nullable=False)
    capability_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    organization: Mapped["Organization"] = relationship(back_populates="mcp_servers")
    credential: Mapped[Optional["Credential"]] = relationship(back_populates="mcp_servers")
    connections: Mapped[List["MCPConnection"]] = relationship(back_populates="server", cascade="all, delete-orphan")
    tools: Mapped[List["MCPTool"]] = relationship(back_populates="server", cascade="all, delete-orphan")
    resources: Mapped[List["MCPResource"]] = relationship(back_populates="server", cascade="all, delete-orphan")
    prompts: Mapped[List["MCPPrompt"]] = relationship(back_populates="server", cascade="all, delete-orphan")
    health: Mapped[List["MCPHealth"]] = relationship(back_populates="server", cascade="all, delete-orphan")
    policies: Mapped[List["MCPPolicy"]] = relationship(back_populates="server", cascade="all, delete-orphan")
    executions: Mapped[List["MCPToolExecution"]] = relationship(back_populates="server", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_mcp_servers_organization_id", "organization_id"),
        Index("ix_mcp_servers_transport", "transport"),
        Index("ix_mcp_servers_status", "status"),
        Index("ix_mcp_servers_enabled", "enabled"),
        Index("ix_mcp_servers_trust_level", "trust_level"),
        Index("ix_mcp_servers_credential_id", "credential_id"),
        Index("ix_mcp_servers_deleted_at", "deleted_at"),
        UniqueConstraint("organization_id", "name", name="uq_mcp_server_org_name"),
    )


class MCPServerVersion(TimestampMixin, SoftDeleteMixin, UUIDMixin, Base):
    __tablename__ = "mcp_server_versions"

    server_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mcp_servers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    transport: Mapped[MCPTransport] = mapped_column(
        SQLEnum(MCPTransport, name="mcp_server_version_transport", create_constraint=True),
        nullable=False
    )
    endpoint: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    command: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    args: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    env: Mapped[Dict[str, str]] = mapped_column(JSON, default=dict, nullable=False)
    working_directory: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    credential_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("credentials.id", ondelete="SET NULL"), nullable=True
    )
    configuration: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    policy: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    protocol_preferences: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    capability_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    server: Mapped["MCPServer"] = relationship()

    __table_args__ = (
        Index("ix_mcp_server_versions_server_id", "server_id"),
    )


class MCPConnection(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "mcp_connections"

    server_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mcp_servers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    protocol_version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    state: Mapped[MCPConnectionState] = mapped_column(
        SQLEnum(MCPConnectionState, name="mcp_connection_state", create_constraint=True),
        default=MCPConnectionState.DISCONNECTED,
        nullable=False
    )
    capabilities: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    server_info: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)
    last_activity: Mapped[datetime] = mapped_column(default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    expires_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    server: Mapped["MCPServer"] = relationship(back_populates="connections")

    __table_args__ = (
        Index("ix_mcp_connections_server_id", "server_id"),
        Index("ix_mcp_connections_state", "state"),
        Index("ix_mcp_connections_session_id", "session_id"),
    )


class MCPTool(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "mcp_tools"

    server_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mcp_servers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    remote_name: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    input_schema: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    output_schema: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    annotations: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(20), default="LOW", nullable=False)
    capabilities: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    trust_level: Mapped[MCPTrustLevel] = mapped_column(
        SQLEnum(MCPTrustLevel, name="mcp_tool_trust_level", create_constraint=True),
        default=MCPTrustLevel.COMMUNITY,
        nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE", nullable=False)
    version: Mapped[str] = mapped_column(String(50), default="1.0.0", nullable=False)
    schema_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    server: Mapped["MCPServer"] = relationship(back_populates="tools")
    executions: Mapped[List["MCPToolExecution"]] = relationship(back_populates="mcp_tool")

    __table_args__ = (
        UniqueConstraint("server_id", "remote_name", name="uq_mcp_tool_server_remote"),
        Index("ix_mcp_tools_server_id", "server_id"),
        Index("ix_mcp_tools_remote_name", "remote_name"),
        Index("ix_mcp_tools_status", "status"),
        Index("ix_mcp_tools_risk_level", "risk_level"),
    )


class MCPResource(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "mcp_resources"

    server_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mcp_servers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    uri: Mapped[str] = mapped_column(String(500), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    mime_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    size: Mapped[Optional[int]] = mapped_column(nullable=True)
    metadata: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE", nullable=False)

    server: Mapped["MCPServer"] = relationship(back_populates="resources")

    __table_args__ = (
        UniqueConstraint("server_id", "uri", name="uq_mcp_resource_server_uri"),
        Index("ix_mcp_resources_server_id", "server_id"),
        Index("ix_mcp_resources_uri", "uri"),
        Index("ix_mcp_resources_mime_type", "mime_type"),
    )


class MCPPrompt(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "mcp_prompts"

    server_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mcp_servers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    remote_name: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    arguments: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE", nullable=False)

    server: Mapped["MCPServer"] = relationship(back_populates="prompts")

    __table_args__ = (
        UniqueConstraint("server_id", "remote_name", name="uq_mcp_prompt_server_remote"),
        Index("ix_mcp_prompts_server_id", "server_id"),
        Index("ix_mcp_prompts_remote_name", "remote_name"),
    )


class MCPHealth(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "mcp_health"

    server_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mcp_servers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(20), default="UNKNOWN", nullable=False)
    last_check: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)
    connection_success: Mapped[int] = mapped_column(default=0, nullable=False)
    connection_failure: Mapped[int] = mapped_column(default=0, nullable=False)
    tool_success: Mapped[int] = mapped_column(default=0, nullable=False)
    tool_failure: Mapped[int] = mapped_column(default=0, nullable=False)
    resource_reads: Mapped[int] = mapped_column(default=0, nullable=False)
    prompt_reads: Mapped[int] = mapped_column(default=0, nullable=False)
    avg_latency_ms: Mapped[float] = mapped_column(default=0.0, nullable=False)
    timeouts: Mapped[int] = mapped_column(default=0, nullable=False)
    protocol_errors: Mapped[int] = mapped_column(default=0, nullable=False)
    last_success: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    last_failure: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    server: Mapped["MCPServer"] = relationship(back_populates="health")

    __table_args__ = (
        Index("ix_mcp_health_server_id", "server_id"),
        Index("ix_mcp_health_status", "status"),
        Index("ix_mcp_health_last_check", "last_check"),
    )


class MCPPolicy(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "mcp_policies"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
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
    server_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mcp_servers.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    allowed_servers: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    blocked_servers: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    allowed_domains: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    blocked_domains: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    allowed_trust_levels: Mapped[List[MCPTrustLevel]] = mapped_column(
        SQLEnum(MCPTrustLevel, name="mcp_policy_allowed_trust", create_constraint=True),
        default=list, nullable=False
    )
    max_risk_level: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    approval_required: Mapped[Dict[str, bool]] = mapped_column(JSON, default=dict, nullable=False)
    execution_limits: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)

    organization: Mapped["Organization"] = relationship()
    server: Mapped[Optional["MCPServer"]] = relationship(back_populates="policies")

    __table_args__ = (
        Index("ix_mcp_policies_organization_id", "organization_id"),
        Index("ix_mcp_policies_team_id", "team_id"),
        Index("ix_mcp_policies_agent_id", "agent_id"),
        Index("ix_mcp_policies_workflow_id", "workflow_id"),
        Index("ix_mcp_policies_server_id", "server_id"),
        Index("ix_mcp_policies_is_active", "is_active"),
    )


class MCPToolExecution(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "mcp_tool_executions"

    server_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mcp_servers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    mcp_tool_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mcp_tools.id", ondelete="CASCADE"), nullable=False, index=True
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
    tool_execution_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tool_executions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(20), default="QUEUED", nullable=False)
    input: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    output: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    error: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    duration_ms: Mapped[int] = mapped_column(default=0, nullable=False)
    retry_count: Mapped[int] = mapped_column(default=0, nullable=False)
    is_retryable: Mapped[bool] = mapped_column(default=False, nullable=False)

    server: Mapped["MCPServer"] = relationship(back_populates="executions")
    mcp_tool: Mapped["MCPTool"] = relationship(back_populates="executions")

    __table_args__ = (
        Index("ix_mcp_tool_executions_server_id", "server_id"),
        Index("ix_mcp_tool_executions_mcp_tool_id", "mcp_tool_id"),
        Index("ix_mcp_tool_executions_organization_id", "organization_id"),
        Index("ix_mcp_tool_executions_agent_id", "agent_id"),
        Index("ix_mcp_tool_executions_workflow_id", "workflow_id"),
        Index("ix_mcp_tool_executions_status", "status"),
        Index("ix_mcp_tool_executions_started_at", "started_at"),
    )