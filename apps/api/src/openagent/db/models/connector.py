"""Universal connector persistence (MP21).

Definition catalog (connectors/versions/capabilities/actions/triggers/
resources) mirrors validated manifests. Instances (connections) reference
the EXISTING credentials table — no duplicate credential storage.
Legacy `integrations` rows migrate into connector_connections (020).
"""

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from sqlalchemy import JSON, Boolean, ForeignKey, Index, Integer, String, Text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from openagent.db.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    pass


class ConnectorStatus(str, enum.Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    DISABLED = "disabled"
    DEPRECATED = "deprecated"
    SUSPENDED = "suspended"
    ERROR = "error"


class ConnectorType(str, enum.Enum):
    OFFICIAL = "official"
    COMMUNITY = "community"
    CUSTOM = "custom"
    INTERNAL = "internal"
    MCP_BACKED = "mcp_backed"
    HTTP_GENERIC = "http_generic"
    DATABASE = "database"
    WEBHOOK_ONLY = "webhook_only"


class ConnectorTrust(str, enum.Enum):
    CORE = "core"
    VERIFIED = "verified"
    ORGANIZATION = "organization"
    COMMUNITY = "community"
    CUSTOM = "custom"
    UNTRUSTED = "untrusted"


class ConnectionStatus(str, enum.Enum):
    UNCONNECTED = "unconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DEGRADED = "degraded"
    AUTH_EXPIRED = "auth_expired"
    ERROR = "error"
    DISCONNECTED = "disconnected"


class ConnectionScope(str, enum.Enum):
    PLATFORM = "platform"
    ORGANIZATION = "organization"
    TEAM = "team"
    USER = "user"
    WORKFLOW = "workflow"
    AGENT = "agent"


class SharingPolicy(str, enum.Enum):
    PRIVATE = "private"
    TEAM = "team"
    ORGANIZATION = "organization"
    WORKFLOW_ONLY = "workflow_only"


class ConnectorHealth(str, enum.Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    AUTH_EXPIRED = "auth_expired"
    RATE_LIMITED = "rate_limited"
    ERROR = "error"
    UNKNOWN = "unknown"


class Connector(TimestampMixin, UUIDMixin, Base):
    """Connector definition catalog entry (one row per connector id)."""

    __tablename__ = "connectors"

    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False, default="automation",
                                          index=True)
    connector_type: Mapped[ConnectorType] = mapped_column(
        SQLEnum(ConnectorType, name="connector_type", create_constraint=True),
        default=ConnectorType.OFFICIAL, nullable=False)
    trust: Mapped[ConnectorTrust] = mapped_column(
        SQLEnum(ConnectorTrust, name="connector_trust", create_constraint=True),
        default=ConnectorTrust.UNTRUSTED, nullable=False, index=True)
    status: Mapped[ConnectorStatus] = mapped_column(
        SQLEnum(ConnectorStatus, name="connector_status", create_constraint=True),
        default=ConnectorStatus.DRAFT, nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    publisher: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    license: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    documentation_url: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    current_version: Mapped[str] = mapped_column(String(32), nullable=False, default="1.0.0")
    signature: Mapped[str] = mapped_column(String(2000), nullable=False, default="")
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")

    versions: Mapped[List["ConnectorVersion"]] = relationship(
        back_populates="connector", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_connectors_category", "category"),
        Index("ix_connectors_trust", "trust"),
        Index("ix_connectors_status", "status"),
    )


class ConnectorVersion(TimestampMixin, UUIDMixin, Base):
    """Immutable per-version manifest snapshot. Workflows pin versions."""

    __tablename__ = "connector_versions"

    connector_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("connectors.id", ondelete="CASCADE"),
        nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    manifest: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    connector: Mapped["Connector"] = relationship(back_populates="versions")
    capabilities: Mapped[List["ConnectorCapability"]] = relationship(
        back_populates="version", cascade="all, delete-orphan")
    actions: Mapped[List["ConnectorAction"]] = relationship(
        back_populates="version", cascade="all, delete-orphan")
    triggers: Mapped[List["ConnectorTrigger"]] = relationship(
        back_populates="version", cascade="all, delete-orphan")
    resources: Mapped[List["ConnectorResource"]] = relationship(
        back_populates="version", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_connector_versions_connector", "connector_id"),
    )


class ConnectorCapability(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "connector_capabilities"

    version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("connector_versions.id", ondelete="CASCADE"),
        nullable=False, index=True)
    capability_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    description: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False, default="LOW")

    version: Mapped["ConnectorVersion"] = relationship(back_populates="capabilities")

    __table_args__ = (
        Index("ix_connector_capabilities_capability", "capability_id"),
    )


class ConnectorAction(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "connector_actions"

    version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("connector_versions.id", ondelete="CASCADE"),
        nullable=False, index=True)
    action_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    input_schema: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    output_schema: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    required_capabilities: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False, default="MEDIUM")
    supports_idempotency: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    mutation: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    version: Mapped["ConnectorVersion"] = relationship(back_populates="actions")

    __table_args__ = (
        Index("ix_connector_actions_action", "action_id"),
    )


class ConnectorTrigger(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "connector_triggers"

    version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("connector_versions.id", ondelete="CASCADE"),
        nullable=False, index=True)
    trigger_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="webhook")
    event_types: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    payload_schema: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    poll_config: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    version: Mapped["ConnectorVersion"] = relationship(back_populates="triggers")

    __table_args__ = (
        Index("ix_connector_triggers_trigger", "trigger_id"),
    )


