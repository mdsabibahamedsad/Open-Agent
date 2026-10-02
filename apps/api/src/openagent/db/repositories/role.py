from typing import Optional, List
from uuid import UUID
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from openagent.db.repositories.base import BaseRepository
from openagent.db.models import Role, RoleType, RolePermission, Permission


class RoleRepository(BaseRepository[Role]):
    def __init__(self, session: AsyncSession):
        super().__init__(Role, session)

    async def get_by_name(self, organization_id: Optional[UUID], name: str) -> Optional[Role]:
        query = select(Role).where(Role.name == name)
        if organization_id:
            query = query.where(Role.organization_id == organization_id)
        else:
            query = query.where(Role.organization_id.is_(None))
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def list_by_organization(self, organization_id: UUID, include_system: bool = True) -> List[Role]:
        query = select(Role).where(Role.organization_id == organization_id)
        if not include_system:
            query = query.where(Role.is_system == False)
        query = query.order_by(Role.priority.desc(), Role.name)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def list_system_roles(self) -> List[Role]:
        result = await self.session.execute(
            select(Role)
            .where(Role.is_system == True, Role.organization_id.is_(None))
            .order_by(Role.priority.desc())
        )
        return list(result.scalars().all())

    async def get_with_permissions(self, role_id: UUID) -> Optional[Role]:
        result = await self.session.execute(
            select(Role)
            .options(selectinload(Role.role_permissions).selectinload(RolePermission.permission))
            .where(Role.id == role_id)
        )
        return result.scalar_one_or_none()

    async def get_permissions(self, role_id: UUID) -> List[Permission]:
        result = await self.session.execute(
            select(Permission)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .where(RolePermission.role_id == role_id)
            .order_by(Permission.resource, Permission.action)
        )
        return list(result.scalars().all())

    async def add_permission(self, role_id: UUID, permission_id: UUID) -> RolePermission:
        from openagent.db.models import RolePermission
        rp = RolePermission(role_id=role_id, permission_id=permission_id)
        self.session.add(rp)
        await self.session.flush()
        return rp

    async def remove_permission(self, role_id: UUID, permission_id: UUID) -> bool:
        from openagent.db.models import RolePermission
        from sqlalchemy import delete
        result = await self.session.execute(
            delete(RolePermission).where(
                RolePermission.role_id == role_id,
                RolePermission.permission_id == permission_id
            )
        )
        return result.rowcount > 0

    async def set_permissions(self, role_id: UUID, permission_ids: List[UUID]) -> None:
        from openagent.db.models import RolePermission
        from sqlalchemy import delete
        # Remove existing permissions
        await self.session.execute(
            delete(RolePermission).where(RolePermission.role_id == role_id)
        )
        # Add new permissions
        for perm_id in permission_ids:
            rp = RolePermission(role_id=role_id, permission_id=perm_id)
            self.session.add(rp)
        await self.session.flush()

    async def count_members(self, role_id: UUID) -> int:
        from openagent.db.models import Membership
        from sqlalchemy import func
        result = await self.session.execute(
            select(func.count(Membership.id)).where(Membership.role_id == role_id)
        )
        return result.scalar_one()