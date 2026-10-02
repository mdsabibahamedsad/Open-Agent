"""MP22: reusable package / skill / preset persistence.

Tenant model:

- ``organization_id NULL``  -> platform-official / community-global package.
- ``organization_id SET``   -> private org catalog entry (never exposed to
  the global catalog of other tenants).

Secrets are NEVER stored here: configurations keep only
``credential_reference`` / ``connection_reference`` ids pointing at the
existing ``credentials`` / ``connector_connections`` tables.
"""

import enum
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from openagent.db.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin


class ReusablePackageType(str, enum.Enum):
    AGENT = "AGENT"
    AGENT_TEAM = "AGENT_TEAM"
    WORKFORCE = "WORKFORCE"
    WORKFLOW = "WORKFLOW"
    SKILL = "SKILL"
    PROMPT = "PROMPT"
    TOOL_BUNDLE = "TOOL_BUNDLE"
    CONNECTOR_BUNDLE = "CONNECTOR_BUNDLE"
    MODEL_PRESET = "MODEL_PRESET"
    AGENT_PRESET = "AGENT_PRESET"
    WORKFLOW_PRESET = "WORKFLOW_PRESET"
    MEMORY_PRESET = "MEMORY_PRESET"
    AUTOMATION_RECIPE = "AUTOMATION_RECIPE"
    TEMPLATE_PACKAGE = "TEMPLATE_PACKAGE"


class PackageVersionStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    VALIDATING = "VALIDATING"
    VALIDATED = "VALIDATED"
    PUBLISHED = "PUBLISHED"
    DEPRECATED = "DEPRECATED"
    REVOKED = "REVOKED"
    ARCHIVED = "ARCHIVED"


class PackageTrust(str, enum.Enum):
    CORE = "CORE"
    VERIFIED = "VERIFIED"
    ORGANIZATION = "ORGANIZATION"
    COMMUNITY = "COMMUNITY"
    UNTRUSTED = "UNTRUSTED"


class PackageVisibility(str, enum.Enum):
    PRIVATE = "PRIVATE"
    TEAM = "TEAM"
    ORGANIZATION = "ORGANIZATION"
    PUBLIC = "PUBLIC"
    UNLISTED = "UNLISTED"


class PackageInstallStatus(str, enum.Enum):
    REQUESTED = "REQUESTED"
    RESOLVING = "RESOLVING"
    VALIDATING = "VALIDATING"
    AWAITING_CONFIGURATION = "AWAITING_CONFIGURATION"
    INSTALLING = "INSTALLING"
    VERIFYING = "VERIFYING"
    INSTALLED = "INSTALLED"
    FAILED = "FAILED"
    UPDATING = "UPDATING"
    ROLLING_BACK = "ROLLING_BACK"
    ROLLED_BACK = "ROLLED_BACK"
    UNINSTALLED = "UNINSTALLED"


class PresetKind(str, enum.Enum):
    MODEL_PRESET = "MODEL_PRESET"
    AGENT_PRESET = "AGENT_PRESET"
    WORKFLOW_PRESET = "WORKFLOW_PRESET"
    MEMORY_PRESET = "MEMORY_PRESET"


class ReusablePackage(SoftDeleteMixin, TimestampMixin, UUIDMixin, Base):
    """Package identity (stable across versions)."""

    __tablename__ = "reusable_packages"

    organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    slug: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    package_type: Mapped[ReusablePackageType] = mapped_column(
        SQLEnum(ReusablePackageType, name="reusable_package_type", create_constraint=True),
        nullable=False,
        index=True,
    )
    visibility: Mapped[PackageVisibility] = mapped_column(
        SQLEnum(PackageVisibility, name="package_visibility", create_constraint=True),
        default=PackageVisibility.ORGANIZATION,
        nullable=False,
        index=True,
    )
    trust: Mapped[PackageTrust] = mapped_column(
        SQLEnum(PackageTrust, name="package_trust", create_constraint=True),
        default=PackageTrust.UNTRUSTED,
        nullable=False,
        index=True,
    )
    official: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    license: Mapped[str] = mapped_column(String(64), nullable=False, default="Apache-2.0")
    author_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    author_email: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    publisher: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    icon: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    categories: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    tags: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    owner_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    team_ids: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    latest_version: Mapped[str] = mapped_column(String(32), nullable=False, default="")

    versions: Mapped[List["PackageVersion"]] = relationship(
        back_populates="package", cascade="all, delete-orphan",
        foreign_keys="PackageVersion.package_id")

    __table_args__ = (
        UniqueConstraint("organization_id", "slug", name="uq_reusable_packages_org_slug"),
        Index("ix_reusable_packages_type", "package_type"),
        Index("ix_reusable_packages_trust", "trust"),
        Index("ix_reusable_packages_visibility", "visibility"),
        Index("ix_reusable_packages_official", "official"),
    )


