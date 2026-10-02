import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any, TYPE_CHECKING
from sqlalchemy import String, Text, JSON, ForeignKey, Index, Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
import enum

from openagent.db.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from openagent.db.models.organization import Organization
    from openagent.db.models.agent import Agent
    from openagent.db.models.agent_version import AgentVersion
    from openagent.db.models.workflow_execution import WorkflowExecution
    from openagent.db.models.execution_event import ExecutionEvent
    from openagent.db.models.memory import Memory


class AgentRunStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AgentRun(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "agent_runs"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_version_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_versions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    workflow_execution_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_executions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[AgentRunStatus] = mapped_column(
        SQLEnum(AgentRunStatus, name="agent_run_status", create_constraint=True),
        default=AgentRunStatus.QUEUED,
        nullable=False
    )
    input: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    output: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    metadata: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    organization: Mapped["Organization"] = relationship()
    agent: Mapped["Agent"] = relationship(back_populates="runs")
    agent_version: Mapped[Optional["AgentVersion"]] = relationship(back_populates="runs")
    workflow_execution: Mapped[Optional["WorkflowExecution"]] = relationship(back_populates="agent_runs")
    events: Mapped[List["ExecutionEvent"]] = relationship(
        back_populates="agent_run", cascade="all, delete-orphan"
    )
    memories: Mapped[List["Memory"]] = relationship(
        back_populates="agent_run", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_agent_runs_organization_id", "organization_id"),
        Index("ix_agent_runs_agent_id", "agent_id"),
        Index("ix_agent_runs_workflow_execution_id", "workflow_execution_id"),
        Index("ix_agent_runs_status", "status"),
        Index("ix_agent_runs_started_at", "started_at"),
        Index("ix_agent_runs_organization_status", "organization_id", "status"),
        Index("ix_agent_runs_organization_created", "organization_id", "created_at"),
    )