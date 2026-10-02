import uuid
from datetime import datetime
from typing import TYPE_CHECKING
from sqlalchemy import ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID

from openagent.db.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from openagent.db.models.role import Role
    from openagent.db.models.permission import Permission
    from openagent.db.models.service_account import ServiceAccount


class RolePermission(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "role_permissions"

    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    permission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("permissions.id", ondelete="CASCADE"), nullable=False, index=True
    )

    role: Mapped["Role"] = relationship(back_populates="role_permissions")
    permission: Mapped["Permission"] = relationship(back_populates="role_permissions")

    __table_args__ = (
        UniqueConstraint("role_id", "permission_id", name="uq_role_permission"),
        Index("ix_role_permissions_role_id", "role_id"),
        Index("ix_role_permissions_permission_id", "permission_id"),
    )


class ServiceAccountPermission(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "service_account_permissions"

    service_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("service_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    permission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("permissions.id", ondelete="CASCADE"), nullable=False, index=True
    )

    service_account: Mapped["ServiceAccount"] = relationship(back_populates="account_permissions")
    permission: Mapped["Permission"] = relationship(back_populates="service_account_permissions")

    __table_args__ = (
        UniqueConstraint("service_account_id", "permission_id", name="uq_service_account_permission"),
        Index("ix_service_account_permissions_service_account_id", "service_account_id"),
        Index("ix_service_account_permissions_permission_id", "permission_id"),
    )