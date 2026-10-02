import uuid
from datetime import datetime
from typing import Optional, Dict, Any, TYPE_CHECKING
from sqlalchemy import String, Text, JSON, ForeignKey, Index, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID

from openagent.db.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from openagent.db.models.organization import Organization
    from openagent.db.models.workflow_execution import WorkflowExecution
    from openagent.db.models.agent_run import AgentRun


class ExecutionEvent(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "execution_events"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    run_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=True, index=True
    )
    workflow_execution_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_executions.id", ondelete="CASCADE"), nullable=True, index=True
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(nullable=False, index=True)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    agent_run: Mapped[Optional["AgentRun"]] = relationship(back_populates="events")
    workflow_execution: Mapped[Optional["WorkflowExecution"]] = relationship(back_populates="events")

    __table_args__ = (
        Index("ix_execution_events_organization_id", "organization_id"),
        Index("ix_execution_events_run_id", "run_id"),
        Index("ix_execution_events_workflow_execution_id", "workflow_execution_id"),
        Index("ix_execution_events_event_type", "event_type"),
        Index("ix_execution_events_timestamp", "timestamp"),
        Index("ix_execution_events_run_sequence", "run_id", "sequence"),
        Index("ix_execution_events_workflow_sequence", "workflow_execution_id", "sequence"),
        Index("ix_execution_events_organization_created", "organization_id", "created_at"),
    )