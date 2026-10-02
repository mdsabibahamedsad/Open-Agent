"""Agent discovery respecting tenant boundaries."""

from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.db.models import Agent, AgentStatus


async def discover_agents(
    db: AsyncSession,
    *,
    organization_id: UUID,
    capabilities: Optional[List[str]] = None,
    team_id: Optional[UUID] = None,
    include_global: bool = True,
    limit: int = 50,
) -> List[Agent]:
    """Discover agents visible to an organization.

    - Organization agents are always visible within the org.
    - Global/platform agents (organization_id IS NULL, if any) are optionally visible.
    - Never returns another organization's private agents.
    - team_id is reserved for team-scoped discovery (MP14).
    """
    _ = team_id
    query = select(Agent).where(Agent.status == AgentStatus.ACTIVE)
    org_clause = Agent.organization_id == organization_id
    if include_global:
        from sqlalchemy import or_

        query = query.where(or_(org_clause, Agent.organization_id.is_(None)))
    else:
        query = query.where(org_clause)
    query = query.order_by(Agent.updated_at.desc()).limit(limit)
    result = await db.execute(query)
    agents = list(result.scalars().all())
    if not capabilities:
        return agents
    wanted = {c.strip().lower() for c in capabilities}
    filtered: List[Agent] = []
    for agent in agents:
        offered = _agent_capabilities(agent)
        if wanted.issubset({c.lower() for c in offered}):
            filtered.append(agent)
    return filtered


def _agent_capabilities(agent: Agent) -> List[str]:
    meta = getattr(agent, "metadata", None) or {}
    if isinstance(meta, dict):
        caps = meta.get("capabilities") or meta.get("advertised_capabilities") or []
        if isinstance(caps, list):
            return [str(c) for c in caps]
    return []
