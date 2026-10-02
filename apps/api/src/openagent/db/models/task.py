import uuid
from datetime import datetime
from typing import Optional, Dict, Any, TYPE_CHECKING, List
from sqlalchemy import String, Text, JSON, ForeignKey, Index, Enum as SQLEnum, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
import enum

from openagent.db.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from openagent.db.models.organization import Organization
    from openagent.db.models.memory import Memory


class TaskStatus(str, enum.Enum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RETRYING = "retrying"


class TaskPriority(int, enum.Enum):
    LOW = 0
    NORMAL = 5
    HIGH = 10
    CRITICAL = 20


class Task(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "tasks"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    status: Mapped[TaskStatus] = mapped_column(
        SQLEnum(TaskStatus, name="task_status", create_constraint=True),
        default=TaskStatus.PENDING,
        nullable=False
    )
    priority: Mapped[TaskPriority] = mapped_column(
        default=TaskPriority.NORMAL, nullable=False
    )
    payload: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    result: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    available_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False, index=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    __table_args__ = (
        Index("ix_tasks_organization_id", "organization_id"),
        Index("ix_tasks_status", "status"),
        Index("ix_tasks_type", "type"),
        Index("ix_tasks_available_at", "available_at"),
        Index("ix_tasks_organization_status", "organization_id", "status"),
        Index("ix_tasks_organization_type_status", "organization_id", "type", "status"),
    )
    memories: Mapped[List["Memory"]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )