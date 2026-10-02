from typing import Optional, List
from uuid import UUID
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.db.repositories.base import BaseRepository
from openagent.db.models.user import User, UserStatus


class UserRepository(BaseRepository[User]):
    def __init__(self, session: AsyncSession):
        super().__init__(User, session)

    async def get_by_email(self, email: str) -> Optional[User]:
        result = await self.session.execute(
            select(User).where(User.email == email)
        )
        return result.scalar_one_or_none()

    async def get_by_email_with_org(self, email: str, organization_id: UUID) -> Optional[User]:
        from openagent.db.models.membership import Membership
        result = await self.session.execute(
            select(User)
            .join(Membership, Membership.user_id == User.id)
            .where(User.email == email, Membership.organization_id == organization_id)
        )
        return result.scalar_one_or_none()

    async def list_by_status(self, status: UserStatus, limit: int = 20, offset: int = 0) -> List[User]:
        result = await self.session.execute(
            select(User)
            .where(User.status == status)
            .order_by(User.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def count_by_status(self, status: UserStatus) -> int:
        result = await self.session.execute(
            select(func.count(User.id)).where(User.status == status)
        )
        return result.scalar_one()