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
    from openagent.db.models.credential import Credential


class IntegrationProvider(str, enum.Enum):
    GITHUB = "github"
    GITLAB = "gitlab"
    BITBUCKET = "bitbucket"
    GOOGLE = "google"
    MICROSOFT = "microsoft"
    SLACK = "slack"
    DISCORD = "discord"
    NOTION = "notion"
    TELEGRAM = "telegram"
    WHATSAPP = "whatsapp"
    HUBSPOT = "hubspot"
    STRIPE = "stripe"
    POSTGRES = "postgres"
    MYSQL = "mysql"
    MONGODB = "mongodb"
    REDIS = "redis"
    AWS = "aws"
    GCP = "gcp"
    AZURE = "azure"
    CUSTOM = "custom"


class IntegrationStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    ERROR = "error"
    PENDING = "pending"
    REVOKED = "revoked"


class Integration(TimestampMixin, SoftDeleteMixin, UUIDMixin, Base):
    __tablename__ = "integrations"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[IntegrationProvider] = mapped_column(
        SQLEnum(IntegrationProvider, name="integration_provider", create_constraint=True),
        nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[IntegrationStatus] = mapped_column(
        SQLEnum(IntegrationStatus, name="integration_status", create_constraint=True),
        default=IntegrationStatus.PENDING,
        nullable=False
    )
    configuration: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    credential_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("credentials.id", ondelete="SET NULL"), nullable=True, index=True
    )
    metadata: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    organization: Mapped["Organization"] = relationship(back_populates="integrations")
    credential: Mapped[Optional["Credential"]] = relationship(back_populates="integrations")

    __table_args__ = (
        Index("ix_integrations_organization_id", "organization_id"),
        Index("ix_integrations_provider", "provider"),
        Index("ix_integrations_credential_id", "credential_id"),
        Index("ix_integrations_status", "status"),
        Index("ix_integrations_deleted_at", "deleted_at"),
    )