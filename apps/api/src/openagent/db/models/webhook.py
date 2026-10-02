import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any, TYPE_CHECKING
from sqlalchemy import String, Text, JSON, ForeignKey, Index, Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
import enum

from openagent.db.models.base import Base, TimestampMixin, SoftDeleteMixin, UUIDMixin

if TYPE_CHECKING:
    from openagent.db.models.organization import Organization
    from openagent.db.models.user import User


class WebhookStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    FAILED = "failed"
    PENDING = "pending"


class Webhook(TimestampMixin, SoftDeleteMixin, UUIDMixin, Base):
    __tablename__ = "webhooks"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    event_types: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    secret_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[WebhookStatus] = mapped_column(
        SQLEnum(WebhookStatus, name="webhook_status", create_constraint=True),
        default=WebhookStatus.PENDING,
        nullable=False
    )
    metadata: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    organization: Mapped["Organization"] = relationship(back_populates="webhooks")

    __table_args__ = (
        Index("ix_webhooks_organization_id", "organization_id"),
        Index("ix_webhooks_status", "status"),
        Index("ix_webhooks_deleted_at", "deleted_at"),
    )