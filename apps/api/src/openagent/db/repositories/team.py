from typing import Optional, List
from uuid import UUID
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from openagent.db.repositories.base import BaseRepository
from openagent.db.models import Team, TeamMembership, TeamMembershipRole, User


class TeamRepository(BaseRepository[Team]):
    def __init__(self, session: AsyncSession):
        super().__init__(Team, session)

    async def get_by_slug(self, organization_id: UUID, slug: str) -> Optional[Team]:
        result = await self.session.execute(
            select(Team).where(
                Team.organization_id == organization_id,
                Team.slug == slug
            )
        )
        return result.scalar_one_or_none()

    async def list_by_organization(self, organization_id: UUID, limit: int = 20, offset: int = 0) -> List[Team]:
        result = await self.session.execute(
            select(Team)
            .where(Team.organization_id == organization_id)
            .order_by(Team.name)
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def get_with_memberships(self, team_id: UUID) -> Optional[Team]:
        result = await self.session.execute(
            select(Team)
            .options(selectinload(Team.memberships).selectinload(TeamMembership.user))
            .where(Team.id == team_id)
        )
        return result.scalar_one_or_none()

    async def get_member_count(self, team_id: UUID) -> int:
        result = await self.session.execute(
            select(func.count(TeamMembership.id)).where(TeamMembership.team_id == team_id)
        )
        return result.scalar_one()

    async def add_member(self, team_id: UUID, user_id: UUID, role: str = "member") -> TeamMembership:
        membership = TeamMembership(
            team_id=team_id,
            user_id=user_id,
            role=role
        )
        self.session.add(membership)
        await self.session.flush()
        return membership

    async def remove_member(self, team_id: UUID, user_id: UUID) -> bool:
        from sqlalchemy import delete
        result = await self.session.execute(
            delete(TeamMembership).where(
                TeamMembership.team_id == team_id,
                TeamMembership.user_id == user_id
            )
        )
        return result.rowcount > 0

    async def update_member_role(self, team_id: UUID, user_id: UUID, role: TeamMembershipRole) -> Optional[TeamMembership]:
        result = await self.session.execute(
            select(TeamMembership).where(
                TeamMembership.team_id == team_id,
                TeamMembership.user_id == user_id
            )
        )
        membership = result.scalar_one_or_none()
        if membership:
            membership.role = role
            await self.session.flush()
        return membership

    async def is_member(self, team_id: UUID, user_id: UUID) -> bool:
        result = await self.session.execute(
            select(func.count(TeamMembership.id)).where(
                TeamMembership.team_id == team_id,
                TeamMembership.user_id == user_id
            )
        )
        return result.scalar_one() > 0

    async def get_user_teams(self, user_id: UUID, organization_id: UUID) -> List[Team]:
        result = await self.session.execute(
            select(Team)
            .join(TeamMembership, TeamMembership.team_id == Team.id)
            .where(
                TeamMembership.user_id == user_id,
                Team.organization_id == organization_id
            )
            .order_by(Team.name)
        )
        return list(result.scalars().all())


class TeamMembershipRepository(BaseRepository[TeamMembership]):
    def __init__(self, session: AsyncSession):
        super().__init__(TeamMembership, session)

    async def list_by_team(self, team_id: UUID) -> List[TeamMembership]:
        result = await self.session.execute(
            select(TeamMembership)
            .where(TeamMembership.team_id == team_id)
            .order_by(TeamMembership.created_at)
        )
        return list(result.scalars().all())

    async def list_by_user(self, user_id: UUID) -> List[TeamMembership]:
        result = await self.session.execute(
            select(TeamMembership)
            .where(TeamMembership.user_id == user_id)
            .order_by(TeamMembership.created_at)
        )
        return list(result.scalars().all())

    async def get_by_team_user(self, team_id: UUID, user_id: UUID) -> Optional[TeamMembership]:
        result = await self.session.execute(
            select(TeamMembership).where(
                TeamMembership.team_id == team_id,
                TeamMembership.user_id == user_id
            )
        )
        return result.scalar_one_or_none()