"""MP28: developer platform persistence (additive only).

Tenant model: every row is organization-scoped. Global/community rows use
organization_id NULL and are readable cross-tenant only through the
catalog path with explicit visibility checks — never raw.
"""

import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from openagent.db.models.base import Base, TimestampMixin, UUIDMixin


class DeveloperProjectStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class ExtensionLifecycle(str, enum.Enum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    PACKAGED = "PACKAGED"
    SIGNED = "SIGNED"
    PUBLISHED = "PUBLISHED"
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"
    DEPRECATED = "DEPRECATED"
    QUARANTINED = "QUARANTINED"
    REVOKED = "REVOKED"
    UNPUBLISHED = "UNPUBLISHED"


class DeploymentStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    HEALTHY = "HEALTHY"
    FAILED = "FAILED"
    ROLLED_BACK = "ROLLED_BACK"
    CANCELLED = "CANCELLED"


class DeveloperProject(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "developer_projects"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    slug: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")
    created_by: Mapped[str] = mapped_column(String(255), nullable=False, default="")

    __table_args__ = (Index("ix_developer_projects_org_slug", "organization_id", "slug", unique=True),)


class DeveloperProjectMember(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "developer_project_members"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("developer_projects.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="developer")

    __table_args__ = (Index("ix_project_members_unique", "project_id", "user_id", unique=True),)


class DeveloperEnvironment(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "developer_environments"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("developer_projects.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(32), nullable=False)  # development|staging|production
    api_endpoint: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    __table_args__ = (Index("ix_dev_envs_unique", "project_id", "name", unique=True),)


class ExtensionDefinition(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "extension_definitions"

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("developer_projects.id", ondelete="SET NULL"), nullable=True)
    slug: Mapped[str] = mapped_column(String(160), nullable=False)
    extension_type: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    lifecycle: Mapped[str] = mapped_column(String(16), nullable=False, default="DRAFT")
    trust_level: Mapped[str] = mapped_column(String(16), nullable=False, default="UNTRUSTED")
    publisher: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    license: Mapped[str] = mapped_column(String(64), nullable=False, default="MIT")
    repository: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    quarantined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    quarantine_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")

    __table_args__ = (Index("ix_extension_defs_org_slug", "organization_id", "slug", unique=True),)


class ExtensionVersion(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "extension_versions"

    extension_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("extension_definitions.id", ondelete="CASCADE"), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    manifest: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    content_digest: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    artifact_size: Mapped[int] = mapped_column(nullable=False, default=0)
    signature: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    compatibility: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    scan_report: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    validation_report: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    changelog: Mapped[str] = mapped_column(Text, nullable=False, default="")
    deprecated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (Index("ix_extension_versions_unique", "extension_id", "version", unique=True),)


class ExtensionInstallation(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "extension_installations"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    extension_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("extension_definitions.id", ondelete="CASCADE"), nullable=False)
    version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("extension_versions.id", ondelete="RESTRICT"), nullable=False)
    environment: Mapped[str] = mapped_column(String(32), nullable=False, default="production")
    granted_permissions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    config_values: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    installed_by: Mapped[str] = mapped_column(String(255), nullable=False, default="")

    __table_args__ = (
        Index("ix_ext_install_unique", "organization_id", "extension_id", "environment", unique=True),
    )


class ExtensionDeployment(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "extension_deployments"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    extension_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("extension_definitions.id", ondelete="CASCADE"), nullable=False)
    version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("extension_versions.id", ondelete="RESTRICT"), nullable=False)
    environment: Mapped[str] = mapped_column(String(32), nullable=False, default="staging")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    stages: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    health: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    deployed_by: Mapped[str] = mapped_column(String(255), nullable=False, default="")


class DeveloperWebhook(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "developer_webhooks"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("developer_projects.id", ondelete="SET NULL"), nullable=True)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    events: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    secret_ref: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class DeveloperWebhookDelivery(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "developer_webhook_deliveries"

    webhook_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("developer_webhooks.id", ondelete="CASCADE"), nullable=False)
    event: Mapped[str] = mapped_column(String(128), nullable=False)
    delivery_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    attempts: Mapped[int] = mapped_column(nullable=False, default=0)


class ExtensionAnalyticsDaily(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "extension_analytics_daily"

    extension_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("extension_definitions.id", ondelete="CASCADE"), nullable=False)
    day: Mapped[str] = mapped_column(String(10), nullable=False)  # YYYY-MM-DD
    installs: Mapped[int] = mapped_column(nullable=False, default=0)
    invocations: Mapped[int] = mapped_column(nullable=False, default=0)
    errors: Mapped[int] = mapped_column(nullable=False, default=0)
    avg_latency_ms: Mapped[int] = mapped_column(nullable=False, default=0)

    __table_args__ = (Index("ix_ext_analytics_unique", "extension_id", "day", unique=True),)


class ExtensionTrustRecord(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "extension_trust_records"

    extension_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("extension_definitions.id", ondelete="CASCADE"), nullable=False)
    key_id: Mapped[str] = mapped_column(String(128), nullable=False)
    public_key: Mapped[str] = mapped_column(Text, nullable=False, default="")
    revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    publisher: Mapped[str] = mapped_column(String(255), nullable=False, default="")
