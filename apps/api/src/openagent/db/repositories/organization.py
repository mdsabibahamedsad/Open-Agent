from typing import Optional, List
from uuid import UUID
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.db.repositories.base import BaseRepository
from openagent.db.models.organization import Organization, OrganizationStatus


class OrganizationRepository(BaseRepository[Organization]):
    def __init__(self, session: AsyncSession):
        super().__init__(Organization, session)

    async def get_by_slug(self, slug: str) -> Optional[Organization]:
        result = await self.session.execute(
            select(Organization).where(Organization.slug == slug)
        )
        return result.scalar_one_or_none()

    async def list_by_status(self, status: OrganizationStatus, limit: int = 20, offset: int = 0) -> List[Organization]:
        result = await self.session.execute(
            select(Organization)
            .where(Organization.status == status)
            .order_by(Organization.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())