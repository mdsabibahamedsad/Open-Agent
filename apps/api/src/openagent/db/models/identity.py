"""MP27: enterprise identity persistence (additive only).

Reuses users/organizations/memberships/teams/roles/permissions/
sessions/credentials/audit_logs. New tables cover IdPs, SSO, domains,
SCIM, group mappings, devices, auth/risk events, workload identities,
credential leases, security policies (+versions), decisions, data
rules, controls + evidence, and security alerts.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from openagent.db.models.base import Base, TimestampMixin, UUIDMixin


class IdentityProviderRow(Base, TimestampMixin, UUIDMixin):
    __tablename__ = "identity_providers"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True)
    provider_type: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    issuer: Mapped[str] = mapped_column(String(1024), default="", nullable=False)
    client_id: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    client_secret_ref: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    metadata_url: Mapped[str] = mapped_column(String(1024), default="", nullable=False)
    certificate_ref: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    attribute_mapping: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="DRAFT", nullable=False, index=True)
    enforce_mfa: Mapped[bool] = mapped_column(default=False, nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), default="", nullable=False)


class IdentityProviderDomain(Base, TimestampMixin, UUIDMixin):
    __tablename__ = "identity_provider_domains"

    provider_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("identity_providers.id", ondelete="CASCADE"),
        nullable=False, index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True)
    domain: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), default="PENDING", nullable=False, index=True)
    method: Mapped[str] = mapped_column(String(16), default="dns_txt", nullable=False)
    challenge_hash: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_idp_domains_domain", "domain"),
        Index("ix_idp_domains_org_status", "organization_id", "status"),
    )


class SsoSession(Base, TimestampMixin, UUIDMixin):
    __tablename__ = "sso_sessions"

    provider_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("identity_providers.id", ondelete="CASCADE"),
        nullable=False, index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True)
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True, index=True)
    subject: Mapped[str] = mapped_column(String(512), nullable=False)
    request_id: Mapped[str] = mapped_column(String(128), default="", nullable=False, index=True)
    auth_strength: Mapped[str] = mapped_column(String(8), default="AAL1", nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ScimCredentialRow(Base, TimestampMixin, UUIDMixin):
    __tablename__ = "scim_credentials"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    prefix: Mapped[str] = mapped_column(String(20), default="", nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked: Mapped[bool] = mapped_column(default=False, nullable=False, index=True)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(String(255), default="", nullable=False)


class ScimSyncRun(Base, TimestampMixin, UUIDMixin):
    __tablename__ = "scim_sync_runs"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True)
    credential_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scim_credentials.id", ondelete="SET NULL"),
        nullable=True)
    users_created: Mapped[int] = mapped_column(default=0, nullable=False)
    users_updated: Mapped[int] = mapped_column(default=0, nullable=False)
    users_deactivated: Mapped[int] = mapped_column(default=0, nullable=False)
    groups_synced: Mapped[int] = mapped_column(default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="completed", nullable=False)
    error: Mapped[str] = mapped_column(Text, default="", nullable=False)


class IdentityGroupMapping(Base, TimestampMixin, UUIDMixin):
    __tablename__ = "identity_group_mappings"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True)
    provider_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("identity_providers.id", ondelete="SET NULL"),
        nullable=True)
    external_group: Mapped[str] = mapped_column(String(512), nullable=False)
    team_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="SET NULL"),
        nullable=True)
    role: Mapped[str] = mapped_column(String(64), default="member", nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), default="", nullable=False)

    __table_args__ = (
        Index("ix_group_mappings_org_group", "organization_id", "external_group"),
    )


class DeviceRow(Base, TimestampMixin, UUIDMixin):
    __tablename__ = "devices"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True)
    device_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(32), default="unknown", nullable=False)
    platform: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    browser: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    trust: Mapped[str] = mapped_column(String(16), default="UNKNOWN", nullable=False, index=True)
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_devices_user_key", "user_id", "device_key"),
    )


class AuthenticationEvent(Base, TimestampMixin, UUIDMixin):
    __tablename__ = "authentication_events"

    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True, index=True)
    organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True, index=True)
    method: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    result: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    device_key: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    auth_strength: Mapped[str] = mapped_column(String(8), default="AAL1", nullable=False)
    detail: Mapped[str] = mapped_column(String(1024), default="", nullable=False)
    request_id: Mapped[str] = mapped_column(String(64), default="", nullable=False, index=True)

    __table_args__ = (
        Index("ix_auth_events_user_created", "user_id", "created_at"),
        Index("ix_auth_events_org_created", "organization_id", "created_at"),
    )


class SessionRiskEvent(Base, TimestampMixin, UUIDMixin):
    __tablename__ = "session_risk_events"

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True)
    score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    level: Mapped[str] = mapped_column(String(16), nullable=False)
    signals: Mapped[List[str]] = mapped_column(JSONB, default=list, nullable=False)


class WorkloadIdentityRow(Base, TimestampMixin, UUIDMixin):
    __tablename__ = "workload_identities"

    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True)
    execution_id: Mapped[str] = mapped_column(String(64), default="", nullable=False, index=True)
    region: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    pool: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    scopes: Mapped[List[str]] = mapped_column(JSONB, default=list, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked: Mapped[bool] = mapped_column(default=False, nullable=False, index=True)


class CredentialLeaseRow(Base, TimestampMixin, UUIDMixin):
    __tablename__ = "credential_leases"

    workload_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workload_identities.id", ondelete="CASCADE"),
        nullable=False, index=True)
    credential_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    scopes: Mapped[List[str]] = mapped_column(JSONB, default=list, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    uses: Mapped[int] = mapped_column(default=0, nullable=False)
    max_uses: Mapped[int] = mapped_column(default=1, nullable=False)
    revoked: Mapped[bool] = mapped_column(default=False, nullable=False, index=True)


class SecurityPolicyRow(Base, TimestampMixin, UUIDMixin):
    __tablename__ = "security_policies"

    scope: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    scope_id: Mapped[str] = mapped_column(String(128), default="", nullable=False, index=True)
    sections: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    version: Mapped[int] = mapped_column(default=1, nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)


class SecurityPolicyVersionRow(Base, TimestampMixin, UUIDMixin):
    __tablename__ = "security_policy_versions"

    policy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("security_policies.id", ondelete="CASCADE"),
        nullable=False, index=True)
    version: Mapped[int] = mapped_column(nullable=False)
    sections: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    changed_by: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    result: Mapped[str] = mapped_column(String(32), default="applied", nullable=False)


class PolicyDecisionRow(Base, TimestampMixin, UUIDMixin):
    __tablename__ = "policy_decisions"

    organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True, index=True)
    actor: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    action: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    resource: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    verdict: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    explanation: Mapped[str] = mapped_column(Text, default="", nullable=False)
    policy_id: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    request_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)

    __table_args__ = (
        Index("ix_policy_decisions_org_created",
              "organization_id", "created_at"),
    )


class DataRuleRow(Base, TimestampMixin, UUIDMixin):
    __tablename__ = "data_classification_rules"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True)
    rule_id: Mapped[str] = mapped_column(String(128), nullable=False)
    classification: Mapped[str] = mapped_column(String(16), nullable=False)
    pattern: Mapped[str] = mapped_column(Text, default="", nullable=False)
    action: Mapped[str] = mapped_column(String(16), default="redact", nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), default="", nullable=False)

    __table_args__ = (
        Index("ix_data_rules_org_rule", "organization_id", "rule_id"),
    )


class SecurityControlRow(Base, TimestampMixin, UUIDMixin):
    __tablename__ = "security_controls"

    organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True, index=True)
    control_id: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), default="implemented", nullable=False)
    owner: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    mappings: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    __table_args__ = (
        Index("ix_controls_org_control", "organization_id", "control_id"),
    )


class ControlEvidenceRow(Base, TimestampMixin, UUIDMixin):
    __tablename__ = "control_evidence"

    control_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("security_controls.id", ondelete="CASCADE"),
        nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    reference: Mapped[str] = mapped_column(Text, nullable=False)
    recorded_by: Mapped[str] = mapped_column(String(255), default="", nullable=False)


class SecurityAlertRow(Base, TimestampMixin, UUIDMixin):
    __tablename__ = "security_alerts"

    organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    detail: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="open", nullable=False, index=True)
    actor: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    request_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)

    __table_args__ = (
        Index("ix_security_alerts_org_status",
              "organization_id", "status"),
    )
