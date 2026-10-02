from typing import Optional, List
from uuid import UUID
from datetime import datetime, timezone
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.db.repositories.base import BaseRepository
from openagent.db.models.approval import Approval, ApprovalType, ApprovalStatus
from openagent.db.models.evaluation import Evaluation, EvaluatorType, EvaluationStatus
from openagent.db.models.audit_log import AuditLog


class ApprovalRepository(BaseRepository[Approval]):
    def __init__(self, session: AsyncSession):
        super().__init__(Approval, session)

    async def list_pending(self, organization_id: UUID, limit: int = 20, offset: int = 0) -> List[Approval]:
        result = await self.session.execute(
            select(Approval)
            .where(Approval.organization_id == organization_id, Approval.status == ApprovalStatus.PENDING)
            .order_by(Approval.created_at.asc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def list_by_run(self, run_id: UUID) -> List[Approval]:
        result = await self.session.execute(
            select(Approval).where(Approval.run_id == run_id).order_by(Approval.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_by_workflow_execution(self, workflow_execution_id: UUID) -> List[Approval]:
        result = await self.session.execute(
            select(Approval).where(Approval.workflow_execution_id == workflow_execution_id).order_by(Approval.created_at.desc())
        )
        return list(result.scalars().all())

    async def approve(self, approval_id: UUID, approved_by: UUID, decision: dict) -> Optional[Approval]:
        """Legacy entry point — now delegates to ApprovalEngine (MP19).

        Direct status writes are forbidden: the engine enforces tenant
        isolation, self-approval protection, quorum, and audit events.
        """
        from openagent.approvals.engine import ApprovalEngine, ApprovalError

        result = await self.session.execute(
            select(Approval).where(Approval.id == approval_id)
        )
        approval = result.scalar_one_or_none()
        if approval is None:
            return None
        engine = ApprovalEngine(self.session)
        try:
            reason = (decision or {}).get("reason", "") if isinstance(decision, dict) else ""
            return await engine.approve(
                approval_id, organization_id=approval.organization_id,
                approver_id=approved_by, reason=reason)
        except ApprovalError:
            return None

    async def reject(self, approval_id: UUID, approved_by: UUID, decision: dict) -> Optional[Approval]:
        """Legacy entry point — now delegates to ApprovalEngine (MP19)."""
        from openagent.approvals.engine import ApprovalEngine, ApprovalError

        result = await self.session.execute(
            select(Approval).where(Approval.id == approval_id)
        )
        approval = result.scalar_one_or_none()
        if approval is None:
            return None
        engine = ApprovalEngine(self.session)
        try:
            reason = (decision or {}).get("reason", "") if isinstance(decision, dict) else ""
            return await engine.reject(
                approval_id, organization_id=approval.organization_id,
                rejecter_id=approved_by, reason=reason)
        except ApprovalError:
            return None

    async def expire_pending(self) -> int:
        now = datetime.now(timezone.utc)
        result = await self.session.execute(
            update(Approval)
            .where(Approval.status == ApprovalStatus.PENDING, Approval.expires_at.is_not(None), Approval.expires_at < now)
            .values(status=ApprovalStatus.EXPIRED, resolved_at=now)
        )
        return result.rowcount


class EvaluationRepository(BaseRepository[Evaluation]):
    def __init__(self, session: AsyncSession):
        super().__init__(Evaluation, session)

    async def list_by_run(self, run_id: UUID) -> List[Evaluation]:
        result = await self.session.execute(
            select(Evaluation).where(Evaluation.run_id == run_id).order_by(Evaluation.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_by_workflow_execution(self, workflow_execution_id: UUID) -> List[Evaluation]:
        result = await self.session.execute(
            select(Evaluation).where(Evaluation.workflow_execution_id == workflow_execution_id).order_by(Evaluation.created_at.desc())
        )
        return list(result.scalars().all())


class AuditLogRepository(BaseRepository[AuditLog]):
    def __init__(self, session: AsyncSession):
        super().__init__(AuditLog, session)

    async def log(
        self,
        organization_id: UUID,
        action: str,
        resource_type: str,
        actor_user_id: Optional[UUID] = None,
        resource_id: Optional[UUID] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        metadata: Optional[dict] = None
    ) -> AuditLog:
        return await self.create(
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            ip_address=ip_address,
            user_agent=user_agent,
            metadata=metadata or {}
        )

    async def list_by_resource(self, resource_type: str, resource_id: UUID, limit: int = 50, offset: int = 0) -> List[AuditLog]:
        result = await self.session.execute(
            select(AuditLog)
            .where(AuditLog.resource_type == resource_type, AuditLog.resource_id == resource_id)
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def list_by_actor(self, actor_user_id: UUID, limit: int = 50, offset: int = 0) -> List[AuditLog]:
        result = await self.session.execute(
            select(AuditLog)
            .where(AuditLog.actor_user_id == actor_user_id)
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def list_by_action(self, organization_id: UUID, action: str, limit: int = 50, offset: int = 0) -> List[AuditLog]:
        result = await self.session.execute(
            select(AuditLog)
            .where(AuditLog.organization_id == organization_id, AuditLog.action == action)
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())