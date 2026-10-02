"""MP26: control-plane persistence (additive only).

Durable state for configuration (+versions), feature flags, alerting,
incidents, maintenance, deployments, operation locks, SLOs, platform
events, IP policies, rotation jobs, private enrollments, backup
reports. Reuses audit_logs + security_events (no duplication).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from openagent.db.models.base import Base, TimestampMixin, UUIDMixin


class PlatformConfig(Base, TimestampMixin, UUIDMixin):
    __tablename__ = "platform_configs"

    scope: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    scope_id: Mapped[str] = mapped_column(String(128), default="", nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    value: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    version: Mapped[int] = mapped_column(default=1, nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), default="", nullable=False)

    __table_args__ = (
        Index("ix_platform_configs_scope_key", "scope", "scope_id", "category", "key"),
    )


class ConfigVersionRow(Base, TimestampMixin, UUIDMixin):
    __tablename__ = "config_versions"

    scope: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    scope_id: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    key: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    before: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    after: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    changes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    rollback_reference: Mapped[str] = mapped_column(String(128), default="", nullable=False)


class FeatureFlagRow(Base, TimestampMixin, UUIDMixin):
    __tablename__ = "feature_flags"

    key: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    scope: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    scope_id: Mapped[str] = mapped_column(String(128), default="", nullable=False, index=True)
    strategy: Mapped[str] = mapped_column(String(32), default="boolean", nullable=False)
    enabled: Mapped[bool] = mapped_column(default=False, nullable=False)
    percentage: Mapped[float] = mapped_column(default=0.0, nullable=False)
    allowlist: Mapped[List[str]] = mapped_column(JSONB, default=list, nullable=False)
    denylist: Mapped[List[str]] = mapped_column(JSONB, default=list, nullable=False)
    version: Mapped[int] = mapped_column(default=1, nullable=False)
    label: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    updated_by: Mapped[str] = mapped_column(String(255), default="", nullable=False)

    __table_args__ = (
        Index("ix_feature_flags_key_scope", "key", "scope", "scope_id"),
    )


class AlertRuleRow(Base, TimestampMixin, UUIDMixin):
    __tablename__ = "alert_rules"

    organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    metric: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    condition: Mapped[str] = mapped_column(String(8), default="gt", nullable=False)
    threshold: Mapped[float] = mapped_column(default=0.0, nullable=False)
    duration_seconds: Mapped[int] = mapped_column(default=300, nullable=False)
    severity: Mapped[str] = mapped_column(String(16), default="WARNING", nullable=False)
    destinations: Mapped[List[str]] = mapped_column(JSONB, default=list, nullable=False)
    enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), default="", nullable=False)


class AlertRow(Base, TimestampMixin, UUIDMixin):
    __tablename__ = "alerts"

    rule_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("alert_rules.id", ondelete="SET NULL"),
        nullable=True, index=True)
    organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True, index=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    condition: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    threshold: Mapped[float] = mapped_column(default=0.0, nullable=False)
    observed: Mapped[float] = mapped_column(default=0.0, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="FIRING", nullable=False, index=True)
    dedup_key: Mapped[str] = mapped_column(String(64), default="", nullable=False, index=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    alert_metadata: Mapped[Dict[str, Any]] = mapped_column("metadata", JSONB, default=dict, nullable=False)

    __table_args__ = (
        Index("ix_alerts_status_severity", "status", "severity"),
        Index("ix_alerts_org_status", "organization_id", "status"),
    )


class IncidentRow(Base, TimestampMixin, UUIDMixin):
    __tablename__ = "incidents"

    organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), default="DETECTED", nullable=False, index=True)
    affected_services: Mapped[List[str]] = mapped_column(JSONB, default=list, nullable=False)
    affected_regions: Mapped[List[str]] = mapped_column(JSONB, default=list, nullable=False)
    responders: Mapped[List[str]] = mapped_column(JSONB, default=list, nullable=False)
    actions: Mapped[List[str]] = mapped_column(JSONB, default=list, nullable=False)
    resolution: Mapped[str] = mapped_column(Text, default="", nullable=False)
    postmortem_ref: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_incidents_status", "status"),
        Index("ix_incidents_org_status", "organization_id", "status"),
    )


class IncidentTimelineRow(Base, TimestampMixin, UUIDMixin):
    __tablename__ = "incident_timeline"

    incident_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("incidents.id", ondelete="CASCADE"),
        nullable=False, index=True)
    actor: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        Index("ix_incident_timeline_incident", "incident_id", "created_at"),
    )


class MaintenanceRow(Base, TimestampMixin, UUIDMixin):
    __tablename__ = "maintenance_windows"

    title: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    affected: Mapped[List[str]] = mapped_column(JSONB, default=list, nullable=False)
    expected_behavior: Mapped[str] = mapped_column(Text, default="", nullable=False)
    active: Mapped[bool] = mapped_column(default=True, nullable=False, index=True)
    created_by: Mapped[str] = mapped_column(String(255), default="", nullable=False)


class DeploymentRow(Base, TimestampMixin, UUIDMixin):
    __tablename__ = "deployments"

    service: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    commit: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    build: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    environment: Mapped[str] = mapped_column(String(32), default="production", nullable=False, index=True)
    deployer: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="PENDING", nullable=False, index=True)
    deployed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_deployments_service_env", "service", "environment"),
    )


class OperationLockRow(Base, TimestampMixin, UUIDMixin):
    __tablename__ = "operation_locks"

    resource: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    owner: Mapped[str] = mapped_column(String(255), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class ServiceSloRow(Base, TimestampMixin, UUIDMixin):
    __tablename__ = "service_slos"

    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    unit: Mapped[str] = mapped_column(String(16), default="ratio", nullable=False)
    target: Mapped[float] = mapped_column(default=0.99, nullable=False)
    window: Mapped[str] = mapped_column(String(16), default="30d", nullable=False)
    enabled: Mapped[bool] = mapped_column(default=True, nullable=False)


class PlatformEventRow(Base, TimestampMixin, UUIDMixin):
    __tablename__ = "platform_events"

    event_type: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(255), nullable=False)
    actor: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    scope: Mapped[str] = mapped_column(String(128), default="platform", nullable=False, index=True)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    request_id: Mapped[str] = mapped_column(String(64), default="", nullable=False, index=True)

    __table_args__ = (
        Index("ix_platform_events_type_created", "event_type", "created_at"),
    )


class IpPolicyRow(Base, TimestampMixin, UUIDMixin):
    __tablename__ = "ip_policies"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True)
    allowlist: Mapped[List[str]] = mapped_column(JSONB, default=list, nullable=False)
    denylist: Mapped[List[str]] = mapped_column(JSONB, default=list, nullable=False)
    enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    updated_by: Mapped[str] = mapped_column(String(255), default="", nullable=False)


class RotationJobRow(Base, TimestampMixin, UUIDMixin):
    __tablename__ = "rotation_jobs"

    kind: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    ref: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    stage: Mapped[str] = mapped_column(String(32), default="created", nullable=False, index=True)
    error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class PrivateEnrollmentRow(Base, TimestampMixin, UUIDMixin):
    __tablename__ = "private_enrollments"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    used: Mapped[bool] = mapped_column(default=False, nullable=False)
    worker_id: Mapped[str] = mapped_column(String(128), default="", nullable=False)


class BackupReportRow(Base, TimestampMixin, UUIDMixin):
    __tablename__ = "backup_reports"

    kind: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    detail: Mapped[str] = mapped_column(Text, default="", nullable=False)
    measured_rpo_seconds: Mapped[Optional[float]] = mapped_column(nullable=True)
    measured_rto_seconds: Mapped[Optional[float]] = mapped_column(nullable=True)
    restore_tested_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    reported_by: Mapped[str] = mapped_column(String(255), default="", nullable=False)
