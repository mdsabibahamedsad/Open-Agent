import uuid
from datetime import datetime
from typing import Optional, Dict, Any, TYPE_CHECKING
from sqlalchemy import String, Text, JSON, ForeignKey, Index, Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
import enum

from openagent.db.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from openagent.db.models.organization import Organization
    from openagent.db.models.user import User


class ApprovalType(str, enum.Enum):
    TOOL_USE = "tool_use"
    RESOURCE_ACCESS = "resource_access"
    DATA_SHARING = "data_sharing"
    WORKFLOW_EXECUTION = "workflow_execution"
    AGENT_ACTION = "agent_action"
    CUSTOM = "custom"


class ApprovalStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    EXECUTING = "executing"
    EXECUTED = "executed"
    EXECUTION_FAILED = "execution_failed"
    INVALIDATED = "invalidated"


class Approval(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "approvals"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    run_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    workflow_execution_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_executions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    approval_type: Mapped[ApprovalType] = mapped_column(
        SQLEnum(ApprovalType, name="approval_type", create_constraint=True),
        default=ApprovalType.CUSTOM,
        nullable=False
    )
    status: Mapped[ApprovalStatus] = mapped_column(
        SQLEnum(ApprovalStatus, name="approval_status", create_constraint=True),
        default=ApprovalStatus.PENDING,
        nullable=False, index=True
    )
    requested_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    payload: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    decision: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(nullable=True, index=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    # Reverse side of Organization.approvals (pre-existing back_populates had
    # no counterpart, which broke mapper configuration).
    organization: Mapped["Organization"] = relationship(back_populates="approvals")
    requester: Mapped[Optional["User"]] = relationship(foreign_keys="Approval.requested_by")
    approver: Mapped[Optional["User"]] = relationship(foreign_keys="Approval.approved_by")

    __table_args__ = (
        Index("ix_approvals_organization_id", "organization_id"),
        Index("ix_approvals_run_id", "run_id"),
        Index("ix_approvals_workflow_execution_id", "workflow_execution_id"),
        Index("ix_approvals_status", "status"),
        Index("ix_approvals_requested_by", "requested_by"),
        Index("ix_approvals_approved_by", "approved_by"),
        Index("ix_approvals_expires_at", "expires_at"),
        Index("ix_approvals_organization_status", "organization_id", "status"),
    )


class ApprovalStep(TimestampMixin, UUIDMixin, Base):
    """Sequential / multi-approval chain step (MP19)."""

    __tablename__ = "approval_steps"

    approval_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("approvals.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    step_index: Mapped[int] = mapped_column(nullable=False, default=0)
    required_role: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending", index=True)
    decided_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    decided_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    __table_args__ = (
        Index("ix_approval_steps_approval", "approval_id"),
        Index("ix_approval_steps_org_status", "organization_id", "status"),
    )


class ApprovalDecision(TimestampMixin, UUIDMixin, Base):
    """One human decision per approver (quorum counting + idempotency)."""

    __tablename__ = "approval_decisions"

    approval_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("approvals.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    actor_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
        index=True,
    )
    decision: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    __table_args__ = (
        Index("ix_approval_decisions_approval", "approval_id"),
        Index("ix_approval_decisions_actor", "actor_id"),
    )


class ApprovalPolicy(TimestampMixin, UUIDMixin, Base):
    """Declarative guardrail policy (org/team/agent scoped)."""

    __tablename__ = "approval_policies"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    team_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True,
    )
    agent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    level: Mapped[str] = mapped_column(String(30), nullable=False, default="organization")
    rules: Mapped[Dict[str, Any]] = mapped_column(JSON, default=list, nullable=False)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True, index=True)
    version: Mapped[int] = mapped_column(nullable=False, default=1)

    __table_args__ = (
        Index("ix_approval_policies_org_active", "organization_id", "is_active"),
        Index("ix_approval_policies_team", "team_id"),
        Index("ix_approval_policies_agent", "agent_id"),
    )


class ApprovalPolicyVersion(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "approval_policy_versions"

    policy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("approval_policies.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    version: Mapped[int] = mapped_column(nullable=False)
    rules: Mapped[Dict[str, Any]] = mapped_column(JSON, default=list, nullable=False)

    __table_args__ = (Index("ix_approval_policy_versions_policy", "policy_id"),)


class ApprovalEscalation(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "approval_escalations"

    approval_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("approvals.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    escalated_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    escalate_to: Mapped[str] = mapped_column(String(100), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (Index("ix_approval_escalations_approval", "approval_id"),)


class ApprovalSnapshot(TimestampMixin, UUIDMixin, Base):
    """Deterministic action snapshot binding approval to exact action bytes."""

    __tablename__ = "approval_action_snapshots"

    approval_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("approvals.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    action_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    snapshot: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    __table_args__ = (Index("ix_approval_snapshots_hash", "action_hash"),)


class ApprovalEvent(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "approval_events"

    approval_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("approvals.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    actor_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    actor_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    event_data: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    __table_args__ = (
        Index("ix_approval_events_approval", "approval_id"),
        Index("ix_approval_events_org_created", "organization_id", "created_at"),
    )


class ApprovalDelegation(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "approval_delegations"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    delegator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    delegate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    scope: Mapped[str] = mapped_column(String(200), nullable=False)
    starts_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)

    __table_args__ = (
        Index("ix_approval_delegations_org", "organization_id"),
        Index("ix_approval_delegations_delegate", "delegate_id"),
    )