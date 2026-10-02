from typing import Optional, List
from uuid import UUID
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.db.repositories.base import BaseRepository
from openagent.db.models import Permission, PermissionResource, PermissionAction


class PermissionRepository(BaseRepository[Permission]):
    def __init__(self, session: AsyncSession):
        super().__init__(Permission, session)

    async def get_by_name(self, name: str) -> Optional[Permission]:
        result = await self.session.execute(
            select(Permission).where(Permission.name == name)
        )
        return result.scalar_one_or_none()

    async def get_by_resource_action(self, resource: PermissionResource, action: PermissionAction) -> Optional[Permission]:
        result = await self.session.execute(
            select(Permission).where(
                Permission.resource == resource,
                Permission.action == action
            )
        )
        return result.scalar_one_or_none()

    async def list_by_resource(self, resource: PermissionResource) -> List[Permission]:
        result = await self.session.execute(
            select(Permission).where(Permission.resource == resource).order_by(Permission.action)
        )
        return list(result.scalars().all())

    async def list_system_permissions(self) -> List[Permission]:
        result = await self.session.execute(
            select(Permission).where(Permission.is_system == True).order_by(Permission.resource, Permission.action)
        )
        return list(result.scalars().all())

    async def list_by_scope(self, scope: str) -> List[Permission]:
        result = await self.session.execute(
            select(Permission).where(Permission.scope == scope).order_by(Permission.resource, Permission.action)
        )
        return list(result.scalars().all())