class ConnectorResource(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "connector_resources"

    version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("connector_versions.id", ondelete="CASCADE"),
        nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    provider_kind: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    schema: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    version: Mapped["ConnectorVersion"] = relationship(back_populates="resources")


class ConnectorConnection(TimestampMixin, UUIDMixin, Base):
    """Tenant-scoped connector instance. Credentials live in credentials table."""

    __tablename__ = "connector_connections"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True)
    connector_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    connector_version: Mapped[str] = mapped_column(String(32), nullable=False,
                                                  default="1.0.0")
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    status: Mapped[ConnectionStatus] = mapped_column(
        SQLEnum(ConnectionStatus, name="connection_status", create_constraint=True),
        default=ConnectionStatus.UNCONNECTED, nullable=False, index=True)
    scope: Mapped[ConnectionScope] = mapped_column(
        SQLEnum(ConnectionScope, name="connection_scope", create_constraint=True),
        default=ConnectionScope.ORGANIZATION, nullable=False)
    sharing_policy: Mapped[SharingPolicy] = mapped_column(
        SQLEnum(SharingPolicy, name="sharing_policy", create_constraint=True),
        default=SharingPolicy.PRIVATE, nullable=False)
    owner_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True, index=True)
    team_ids: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    workflow_ids: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    credential_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("credentials.id", ondelete="SET NULL"),
        nullable=True, index=True)
    granted_capabilities: Mapped[List[str]] = mapped_column(JSON, default=list,
                                                            nullable=False)
    policy_config: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict,
                                                          nullable=False)
    config: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    oauth_state: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    health: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    last_error: Mapped[str] = mapped_column(Text, nullable=False, default="")

    __table_args__ = (
        Index("ix_connector_connections_org", "organization_id"),
        Index("ix_connector_connections_connector", "connector_id"),
        Index("ix_connector_connections_status", "status"),
        Index("ix_connector_connections_owner", "owner_user_id"),
        Index("ix_connector_connections_credential", "credential_id"),
    )


class ConnectorPermission(TimestampMixin, UUIDMixin, Base):
    """Granular per-connection grants (service account / user / team scope)."""

    __tablename__ = "connector_permissions"

    connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("connector_connections.id", ondelete="CASCADE"),
        nullable=False, index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True)
    grantee_type: Mapped[str] = mapped_column(String(32), nullable=False, default="user")
    grantee_id: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    capabilities: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)

    __table_args__ = (
        Index("ix_connector_permissions_connection", "connection_id"),
        Index("ix_connector_permissions_grantee", "grantee_type", "grantee_id"),
    )


class ConnectorWebhook(TimestampMixin, UUIDMixin, Base):
    """Inbound webhook endpoint. Only the secret HASH is stored."""

    __tablename__ = "connector_webhooks"

    connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("connector_connections.id", ondelete="CASCADE"),
        nullable=False, index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True)
    connector_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    endpoint: Mapped[str] = mapped_column(String(200), nullable=False)
    event_types: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    verify_mode: Mapped[str] = mapped_column(String(32), nullable=False,
                                             default="hmac_sha256")
    secret_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    secret_prefix: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    # Encrypted endpoint secret (platform key, bound to webhook id) so the
    # receiver can verify HMAC without ever storing plaintext.
    secret_cipher: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False,
                                            index=True)
    failure_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_delivery_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    last_signature_ok: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

    __table_args__ = (
        Index("ix_connector_webhooks_connection", "connection_id"),
        Index("ix_connector_webhooks_endpoint", "connector_id", "endpoint"),
    )


class ConnectorEvent(TimestampMixin, UUIDMixin, Base):
    """Normalized inbound event. Raw payloads stored only as references."""

    __tablename__ = "connector_events"

    webhook_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("connector_webhooks.id", ondelete="SET NULL"),
        nullable=True, index=True)
    connection_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("connector_connections.id", ondelete="SET NULL"),
        nullable=True, index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    resource_id: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    delivery_id: Mapped[str] = mapped_column(String(128), nullable=False, default="",
                                             index=True)
    payload_reference: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    attributes: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    processed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False,
                                            index=True)

    __table_args__ = (
        Index("ix_connector_events_org_type", "organization_id", "event_type"),
        Index("ix_connector_events_delivery", "delivery_id"),
    )


class ConnectorHealth(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "connector_health"

    connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("connector_connections.id", ondelete="CASCADE"),
        nullable=False, index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True)
    state: Mapped[ConnectorHealth] = mapped_column(
        SQLEnum(ConnectorHealth, name="connector_health", create_constraint=True),
        default=ConnectorHealth.UNKNOWN, nullable=False, index=True)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    auth_ok: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    detail: Mapped[str] = mapped_column(String(500), nullable=False, default="")

    __table_args__ = (
        Index("ix_connector_health_connection", "connection_id"),
    )


class ConnectorUsage(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "connector_usage"

    connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("connector_connections.id", ondelete="CASCADE"),
        nullable=False, index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True)
    period: Mapped[str] = mapped_column(String(16), nullable=False, default="",
                                        index=True)  # YYYY-MM-DD
    calls: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    successes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    latency_ms_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    __table_args__ = (
        Index("ix_connector_usage_connection_period", "connection_id", "period"),
    )


class ConnectorCursor(TimestampMixin, UUIDMixin, Base):
    """Polling cursor state per connection+trigger."""

    __tablename__ = "connector_cursors"

    connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("connector_connections.id", ondelete="CASCADE"),
        nullable=False, index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True)
    trigger_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    state: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    __table_args__ = (
        Index("ix_connector_cursors_connection_trigger", "connection_id", "trigger_id"),
    )