class PackageVersion(TimestampMixin, UUIDMixin, Base):
    """Immutable snapshot of a package definition."""

    __tablename__ = "package_versions"

    package_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reusable_packages.id", ondelete="CASCADE"),
        nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[PackageVersionStatus] = mapped_column(
        SQLEnum(PackageVersionStatus, name="package_version_status", create_constraint=True),
        default=PackageVersionStatus.DRAFT, nullable=False, index=True)
    manifest: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    risk: Mapped[str] = mapped_column(String(16), nullable=False, default="LOW")
    changelog: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    deprecated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Provenance (clone / fork): never mutated after creation.
    source_package_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reusable_packages.id", ondelete="SET NULL"),
        nullable=True)
    source_version: Mapped[str] = mapped_column(String(32), nullable=False, default="")

    package: Mapped["ReusablePackage"] = relationship(
        back_populates="versions", foreign_keys=[package_id])
    resources: Mapped[List["PackageResource"]] = relationship(
        back_populates="version", cascade="all, delete-orphan")
    dependencies: Mapped[List["PackageDependency"]] = relationship(
        back_populates="version", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("package_id", "version", name="uq_package_versions_package_version"),
        Index("ix_package_versions_status", "status"),
    )


class PackageResource(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "package_resources"

    version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("package_versions.id", ondelete="CASCADE"),
        nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    payload: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")

    version: Mapped["PackageVersion"] = relationship(back_populates="resources")

    __table_args__ = (
        UniqueConstraint("version_id", "kind", "slug",
                         name="uq_package_resources_version_kind_slug"),
        Index("ix_package_resources_kind", "kind"),
    )


class PackageDependency(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "package_dependencies"

    version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("package_versions.id", ondelete="CASCADE"),
        nullable=False, index=True)
    dep_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    package: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    constraint: Mapped[str] = mapped_column(String(64), nullable=False, default="*")
    optional: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    peer: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    version: Mapped["PackageVersion"] = relationship(back_populates="dependencies")


class Skill(SoftDeleteMixin, TimestampMixin, UUIDMixin, Base):
    """First-class reusable capability attachable to agents/workflows/teams."""

    __tablename__ = "skills"

    organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True, index=True)
    slug: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[PackageVersionStatus] = mapped_column(
        SQLEnum(PackageVersionStatus, name="skill_status", create_constraint=True),
        default=PackageVersionStatus.DRAFT, nullable=False, index=True)
    trust: Mapped[PackageTrust] = mapped_column(
        SQLEnum(PackageTrust, name="skill_trust", create_constraint=True),
        default=PackageTrust.UNTRUSTED, nullable=False, index=True)
    visibility: Mapped[PackageVisibility] = mapped_column(
        SQLEnum(PackageVisibility, name="skill_visibility", create_constraint=True),
        default=PackageVisibility.ORGANIZATION, nullable=False, index=True)
    official: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    categories: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    tags: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    owner_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    latest_version: Mapped[str] = mapped_column(String(32), nullable=False, default="")

    versions: Mapped[List["SkillVersion"]] = relationship(
        back_populates="skill", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("organization_id", "slug", name="uq_skills_org_slug"),
        Index("ix_skills_official", "official"),
    )


class SkillVersion(TimestampMixin, UUIDMixin, Base):
    """Immutable skill snapshot."""

    __tablename__ = "skill_versions"

    skill_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("skills.id", ondelete="CASCADE"),
        nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[PackageVersionStatus] = mapped_column(
        SQLEnum(PackageVersionStatus, name="skill_version_status", create_constraint=True),
        default=PackageVersionStatus.DRAFT, nullable=False, index=True)
    instructions: Mapped[str] = mapped_column(Text, nullable=False, default="")
    input_schema: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    output_schema: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    required_tools: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    required_connectors: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    model_requirements: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    memory_requirements: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    security_requirements: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    evaluation_criteria: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    skill: Mapped["Skill"] = relationship(back_populates="versions")

    __table_args__ = (
        UniqueConstraint("skill_id", "version", name="uq_skill_versions_skill_version"),
    )


