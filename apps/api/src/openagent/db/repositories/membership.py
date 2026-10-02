from typing import Optional, List
from uuid import UUID
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.db.repositories.base import BaseRepository
from openagent.db.models.membership import Membership, MembershipRole, MembershipStatus


class MembershipRepository(BaseRepository[Membership]):
    def __init__(self, session: AsyncSession):
        super().__init__(Membership, session)

    async def get_by_user_and_org(self, user_id: UUID, organization_id: UUID) -> Optional[Membership]:
        result = await self.session.execute(
            select(Membership).where(
                Membership.user_id == user_id,
                Membership.organization_id == organization_id
            )
        )
        return result.scalar_one_or_none()

    async def list_by_user(self, user_id: UUID, limit: int = 20, offset: int = 0) -> List[Membership]:
        result = await self.session.execute(
            select(Membership)
            .where(Membership.user_id == user_id)
            .order_by(Membership.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def list_by_organization(self, organization_id: UUID, limit: int = 20, offset: int = 0) -> List[Membership]:
        result = await self.session.execute(
            select(Membership)
            .where(Membership.organization_id == organization_id)
            .order_by(Membership.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def list_by_role(self, organization_id: UUID, role: MembershipRole, limit: int = 20, offset: int = 0) -> List[Membership]:
        result = await self.session.execute(
            select(Membership)
            .where(Membership.organization_id == organization_id, Membership.role == role)
            .order_by(Membership.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())