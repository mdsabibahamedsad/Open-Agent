from typing import Optional, List
from uuid import UUID
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.db.repositories.base import BaseRepository
from openagent.db.models.agent import Agent, AgentVersion, AgentStatus, AgentType


class AgentRepository(BaseRepository[Agent]):
    def __init__(self, session: AsyncSession):
        super().__init__(Agent, session)

    async def get_by_slug(self, organization_id: UUID, slug: str) -> Optional[Agent]:
        result = await self.session.execute(
            select(Agent).where(
                Agent.organization_id == organization_id,
                Agent.slug == slug
            )
        )
        return result.scalar_one_or_none()

    async def list_by_status(self, organization_id: UUID, status: AgentStatus, limit: int = 20, offset: int = 0) -> List[Agent]:
        result = await self.session.execute(
            select(Agent)
            .where(Agent.organization_id == organization_id, Agent.status == status)
            .order_by(Agent.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def list_by_type(self, organization_id: UUID, agent_type: AgentType, limit: int = 20, offset: int = 0) -> List[Agent]:
        result = await self.session.execute(
            select(Agent)
            .where(Agent.organization_id == organization_id, Agent.agent_type == agent_type)
            .order_by(Agent.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())


class AgentVersionRepository(BaseRepository[AgentVersion]):
    def __init__(self, session: AsyncSession):
        super().__init__(AgentVersion, session)

    async def get_by_agent_and_version(self, agent_id: UUID, version: str) -> Optional[AgentVersion]:
        result = await self.session.execute(
            select(AgentVersion).where(
                AgentVersion.agent_id == agent_id,
                AgentVersion.version == version
            )
        )
        return result.scalar_one_or_none()

    async def list_by_agent(self, agent_id: UUID, limit: int = 20, offset: int = 0) -> List[AgentVersion]:
        result = await self.session.execute(
            select(AgentVersion)
            .where(AgentVersion.agent_id == agent_id)
            .order_by(AgentVersion.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def get_latest_version(self, agent_id: UUID) -> Optional[AgentVersion]:
        result = await self.session.execute(
            select(AgentVersion)
            .where(AgentVersion.agent_id == agent_id)
            .order_by(AgentVersion.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()