class Preset(SoftDeleteMixin, TimestampMixin, UUIDMixin, Base):
    """Reusable model/agent/workflow/memory preset identity."""

    __tablename__ = "presets"

    organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True, index=True)
    slug: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[PresetKind] = mapped_column(
        SQLEnum(PresetKind, name="preset_kind", create_constraint=True),
        nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    visibility: Mapped[PackageVisibility] = mapped_column(
        SQLEnum(PackageVisibility, name="preset_visibility", create_constraint=True),
        default=PackageVisibility.ORGANIZATION, nullable=False, index=True)
    official: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    latest_version: Mapped[str] = mapped_column(String(32), nullable=False, default="")

    versions: Mapped[List["PresetVersion"]] = relationship(
        back_populates="preset", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("organization_id", "slug", name="uq_presets_org_slug"),
        Index("ix_presets_kind", "kind"),
    )


class PresetVersion(TimestampMixin, UUIDMixin, Base):
    """Immutable preset snapshot (references Model Router / Memory by name)."""

    __tablename__ = "preset_versions"

    preset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("presets.id", ondelete="CASCADE"),
        nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[PackageVersionStatus] = mapped_column(
        SQLEnum(PackageVersionStatus, name="preset_version_status", create_constraint=True),
        default=PackageVersionStatus.DRAFT, nullable=False, index=True)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    preset: Mapped["Preset"] = relationship(back_populates="versions")

    __table_args__ = (
        UniqueConstraint("preset_id", "version", name="uq_preset_versions_preset_version"),
    )


class PackageInstallation(TimestampMixin, UUIDMixin, Base):
    """Tenant-scoped installation of one package version."""

    __tablename__ = "package_installations"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True)
    package_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reusable_packages.id", ondelete="CASCADE"),
        nullable=False, index=True)
    version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("package_versions.id", ondelete="RESTRICT"),
        nullable=False, index=True)
    status: Mapped[PackageInstallStatus] = mapped_column(
        SQLEnum(PackageInstallStatus, name="package_install_status", create_constraint=True),
        default=PackageInstallStatus.REQUESTED, nullable=False, index=True)
    configuration: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    resolved_dependencies: Mapped[List[Dict[str, Any]]] = mapped_column(
        JSON, default=list, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    installed_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    previous_version_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("package_versions.id", ondelete="SET NULL"),
        nullable=True)
    update_available: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    installed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    resources: Mapped[List["InstallationResource"]] = relationship(
        back_populates="installation", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("organization_id", "idempotency_key",
                         name="uq_installations_org_idempotency"),
        Index("ix_installations_org_package", "organization_id", "package_id"),
        Index("ix_installations_status", "status"),
    )


class InstallationResource(TimestampMixin, UUIDMixin, Base):
    """One materialized graph node of an installation (agent/workflow/skill…)."""

    __tablename__ = "installation_resources"

    installation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("package_installations.id", ondelete="CASCADE"),
        nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(160), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    local_ref_type: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    local_ref_id: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    snapshot: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    installation: Mapped["PackageInstallation"] = relationship(back_populates="resources")

    __table_args__ = (
        Index("ix_installation_resources_kind", "installation_id", "kind"),
    )


class PackageSignature(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "package_signatures"

    version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("package_versions.id", ondelete="CASCADE"),
        nullable=False, index=True, unique=True)
    algorithm: Mapped[str] = mapped_column(String(32), nullable=False)
    signature: Mapped[str] = mapped_column(Text, nullable=False)
    key_id: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    signer: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class PackageSecurityScan(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "package_security_scans"

    version_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("package_versions.id", ondelete="CASCADE"),
        nullable=True, index=True)
    installation_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("package_installations.id", ondelete="CASCADE"),
        nullable=True, index=True)
    risk: Mapped[str] = mapped_column(String(16), nullable=False, default="LOW")
    findings: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    scanner_version: Mapped[str] = mapped_column(String(16), nullable=False, default="1")


class PackageValidationResult(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "package_validation_results"

    version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("package_versions.id", ondelete="CASCADE"),
        nullable=False, index=True)
    passed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    findings: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    stages: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class PackageFork(TimestampMixin, UUIDMixin, Base):
    """Fork lineage: which package was forked from what, by whom."""

    __tablename__ = "package_forks"

    package_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reusable_packages.id", ondelete="CASCADE"),
        nullable=False, index=True)
    parent_package_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reusable_packages.id", ondelete="SET NULL"),
        nullable=True, index=True)
    parent_version: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    forked_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class PackageUpdatePlan(TimestampMixin, UUIDMixin, Base):
    """Planned (approved-before-apply) update of an installation."""

    __tablename__ = "package_update_plans"

    installation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("package_installations.id", ondelete="CASCADE"),
        nullable=False, index=True)
    from_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("package_versions.id", ondelete="RESTRICT"),
        nullable=False)
    to_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("package_versions.id", ondelete="RESTRICT"),
        nullable=False)
    breaking: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    impact: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    migration_steps: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    approved_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class PackageCategory(TimestampMixin, UUIDMixin, Base):
    """Admin-managed catalog categories (seeded with STANDARD_CATEGORIES)."""

    __tablename__ = "package_categories"

    organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True, index=True)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    official: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        UniqueConstraint("organization_id", "slug", name="uq_package_categories_org_slug"),
    )


class PublisherProfile(TimestampMixin, UUIDMixin, Base):
    """Marketplace publisher identity (MP22 verification + MP23 profile).

    ``verified`` is kept in sync with ``verification_status`` by the
    marketplace service layer for backward compatibility.
    """

    __tablename__ = "publisher_profiles"

    organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True, index=True)
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), nullable=False, default="", index=True)
    publisher_type: Mapped[str] = mapped_column(String(32), nullable=False, default="INDIVIDUAL")
    avatar: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    banner: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    website: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    social_links: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    verification_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="UNVERIFIED", index=True)
    verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    trust_status: Mapped[str] = mapped_column(String(32), nullable=False, default="UNTRUSTED")
    suspended_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
