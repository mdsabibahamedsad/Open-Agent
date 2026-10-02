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
    from openagent.db.models.integration import Integration
    from openagent.db.models.mcp import MCPServer
    from openagent.db.models.tool import Tool


class CredentialType(str, enum.Enum):
    API_KEY = "api_key"
    OAUTH_TOKEN = "oauth_token"
    BASIC_AUTH = "basic_auth"
    BEARER_TOKEN = "bearer_token"
    CERTIFICATE = "certificate"
    SSH_KEY = "ssh_key"
    DATABASE_URL = "database_url"
    CUSTOM = "custom"


class CredentialStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    EXPIRED = "expired"
    REVOKED = "revoked"


class Credential(TimestampMixin, SoftDeleteMixin, UUIDMixin, Base):
    __tablename__ = "credentials"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    credential_type: Mapped[CredentialType] = mapped_column(
        SQLEnum(CredentialType, name="credential_type", create_constraint=True),
        default=CredentialType.API_KEY,
        nullable=False
    )
    encrypted_data: Mapped[str] = mapped_column(Text, nullable=False)
    metadata: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[CredentialStatus] = mapped_column(
        SQLEnum(CredentialStatus, name="credential_status", create_constraint=True),
        default=CredentialStatus.ACTIVE,
        nullable=False
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    organization: Mapped["Organization"] = relationship(back_populates="credentials")
    integrations: Mapped[List["Integration"]] = relationship(back_populates="credential")
    mcp_servers: Mapped[List["MCPServer"]] = relationship(back_populates="credential")

    __table_args__ = (
        Index("ix_credentials_organization_id", "organization_id"),
        Index("ix_credentials_provider", "provider"),
        Index("ix_credentials_credential_type", "credential_type"),
        Index("ix_credentials_status", "status"),
        Index("ix_credentials_expires_at", "expires_at"),
        Index("ix_credentials_deleted_at", "deleted_at"),
    )