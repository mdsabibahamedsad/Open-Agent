"""Repositories for management tables (thin wrappers over BaseRepository)."""

from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.db.models.management import (
    AgentAvailability,
    AgentCapacity,
    AgentCommitment,
    AgentContract,
    AgentDepartment,
    CollaborationRequest,
    DelegationRequest,
    DynamicTeam,
    DynamicTeamMembership,
    Escalation,
    HandoffPackage,
    ManagerDecision,
    ManagerProfile,
    PlanVersion,
    ReviewResult,
    TeamCharter,
)
from openagent.db.repositories.base import BaseRepository


class ManagerProfileRepository(BaseRepository[ManagerProfile]):
    def __init__(self, session: AsyncSession):
        super().__init__(ManagerProfile, session)

    async def get_by_agent(self, organization_id: UUID, agent_id: UUID) -> Optional[ManagerProfile]:
        result = await self.session.execute(
            select(ManagerProfile).where(
                ManagerProfile.organization_id == organization_id,
                ManagerProfile.agent_id == agent_id,
            )
        )
        return result.scalar_one_or_none()


class AgentContractRepository(BaseRepository[AgentContract]):
    def __init__(self, session: AsyncSession):
        super().__init__(AgentContract, session)

    async def get_by_idempotency_key(
        self, organization_id: UUID, key: str,
    ) -> Optional[AgentContract]:
        result = await self.session.execute(
            select(AgentContract).where(
                AgentContract.organization_id == organization_id,
                AgentContract.idempotency_key == key,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_task(self, task_id: UUID, limit: int = 500) -> List[AgentContract]:
        result = await self.session.execute(
            select(AgentContract).where(AgentContract.task_id == task_id)
            .order_by(AgentContract.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())


class DelegationRequestRepository(BaseRepository[DelegationRequest]):
    def __init__(self, session: AsyncSession):
        super().__init__(DelegationRequest, session)

    async def get_by_idempotency_key(
        self, organization_id: UUID, key: str,
    ) -> Optional[DelegationRequest]:
        result = await self.session.execute(
            select(DelegationRequest).where(
                DelegationRequest.organization_id == organization_id,
                DelegationRequest.idempotency_key == key,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_run(
        self, orchestration_run_id: UUID, limit: int = 200, offset: int = 0,
    ) -> List[DelegationRequest]:
        result = await self.session.execute(
            select(DelegationRequest)
            .where(DelegationRequest.orchestration_run_id == orchestration_run_id)
            .order_by(DelegationRequest.created_at.desc())
            .limit(limit).offset(offset)
        )
        return list(result.scalars().all())


class AgentCommitmentRepository(BaseRepository[AgentCommitment]):
    def __init__(self, session: AsyncSession):
        super().__init__(AgentCommitment, session)

    async def list_by_task(self, task_id: UUID, limit: int = 500) -> List[AgentCommitment]:
        result = await self.session.execute(
            select(AgentCommitment).where(AgentCommitment.task_id == task_id)
            .order_by(AgentCommitment.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())


class HandoffPackageRepository(BaseRepository[HandoffPackage]):
    def __init__(self, session: AsyncSession):
        super().__init__(HandoffPackage, session)

    async def get_by_idempotency_key(
        self, organization_id: UUID, key: str,
    ) -> Optional[HandoffPackage]:
        result = await self.session.execute(
            select(HandoffPackage).where(
                HandoffPackage.organization_id == organization_id,
                HandoffPackage.idempotency_key == key,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_run(
        self, orchestration_run_id: UUID, limit: int = 200, offset: int = 0,
    ) -> List[HandoffPackage]:
        result = await self.session.execute(
            select(HandoffPackage)
            .where(HandoffPackage.orchestration_run_id == orchestration_run_id)
            .order_by(HandoffPackage.created_at.desc())
            .limit(limit).offset(offset)
        )
        return list(result.scalars().all())


class ReviewResultRepository(BaseRepository[ReviewResult]):
    def __init__(self, session: AsyncSession):
        super().__init__(ReviewResult, session)

    async def list_by_task(self, task_id: UUID, limit: int = 500) -> List[ReviewResult]:
        result = await self.session.execute(
            select(ReviewResult).where(ReviewResult.task_id == task_id)
            .order_by(ReviewResult.revision_number.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def latest_for_task(self, task_id: UUID) -> Optional[ReviewResult]:
        rows = await self.list_by_task(task_id)
        return rows[0] if rows else None


class EscalationRepository(BaseRepository[Escalation]):
    def __init__(self, session: AsyncSession):
        super().__init__(Escalation, session)

    async def get_by_idempotency_key(
        self, organization_id: UUID, key: str,
    ) -> Optional[Escalation]:
        result = await self.session.execute(
            select(Escalation).where(
                Escalation.organization_id == organization_id,
                Escalation.idempotency_key == key,
            )
        )
        return result.scalar_one_or_none()

    async def list_open(
        self, organization_id: UUID, limit: int = 200, offset: int = 0,
    ) -> List[Escalation]:
        result = await self.session.execute(
            select(Escalation)
            .where(
                Escalation.organization_id == organization_id,
                Escalation.status.in_(["open", "acknowledged", "in_progress", "escalated"]),
            )
            .order_by(Escalation.created_at.desc())
            .limit(limit).offset(offset)
        )
        return list(result.scalars().all())


class AgentDepartmentRepository(BaseRepository[AgentDepartment]):
    def __init__(self, session: AsyncSession):
        super().__init__(AgentDepartment, session)

    async def get_by_slug(self, organization_id: UUID, slug: str) -> Optional[AgentDepartment]:
        result = await self.session.execute(
            select(AgentDepartment).where(
                AgentDepartment.organization_id == organization_id,
                AgentDepartment.slug == slug,
            )
        )
        return result.scalar_one_or_none()


class DynamicTeamRepository(BaseRepository[DynamicTeam]):
    def __init__(self, session: AsyncSession):
        super().__init__(DynamicTeam, session)

    async def get_by_idempotency_key(
        self, organization_id: UUID, key: str,
    ) -> Optional[DynamicTeam]:
        result = await self.session.execute(
            select(DynamicTeam).where(
                DynamicTeam.organization_id == organization_id,
                DynamicTeam.idempotency_key == key,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_run(self, orchestration_run_id: UUID, limit: int = 500) -> List[DynamicTeam]:
        result = await self.session.execute(
            select(DynamicTeam).where(DynamicTeam.orchestration_run_id == orchestration_run_id)
            .order_by(DynamicTeam.created_at.asc())
            .limit(limit)
        )
        return list(result.scalars().all())


class TeamCharterRepository(BaseRepository[TeamCharter]):
    def __init__(self, session: AsyncSession):
        super().__init__(TeamCharter, session)

    async def get_by_team(self, team_id: UUID) -> Optional[TeamCharter]:
        result = await self.session.execute(
            select(TeamCharter).where(TeamCharter.team_id == team_id)
        )
        return result.scalar_one_or_none()


class DynamicTeamMembershipRepository(BaseRepository[DynamicTeamMembership]):
    def __init__(self, session: AsyncSession):
        super().__init__(DynamicTeamMembership, session)

    async def list_by_team(self, team_id: UUID, limit: int = 500) -> List[DynamicTeamMembership]:
        result = await self.session.execute(
            select(DynamicTeamMembership).where(DynamicTeamMembership.team_id == team_id)
            .order_by(DynamicTeamMembership.created_at.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_by_agent(
        self, organization_id: UUID, agent_id: UUID, limit: int = 500,
    ) -> List[DynamicTeamMembership]:
        result = await self.session.execute(
            select(DynamicTeamMembership).where(
                DynamicTeamMembership.organization_id == organization_id,
                DynamicTeamMembership.agent_id == agent_id,
                DynamicTeamMembership.status == "active",
            ).limit(limit)
        )
        return list(result.scalars().all())


class AgentAvailabilityRepository(BaseRepository[AgentAvailability]):
    def __init__(self, session: AsyncSession):
        super().__init__(AgentAvailability, session)

    async def get_by_agent(self, agent_id: UUID) -> Optional[AgentAvailability]:
        result = await self.session.execute(
            select(AgentAvailability).where(AgentAvailability.agent_id == agent_id)
        )
        return result.scalar_one_or_none()


class AgentCapacityRepository(BaseRepository[AgentCapacity]):
    def __init__(self, session: AsyncSession):
        super().__init__(AgentCapacity, session)

    async def get_by_agent(self, agent_id: UUID) -> Optional[AgentCapacity]:
        result = await self.session.execute(
            select(AgentCapacity).where(AgentCapacity.agent_id == agent_id)
        )
        return result.scalar_one_or_none()


class PlanVersionRepository(BaseRepository[PlanVersion]):
    def __init__(self, session: AsyncSession):
        super().__init__(PlanVersion, session)

    async def list_by_run(self, orchestration_run_id: UUID, limit: int = 500) -> List[PlanVersion]:
        result = await self.session.execute(
            select(PlanVersion).where(PlanVersion.orchestration_run_id == orchestration_run_id)
            .order_by(PlanVersion.version.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def latest_version(self, orchestration_run_id: UUID) -> int:
        rows = await self.list_by_run(orchestration_run_id)
        return max((r.version for r in rows), default=0)


class CollaborationRequestRepository(BaseRepository[CollaborationRequest]):
    def __init__(self, session: AsyncSession):
        super().__init__(CollaborationRequest, session)

    async def list_by_run(
        self, orchestration_run_id: UUID, limit: int = 200,
    ) -> List[CollaborationRequest]:
        result = await self.session.execute(
            select(CollaborationRequest)
            .where(CollaborationRequest.orchestration_run_id == orchestration_run_id)
            .order_by(CollaborationRequest.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())


class ManagerDecisionRepository(BaseRepository[ManagerDecision]):
    def __init__(self, session: AsyncSession):
        super().__init__(ManagerDecision, session)

    async def list_by_run(
        self, orchestration_run_id: UUID, limit: int = 200,
    ) -> List[ManagerDecision]:
        result = await self.session.execute(
            select(ManagerDecision)
            .where(ManagerDecision.orchestration_run_id == orchestration_run_id)
            .order_by(ManagerDecision.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
