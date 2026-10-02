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
    from openagent.db.models.workflow import Workflow
    from openagent.db.models.workflow_version import WorkflowVersion
    from openagent.db.models.agent_run import AgentRun
    from openagent.db.models.execution_event import ExecutionEvent


class WorkflowExecutionStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkflowExecutionTriggerType(str, enum.Enum):
    MANUAL = "manual"
    SCHEDULED = "scheduled"
    WEBHOOK = "webhook"
    API = "api"
    EVENT = "event"


class WorkflowExecution(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "workflow_executions"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workflow_version_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_versions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[WorkflowExecutionStatus] = mapped_column(
        SQLEnum(WorkflowExecutionStatus, name="workflow_execution_status", create_constraint=True),
        default=WorkflowExecutionStatus.QUEUED,
        nullable=False
    )
    trigger_type: Mapped[WorkflowExecutionTriggerType] = mapped_column(
        SQLEnum(WorkflowExecutionTriggerType, name="workflow_execution_trigger_type", create_constraint=True),
        default=WorkflowExecutionTriggerType.MANUAL,
        nullable=False
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    error_code: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metadata: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    organization: Mapped["Organization"] = relationship()
    workflow: Mapped["Workflow"] = relationship(back_populates="executions")
    workflow_version: Mapped[Optional["WorkflowVersion"]] = relationship(back_populates="executions")
    agent_runs: Mapped[List["AgentRun"]] = relationship(
        back_populates="workflow_execution", cascade="all, delete-orphan"
    )
    events: Mapped[List["ExecutionEvent"]] = relationship(
        back_populates="workflow_execution", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_workflow_executions_organization_id", "organization_id"),
        Index("ix_workflow_executions_workflow_id", "workflow_id"),
        Index("ix_workflow_executions_status", "status"),
        Index("ix_workflow_executions_started_at", "started_at"),
        Index("ix_workflow_executions_organization_status", "organization_id", "status"),
        Index("ix_workflow_executions_organization_created", "organization_id", "created_at"),
    )