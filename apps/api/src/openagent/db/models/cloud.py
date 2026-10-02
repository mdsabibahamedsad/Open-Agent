"""MP25: cloud runtime persistence.

Additive tables only. Reuses existing ``workflow_executions``,
``execution_events`` (core), commerce usage/entitlement tables, and the
core ``scheduled_jobs`` table — no duplication.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from openagent.db.models.base import Base, TimestampMixin, UUIDMixin


class CloudRegion(Base, TimestampMixin, UUIDMixin):
    __tablename__ = "cloud_regions"

    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE", nullable=False, index=True)
    capabilities: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    residency_tags: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    cost_weight: Mapped[float] = mapped_column(default=1.0, nullable=False)
    max_workers: Mapped[int] = mapped_column(default=100, nullable=False)
    is_private: Mapped[bool] = mapped_column(default=False, nullable=False)
    region_metadata: Mapped[Dict[str, Any]] = mapped_column("metadata", JSONB, default=dict, nullable=False)


class WorkerPool(Base, TimestampMixin, UUIDMixin):
    __tablename__ = "worker_pools"

    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    region_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cloud_regions.id", ondelete="SET NULL"),
        nullable=True, index=True)
    capabilities: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    min_workers: Mapped[int] = mapped_column(default=0, nullable=False)
    max_workers: Mapped[int] = mapped_column(default=20, nullable=False)
    labels: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)


class CloudWorker(Base, TimestampMixin, UUIDMixin):
    __tablename__ = "cloud_workers"

    worker_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    service_identity: Mapped[str] = mapped_column(String(255), nullable=False)
    region_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cloud_regions.id", ondelete="SET NULL"),
        nullable=True, index=True)
    region_slug: Mapped[str] = mapped_column(String(100), nullable=False, default="local-1", index=True)
    pool_slug: Mapped[str] = mapped_column(String(100), nullable=False, default="default", index=True)
    capabilities: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    labels: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    state: Mapped[str] = mapped_column(String(32), default="REGISTERING", nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(50), default="0.1.0", nullable=False)
    max_concurrency: Mapped[int] = mapped_column(default=4, nullable=False)
    active_count: Mapped[int] = mapped_column(default=0, nullable=False)
    cpu_millicores_total: Mapped[int] = mapped_column(default=2000, nullable=False)
    memory_mb_total: Mapped[int] = mapped_column(default=4096, nullable=False)
    supports_gpu: Mapped[bool] = mapped_column(default=False, nullable=False)
    tenant_restriction: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    last_heartbeat_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    drained_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_cloud_workers_region_state", "region_slug", "state"),
        Index("ix_cloud_workers_pool_state", "pool_slug", "state"),
    )


class WorkerHeartbeat(Base, TimestampMixin, UUIDMixin):
    __tablename__ = "worker_heartbeats"

    worker_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    active_count: Mapped[int] = mapped_column(default=0, nullable=False)
    cpu_millicores_used: Mapped[int] = mapped_column(default=0, nullable=False)
    memory_mb_used: Mapped[int] = mapped_column(default=0, nullable=False)
    detail: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)


class ExecutionLease(Base, TimestampMixin, UUIDMixin):
    __tablename__ = "execution_leases"

    execution_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True)
    lease_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    owner_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    version: Mapped[int] = mapped_column(default=1, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    renewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    released_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_execution_leases_exec_owner", "execution_id", "owner_id"),
    )


class ExecutionPlacement(Base, TimestampMixin, UUIDMixin):
    __tablename__ = "execution_placements"

    execution_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True)
    region_slug: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    pool_slug: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    queue: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    priority: Mapped[str] = mapped_column(String(16), default="NORMAL", nullable=False)
    failover_from: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    residency: Mapped[str] = mapped_column(String(32), default="ANY_REGION", nullable=False)


class ExecutionAttempt(Base, TimestampMixin, UUIDMixin):
    __tablename__ = "execution_attempts"

    execution_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True)
    attempt: Mapped[int] = mapped_column(default=1, nullable=False)
    worker_id: Mapped[str] = mapped_column(String(128), default="", nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_execution_attempts_exec_attempt", "execution_id", "attempt"),
    )


class CloudQueueState(Base, TimestampMixin, UUIDMixin):
    __tablename__ = "cloud_queues"

    queue: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    depth: Mapped[int] = mapped_column(default=0, nullable=False)
    oldest_age_seconds: Mapped[float] = mapped_column(default=0.0, nullable=False)
    processing: Mapped[int] = mapped_column(default=0, nullable=False)
    dead_letter_count: Mapped[int] = mapped_column(default=0, nullable=False)
    paused: Mapped[bool] = mapped_column(default=False, nullable=False)


class DeadLetterMessage(Base, TimestampMixin, UUIDMixin):
    __tablename__ = "dead_letter_messages"

    message_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    queue: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    execution_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    payload: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="PENDING", nullable=False, index=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class SchedulerLease(Base, TimestampMixin, UUIDMixin):
    __tablename__ = "scheduler_leases"

    resource: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    owner_id: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[int] = mapped_column(default=1, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class ScheduleDedup(Base, TimestampMixin, UUIDMixin):
    __tablename__ = "schedule_dedup"

    schedule_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    execution_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    execution_id: Mapped[str] = mapped_column(String(64), nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CloudArtifact(Base, TimestampMixin, UUIDMixin):
    __tablename__ = "cloud_artifacts"

    artifact_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True)
    execution_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    task_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False, default="application/octet-stream")
    size: Mapped[int] = mapped_column(default=0, nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    checksum: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    category: Mapped[str] = mapped_column(String(64), nullable=False, default="execution-artifacts", index=True)
    state: Mapped[str] = mapped_column(String(32), default="ACTIVE", nullable=False, index=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    download_count: Mapped[int] = mapped_column(default=0, nullable=False)
    artifact_metadata: Mapped[Dict[str, Any]] = mapped_column("metadata", JSONB, default=dict, nullable=False)

    __table_args__ = (
        Index("ix_cloud_artifacts_org_state", "organization_id", "state"),
        Index("ix_cloud_artifacts_exec", "execution_id"),
    )


class CloudExecutionEvent(Base, TimestampMixin, UUIDMixin):
    """Durable per-execution event log (§37). Small metadata in Postgres;
    large payloads referenced via artifact refs."""

    __tablename__ = "cloud_execution_events"

    execution_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True)
    sequence: Mapped[int] = mapped_column(nullable=False)
    type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    __table_args__ = (
        Index("ix_cloud_execution_events_exec_seq", "execution_id", "sequence", unique=True),
    )


class CloudUsageEvent(Base, TimestampMixin, UUIDMixin):
    """Cloud execution usage staged for commerce aggregation (§38)."""

    __tablename__ = "cloud_usage_events"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True)
    execution_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    meter: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    quantity: Mapped[float] = mapped_column(default=0.0, nullable=False)
    dedup_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    exported: Mapped[bool] = mapped_column(default=False, nullable=False, index=True)

    __table_args__ = (
        Index("ix_cloud_usage_org_meter", "organization_id", "meter"),
    )


class RuntimePolicy(Base, TimestampMixin, UUIDMixin):
    """Org/global runtime policies: residency, pools, retention, limits."""

    __tablename__ = "runtime_policies"

    scope: Mapped[str] = mapped_column(String(32), nullable=False, index=True)  # global|organization
    organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True, index=True)
    residency: Mapped[str] = mapped_column(String(32), default="ANY_REGION", nullable=False)
    allowed_regions: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    pool_preference: Mapped[str] = mapped_column(String(100), default="default", nullable=False)
    max_concurrent_executions: Mapped[int] = mapped_column(default=10, nullable=False)
    artifact_retention_seconds: Mapped[int] = mapped_column(default=2592000, nullable=False)
    webhook_limit_per_minute: Mapped[int] = mapped_column(default=120, nullable=False)
    policy: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
