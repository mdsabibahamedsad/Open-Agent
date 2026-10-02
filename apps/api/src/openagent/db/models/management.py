"""Management-layer persistence (MP14): managers, contracts, delegations,
handoffs, reviews, escalations, dynamic teams, workforce organization.

Reuses agents / orchestration_runs / orchestration_tasks / teams.
All tables carry organization_id with tenant-isolated indexes.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from openagent.db.models.base import Base, TimestampMixin, UUIDMixin


class ManagerProfileStatus(str, enum.Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    ARCHIVED = "archived"


class DelegationRequestStatus(str, enum.Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


class HandoffPackageStatus(str, enum.Enum):
    PREPARING = "preparing"
    PENDING_ACCEPTANCE = "pending_acceptance"
    ACCEPTED = "accepted"
    EXECUTING = "executing"
    COMPLETED = "completed"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class ReviewResultStatus(str, enum.Enum):
    APPROVED = "approved"
    REVISION_REQUIRED = "revision_required"
    REJECTED = "rejected"
    ESCALATE = "escalate"


class EscalationStatus(str, enum.Enum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    ESCALATED = "escalated"
    CLOSED = "closed"


class DynamicTeamStatus(str, enum.Enum):
    CREATED = "created"
    FORMING = "forming"
    ACTIVE = "active"
    WINDING_DOWN = "winding_down"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ManagerProfile(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "manager_profiles"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False, unique=True, index=True,
    )
    label: Mapped[str] = mapped_column(String(64), default="manager", nullable=False)
    status: Mapped[ManagerProfileStatus] = mapped_column(
        SQLEnum(ManagerProfileStatus, name="manager_profile_status", create_constraint=True),
        default=ManagerProfileStatus.ACTIVE, nullable=False,
    )
    managed_capabilities: Mapped[List[str]] = mapped_column(JSONB, default=list, nullable=False)
    delegation_policy: Mapped[str] = mapped_column(String(30), default="hybrid", nullable=False)
    review_required: Mapped[bool] = mapped_column(default=True, nullable=False)
    escalation_policy: Mapped[str] = mapped_column(String(64), default="default", nullable=False)
    team_policy: Mapped[str] = mapped_column(String(30), default="allow", nullable=False)
    budget_share: Mapped[float] = mapped_column(default=1.0, nullable=False)
    max_workers: Mapped[int] = mapped_column(Integer, default=20, nullable=False)
    max_depth: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    max_direct_reports: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    max_active_tasks: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    max_delegations: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    max_replans: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    max_team_size: Mapped[int] = mapped_column(Integer, default=12, nullable=False)
    allowed_actions: Mapped[List[str]] = mapped_column(JSONB, default=list, nullable=False)
    scope: Mapped[str] = mapped_column(String(20), default="organization", nullable=False)
    department_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_departments.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    team_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dynamic_teams.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    profile_metadata: Mapped[Dict[str, Any]] = mapped_column("metadata", JSONB, default=dict, nullable=False)

    __table_args__ = (
        Index("ix_manager_profiles_org_status", "organization_id", "status"),
    )


class AgentContract(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "agent_contracts"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    orchestration_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orchestration_runs.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )
    task_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orchestration_tasks.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    agent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    manager_agent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    responsibilities: Mapped[List[str]] = mapped_column(JSONB, default=list, nullable=False)
    inputs: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    expected_outputs: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    capabilities: Mapped[List[str]] = mapped_column(JSONB, default=list, nullable=False)
    constraints: Mapped[List[str]] = mapped_column(JSONB, default=list, nullable=False)
    required_permissions: Mapped[List[str]] = mapped_column("permissions", JSONB, default=list, nullable=False)
    budget: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    deadline: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    quality_requirements: Mapped[List[str]] = mapped_column(JSONB, default=list, nullable=False)
    acceptance_criteria: Mapped[List[Any]] = mapped_column(JSONB, default=list, nullable=False)
    escalation_conditions: Mapped[List[str]] = mapped_column(JSONB, default=list, nullable=False)
    max_revisions: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)

    __table_args__ = (
        Index("ix_agent_contracts_org_run", "organization_id", "orchestration_run_id"),
        Index("ix_agent_contracts_task", "task_id"),
    )


class DelegationRequest(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "delegation_requests"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    orchestration_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orchestration_runs.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )
    task_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orchestration_tasks.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    contract_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_contracts.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    source_agent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    target_agent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    required_capabilities: Mapped[List[str]] = mapped_column(JSONB, default=list, nullable=False)
    constraints: Mapped[List[str]] = mapped_column(JSONB, default=list, nullable=False)
    budget: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    deadline: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    policy: Mapped[str] = mapped_column(String(30), default="hybrid", nullable=False)
    status: Mapped[DelegationRequestStatus] = mapped_column(
        SQLEnum(DelegationRequestStatus, name="delegation_request_status", create_constraint=True),
        default=DelegationRequestStatus.PENDING, nullable=False, index=True,
    )
    decision_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    decided_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True,
    )
    decided_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(nullable=True, index=True)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)

    __table_args__ = (
        Index("ix_delegations_org_status", "organization_id", "status"),
        Index("ix_delegations_run", "orchestration_run_id", "status"),
    )


class AgentCommitment(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "agent_commitments"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    orchestration_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orchestration_runs.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )
    delegation_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("delegation_requests.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orchestration_tasks.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    deadline: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    budget: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    expected_output: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="accepted", nullable=False, index=True)
    accepted_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    released_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    __table_args__ = (
        Index("ix_commitments_task_agent", "task_id", "agent_id"),
    )


class HandoffPackage(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "handoff_packages"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    orchestration_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orchestration_runs.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orchestration_tasks.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    contract_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_contracts.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    source_agent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    target_agent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    mode: Mapped[str] = mapped_column(String(30), default="full_handoff", nullable=False)
    package: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    context_manifest: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    status: Mapped[HandoffPackageStatus] = mapped_column(
        SQLEnum(HandoffPackageStatus, name="handoff_package_status", create_constraint=True),
        default=HandoffPackageStatus.PREPARING, nullable=False, index=True,
    )
    accepted_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(nullable=True, index=True)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)

    __table_args__ = (
        Index("ix_handoff_packages_run_status", "orchestration_run_id", "status"),
        Index("ix_handoff_packages_task", "task_id", "created_at"),
    )


class ReviewResult(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "review_results"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    orchestration_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orchestration_runs.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orchestration_tasks.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    reviewer_agent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    status: Mapped[ReviewResultStatus] = mapped_column(
        SQLEnum(ReviewResultStatus, name="review_result_status", create_constraint=True),
        nullable=False, index=True,
    )
    criteria_results: Mapped[List[Any]] = mapped_column(JSONB, default=list, nullable=False)
    issues: Mapped[List[str]] = mapped_column(JSONB, default=list, nullable=False)
    required_changes: Mapped[List[str]] = mapped_column(JSONB, default=list, nullable=False)
    evidence: Mapped[List[str]] = mapped_column(JSONB, default=list, nullable=False)
    revision_number: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    gate_result: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    __table_args__ = (
        Index("ix_review_results_task_rev", "task_id", "revision_number"),
    )


class Escalation(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "escalations"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    orchestration_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orchestration_runs.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )
    task_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orchestration_tasks.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    source_agent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    current_holder_agent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    trigger: Mapped[str] = mapped_column(String(40), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(20), default="warning", nullable=False, index=True)
    status: Mapped[EscalationStatus] = mapped_column(
        SQLEnum(EscalationStatus, name="escalation_status", create_constraint=True),
        default=EscalationStatus.OPEN, nullable=False, index=True,
    )
    chain: Mapped[List[str]] = mapped_column(JSONB, default=list, nullable=False)
    chain_level: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    recommended_action: Mapped[str] = mapped_column(Text, default="", nullable=False)
    history: Mapped[List[Any]] = mapped_column(JSONB, default=list, nullable=False)
    human_approval_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("approvals.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)

    __table_args__ = (
        Index("ix_escalations_org_status", "organization_id", "status"),
        Index("ix_escalations_run", "orchestration_run_id", "status"),
    )


class AgentDepartment(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "agent_departments"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    slug: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)

    __table_args__ = (
        Index("ix_agent_departments_org_slug", "organization_id", "slug", unique=True),
    )


class DynamicTeam(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "dynamic_teams"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    orchestration_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orchestration_runs.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )
    task_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orchestration_tasks.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    manager_agent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    department_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_departments.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    team_type: Mapped[str] = mapped_column(String(30), default="temporary", nullable=False)
    status: Mapped[DynamicTeamStatus] = mapped_column(
        SQLEnum(DynamicTeamStatus, name="dynamic_team_status", create_constraint=True),
        default=DynamicTeamStatus.CREATED, nullable=False, index=True,
    )
    budget: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)

    __table_args__ = (
        Index("ix_dynamic_teams_org_status", "organization_id", "status"),
        Index("ix_dynamic_teams_run", "orchestration_run_id"),
    )


class TeamCharter(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "team_charters"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dynamic_teams.id", ondelete="CASCADE"),
        nullable=False, unique=True, index=True,
    )
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str] = mapped_column(Text, default="", nullable=False)
    responsibilities: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    communication_rules: Mapped[List[str]] = mapped_column(JSONB, default=list, nullable=False)
    completion_criteria: Mapped[List[str]] = mapped_column(JSONB, default=list, nullable=False)
    deadline: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    budget: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)


class DynamicTeamMembership(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "dynamic_team_memberships"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dynamic_teams.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    role: Mapped[str] = mapped_column(String(64), default="worker", nullable=False)
    responsibilities: Mapped[List[str]] = mapped_column(JSONB, default=list, nullable=False)
    permissions: Mapped[List[str]] = mapped_column(JSONB, default=list, nullable=False)
    task_scope: Mapped[List[str]] = mapped_column(JSONB, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False, index=True)

    __table_args__ = (
        Index("ix_dyn_team_member_unique", "team_id", "agent_id", unique=True),
        Index("ix_dyn_team_member_agent", "agent_id", "status"),
    )


class AgentAvailability(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "agent_availability"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False, unique=True, index=True,
    )
    state: Mapped[str] = mapped_column(String(20), default="available", nullable=False, index=True)
    active_tasks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    active_runs: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_heartbeat_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)


class AgentCapacity(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "agent_capacity"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False, unique=True, index=True,
    )
    max_concurrent_tasks: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    max_concurrent_runs: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    max_daily_cost: Mapped[float] = mapped_column(default=50.0, nullable=False)
    max_token_budget: Mapped[int] = mapped_column(Integer, default=500000, nullable=False)
    daily_cost_used: Mapped[float] = mapped_column(default=0.0, nullable=False)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class PlanVersion(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "plan_versions"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    orchestration_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orchestration_runs.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_by_agent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True,
    )
    changes: Mapped[List[str]] = mapped_column(JSONB, default=list, nullable=False)
    parent_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    plan_snapshot: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    __table_args__ = (
        Index("ix_plan_versions_run_version", "orchestration_run_id", "version", unique=True),
    )


class CollaborationRequest(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "collaboration_requests"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    orchestration_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orchestration_runs.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    task_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orchestration_tasks.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    from_agent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    to_agent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False, index=True)

    __table_args__ = (
        Index("ix_collab_run_status", "orchestration_run_id", "status"),
    )


class ManagerDecision(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "manager_decisions"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    orchestration_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orchestration_runs.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )
    manager_agent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    task_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orchestration_tasks.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    decision_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    selected_action: Mapped[str] = mapped_column(String(128), nullable=False)
    alternatives: Mapped[List[str]] = mapped_column(JSONB, default=list, nullable=False)
    policy_basis: Mapped[str] = mapped_column(Text, default="", nullable=False)
    rationale: Mapped[str] = mapped_column(Text, default="", nullable=False)

    __table_args__ = (
        Index("ix_manager_decisions_run", "orchestration_run_id", "created_at"),
    )
