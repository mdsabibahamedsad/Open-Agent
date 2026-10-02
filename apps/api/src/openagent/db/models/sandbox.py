"""Sandbox SQLAlchemy models (mirrors alembic 017_add_sandbox)."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy import JSON as SA_JSON
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from openagent.db.models.base import Base, TimestampMixin, UUIDMixin


class SandboxProvider(str, enum.Enum):
    docker = "docker"
    local = "local"
    kubernetes = "kubernetes"


class SandboxStatus(str, enum.Enum):
    CREATING = "CREATING"
    CREATED = "CREATED"
    STARTING = "STARTING"
    READY = "READY"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"
    DESTROYING = "DESTROYING"
    DESTROYED = "DESTROYED"


class SandboxExecutionStatus(str, enum.Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    WAITING = "WAITING"  # parked for approval (MP19 hook); never executes
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    CANCELLED = "CANCELLED"
    KILLED = "KILLED"
    RESOURCE_LIMIT = "RESOURCE_LIMIT"
    POLICY_DENIED = "POLICY_DENIED"
    SANDBOX_ERROR = "SANDBOX_ERROR"


class ImageTrustTier(str, enum.Enum):
    CORE = "CORE"
    VERIFIED = "VERIFIED"
    ORGANIZATION = "ORGANIZATION"
    CUSTOM = "CUSTOM"
    UNTRUSTED = "UNTRUSTED"


class Sandbox(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "sandboxes"

    sandbox_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True)
    owner_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    task_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True, index=True)
    workspace_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True, index=True)
    provider: Mapped[SandboxProvider] = mapped_column(
        SQLEnum(SandboxProvider, name="sandbox_provider", create_constraint=False),
        default=SandboxProvider.docker, nullable=False)
    profile: Mapped[str] = mapped_column(String(50), nullable=False, default="TEST")
    status: Mapped[SandboxStatus] = mapped_column(
        SQLEnum(SandboxStatus, name="sandbox_status", create_constraint=False),
        default=SandboxStatus.CREATING, nullable=False, index=True)
    provider_handle: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    image: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    image_digest: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    destroyed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    resource_config: Mapped[Dict[str, Any]] = mapped_column(SA_JSON, default=dict, nullable=False)
    mounts: Mapped[List[Any]] = mapped_column(SA_JSON, default=list, nullable=False)
    meta: Mapped[Dict[str, Any]] = mapped_column("metadata", SA_JSON, default=dict, nullable=False)


class SandboxProfileRow(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "sandbox_profiles"

    profile_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True, index=True)  # NULL = builtin/platform default
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    config: Mapped[Dict[str, Any]] = mapped_column(SA_JSON, default=dict, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    meta: Mapped[Dict[str, Any]] = mapped_column("metadata", SA_JSON, default=dict, nullable=False)


class SandboxExecution(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "sandbox_executions"

    execution_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True)
    sandbox_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("sandboxes.id", ondelete="CASCADE"),
        nullable=False, index=True)
    task_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True, index=True)
    command: Mapped[str] = mapped_column(Text, nullable=False)
    workdir: Mapped[str] = mapped_column(String(1024), nullable=False, default="/workspace")
    profile: Mapped[str] = mapped_column(String(50), nullable=False, default="TEST")
    status: Mapped[SandboxExecutionStatus] = mapped_column(
        SQLEnum(SandboxExecutionStatus, name="sandbox_execution_status",
                create_constraint=False),
        default=SandboxExecutionStatus.QUEUED, nullable=False, index=True)
    exit_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    signal: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    timed_out: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    oom_killed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    peak_memory_mb: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False, default="MEDIUM")
    risk_reasons: Mapped[List[Any]] = mapped_column(SA_JSON, default=list, nullable=False)
    policy_decision: Mapped[Dict[str, Any]] = mapped_column(SA_JSON, default=dict, nullable=False)
    stdout_tail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    stdout_ref: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    stderr_ref: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    artifacts: Mapped[List[Any]] = mapped_column(SA_JSON, default=list, nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    meta: Mapped[Dict[str, Any]] = mapped_column("metadata", SA_JSON, default=dict, nullable=False)


class SandboxLease(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "sandbox_leases"

    sandbox_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("sandboxes.id", ondelete="CASCADE"),
        nullable=False, index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True)
    owner: Mapped[str] = mapped_column(String(255), nullable=False)
    task_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True)
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    last_heartbeat_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)
    released_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)


class SandboxArtifact(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "sandbox_artifacts"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True)
    sandbox_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("sandboxes.id", ondelete="SET NULL"),
        nullable=True, index=True)
    execution_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("sandbox_executions.id", ondelete="SET NULL"),
        nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    kind: Mapped[str] = mapped_column(String(50), nullable=False, default="file")
    storage_ref: Mapped[str] = mapped_column(String(1024), nullable=False)
    size_bytes: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    mime_type: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    meta: Mapped[Dict[str, Any]] = mapped_column("metadata", SA_JSON, default=dict, nullable=False)


class SandboxEvent(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "sandbox_events"

    event_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True)
    sandbox_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("sandboxes.id", ondelete="SET NULL"),
        nullable=True, index=True)
    execution_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("sandbox_executions.id", ondelete="SET NULL"),
        nullable=True, index=True)
    type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    payload: Mapped[Dict[str, Any]] = mapped_column(SA_JSON, default=dict, nullable=False)
    meta: Mapped[Dict[str, Any]] = mapped_column("metadata", SA_JSON, default=dict, nullable=False)


class SandboxImagePolicy(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "sandbox_image_policies"

    organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True, index=True)  # NULL = platform default
    image: Mapped[str] = mapped_column(String(500), nullable=False)
    trust_tier: Mapped[ImageTrustTier] = mapped_column(
        SQLEnum(ImageTrustTier, name="image_trust_tier", create_constraint=False),
        default=ImageTrustTier.CUSTOM, nullable=False)
    allowed: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    require_digest: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    meta: Mapped[Dict[str, Any]] = mapped_column("metadata", SA_JSON, default=dict, nullable=False)
