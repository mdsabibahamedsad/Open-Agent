"""Multi-agent orchestration persistence models.

Reuses existing agents / agent_versions / agent_runs / execution_events.
Adds orchestration-scoped tables with organization isolation, FKs, indexes.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from openagent.db.models.base import Base, TimestampMixin, UUIDMixin


class OrchestrationRunStatus(str, enum.Enum):
    CREATED = "created"
    PLANNING = "planning"
    READY = "ready"
    RUNNING = "running"
    WAITING = "waiting"
    PAUSED = "paused"
    SUCCEEDED = "succeeded"
    PARTIALLY_SUCCEEDED = "partially_succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class OrchestrationTaskStatus(str, enum.Enum):
    CREATED = "created"
    READY = "ready"
    ASSIGNED = "assigned"
    RUNNING = "running"
    WAITING = "waiting"
    PAUSED = "paused"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class AgentRoleName(str, enum.Enum):
    CEO = "ceo"
    MANAGER = "manager"
    PLANNER = "planner"
    RESEARCHER = "researcher"
    DEVELOPER = "developer"
    CODER = "coder"
    DESIGNER = "designer"
    BROWSER_AGENT = "browser_agent"
    DATA_ANALYST = "data_analyst"
    MARKETING_AGENT = "marketing_agent"
    SALES_AGENT = "sales_agent"
    OPERATIONS_AGENT = "operations_agent"
    QA_AGENT = "qa_agent"
    SECURITY_AGENT = "security_agent"
    WRITER = "writer"
    REVIEWER = "reviewer"
    SPECIALIST = "specialist"
    WORKER = "worker"
    CUSTOM = "custom"


class AgentRelationshipType(str, enum.Enum):
    MANAGES = "manages"
    REPORTS_TO = "reports_to"
    COLLABORATES_WITH = "collaborates_with"
    CAN_DELEGATE_TO = "can_delegate_to"
    CAN_REVIEW = "can_review"
    SPECIALIZES_IN = "specializes_in"


class OrchestrationRun(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "orchestration_runs"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[OrchestrationRunStatus] = mapped_column(
        SQLEnum(OrchestrationRunStatus, name="orchestration_run_status", create_constraint=True),
        default=OrchestrationRunStatus.CREATED, nullable=False, index=True,
    )
    root_agent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    team_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    budget: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    usage: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    final_result: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    run_metadata: Mapped[Dict[str, Any]] = mapped_column("metadata", JSONB, default=dict, nullable=False)

    __table_args__ = (
        Index("ix_orch_runs_org_status", "organization_id", "status"),
        Index("ix_orch_runs_org_created", "organization_id", "created_at"),
    )


class OrchestrationTask(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "orchestration_tasks"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    orchestration_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orchestration_runs.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    parent_task_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orchestration_tasks.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    assigned_agent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    agent_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    external_task_id: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    instructions: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[OrchestrationTaskStatus] = mapped_column(
        SQLEnum(OrchestrationTaskStatus, name="orchestration_task_status", create_constraint=True),
        default=OrchestrationTaskStatus.CREATED, nullable=False, index=True,
    )
    priority: Mapped[str] = mapped_column(String(20), default="normal", nullable=False)
    dependency_policy: Mapped[str] = mapped_column(String(20), default="all_success", nullable=False)
    required_capabilities: Mapped[List[str]] = mapped_column(JSONB, default=list, nullable=False)
    required_permissions: Mapped[List[str]] = mapped_column(JSONB, default=list, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(20), default="low", nullable=False)
    requires_approval: Mapped[bool] = mapped_column(default=False, nullable=False)
    task_input: Mapped[Dict[str, Any]] = mapped_column("input", JSONB, default=dict, nullable=False)
    output: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_retries: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    retry_strategy: Mapped[str] = mapped_column(String(30), default="fixed", nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=600, nullable=False)
    depth: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    aggregation_strategy: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    lease_owner: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    lease_expires_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    last_heartbeat_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    task_metadata: Mapped[Dict[str, Any]] = mapped_column("metadata", JSONB, default=dict, nullable=False)

    __table_args__ = (
        Index("ix_orch_tasks_run_status", "orchestration_run_id", "status"),
        Index("ix_orch_tasks_run_external", "orchestration_run_id", "external_task_id", unique=True),
        Index("ix_orch_tasks_org_created", "organization_id", "created_at"),
    )


class OrchestrationTaskDependency(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "orchestration_task_dependencies"

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
    depends_on_task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orchestration_tasks.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    __table_args__ = (
        Index("ix_orch_task_deps_unique", "task_id", "depends_on_task_id", unique=True),
        Index("ix_orch_task_deps_run", "orchestration_run_id", "task_id"),
    )


class AgentRelationship(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "agent_relationships"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    source_agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    target_agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    relationship_type: Mapped[AgentRelationshipType] = mapped_column(
        SQLEnum(AgentRelationshipType, name="agent_relationship_type", create_constraint=True),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(64), default="worker", nullable=False)
    rel_metadata: Mapped[Dict[str, Any]] = mapped_column("metadata", JSONB, default=dict, nullable=False)

    __table_args__ = (
        Index("ix_agent_rel_unique", "organization_id", "source_agent_id", "target_agent_id",
              "relationship_type", unique=True),
        Index("ix_agent_rel_source", "source_agent_id", "relationship_type"),
    )


class AgentCapability(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "agent_capabilities"

    organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    version: Mapped[str] = mapped_column(String(32), default="1.0", nullable=False)
    required_tools: Mapped[List[str]] = mapped_column(JSONB, default=list, nullable=False)
    required_permissions: Mapped[List[str]] = mapped_column(JSONB, default=list, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(20), default="low", nullable=False)
    available: Mapped[bool] = mapped_column(default=True, nullable=False)

    __table_args__ = (
        Index("ix_agent_cap_unique", "agent_id", "name", unique=True),
        Index("ix_agent_cap_name", "name"),
    )


class AgentMessage(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "agent_messages"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    orchestration_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orchestration_runs.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    sender_agent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    recipient_agent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    task_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orchestration_tasks.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    message_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    correlation_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    reply_to: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    __table_args__ = (
        Index("ix_agent_msg_run_created", "orchestration_run_id", "created_at"),
        Index("ix_agent_msg_task", "task_id", "created_at"),
    )


class AgentHandoff(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "agent_handoffs"

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
    from_agent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True,
    )
    to_agent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True,
    )
    package: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="completed", nullable=False)


class OrchestrationTaskAttempt(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "orchestration_task_attempts"

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
    agent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True,
    )
    agent_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True,
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    output: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_orch_attempts_task", "task_id", "attempt_number", unique=True),
    )


class OrchestrationBudgetLedger(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "orchestration_budget_ledgers"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    orchestration_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orchestration_runs.id", ondelete="CASCADE"),
        nullable=False, unique=True, index=True,
    )
    limits: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    consumed_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    consumed_cost: Mapped[float] = mapped_column(Numeric(14, 6), default=0, nullable=False)  # type: ignore[assignment]
    consumed_tool_calls: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    consumed_steps: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    consumed_tasks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    consumed_agents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class OrchestrationEvent(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "orchestration_events"

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
    agent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True,
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    trace_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    span_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    parent_span_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        Index("ix_orch_events_run_created", "orchestration_run_id", "created_at"),
        Index("ix_orch_events_run_type", "orchestration_run_id", "event_type"),
    )


class AgentConflict(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "agent_conflicts"

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
    sources: Mapped[List[Any]] = mapped_column(JSONB, default=list, nullable=False)
    claims: Mapped[List[Any]] = mapped_column(JSONB, default=list, nullable=False)
    evidence: Mapped[List[Any]] = mapped_column(JSONB, default=list, nullable=False)
    confidence: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    resolution_status: Mapped[str] = mapped_column(String(30), default="open", nullable=False)
    resolution: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
