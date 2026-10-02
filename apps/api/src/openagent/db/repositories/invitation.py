from typing import Optional, List
from uuid import UUID
from datetime import datetime, timezone
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.db.repositories.base import BaseRepository
from openagent.db.models import OrganizationInvitation, InvitationStatus, Role
from openagent.core.security.tokens import create_token_pair


class OrganizationInvitationRepository(BaseRepository[OrganizationInvitation]):
    def __init__(self, session: AsyncSession):
        super().__init__(OrganizationInvitation, session)

    async def get_by_token_hash(self, token_hash: str) -> Optional[OrganizationInvitation]:
        result = await self.session.execute(
            select(OrganizationInvitation).where(OrganizationInvitation.token_hash == token_hash)
        )
        return result.scalar_one_or_none()

    async def list_by_organization(
        self,
        organization_id: UUID,
        status: Optional[InvitationStatus] = None,
        limit: int = 20,
        offset: int = 0
    ) -> List[OrganizationInvitation]:
        query = select(OrganizationInvitation).where(OrganizationInvitation.organization_id == organization_id)
        if status:
            query = query.where(OrganizationInvitation.status == status)
        query = query.order_by(OrganizationInvitation.created_at.desc()).limit(limit).offset(offset)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_pending_by_email(self, organization_id: UUID, email: str) -> Optional[OrganizationInvitation]:
        result = await self.session.execute(
            select(OrganizationInvitation).where(
                OrganizationInvitation.organization_id == organization_id,
                OrganizationInvitation.email == email.lower(),
                OrganizationInvitation.status == InvitationStatus.PENDING
            )
        )
        return result.scalar_one_or_none()

    async def count_pending(self, organization_id: UUID) -> int:
        result = await self.session.execute(
            select(func.count(OrganizationInvitation.id)).where(
                OrganizationInvitation.organization_id == organization_id,
                OrganizationInvitation.status == InvitationStatus.PENDING
            )
        )
        return result.scalar_one()

    async def create_invitation(
        self,
        organization_id: UUID,
        email: str,
        role_id: UUID,
        invited_by: UUID,
        expires_in_hours: int = 168  # 7 days
    ) -> tuple[OrganizationInvitation, str]:
        """Create invitation and return (invitation, raw_token)."""
        token, token_hash, expires_at = create_token_pair()
        
        invitation = OrganizationInvitation(
            organization_id=organization_id,
            email=email.lower(),
            role_id=role_id,
            invited_by=invited_by,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        self.session.add(invitation)
        await self.session.flush()
        return invitation, token

    async def accept(self, invitation: OrganizationInvitation) -> OrganizationInvitation:
        invitation.status = InvitationStatus.ACCEPTED
        invitation.accepted_at = datetime.now(timezone.utc)
        await self.session.flush()
        return invitation

    async def decline(self, invitation: OrganizationInvitation) -> OrganizationInvitation:
        invitation.status = InvitationStatus.DECLINED
        await self.session.flush()
        return invitation

    async def revoke(self, invitation: OrganizationInvitation, revoked_by: UUID) -> OrganizationInvitation:
        invitation.status = InvitationStatus.REVOKED
        invitation.revoked_at = datetime.now(timezone.utc)
        invitation.revoked_by = revoked_by
        await self.session.flush()
        return invitation

    async def expire_old_invitations(self) -> int:
        """Mark expired invitations. Returns count of expired invitations."""
        now = datetime.now(timezone.utc)
        result = await self.session.execute(
            update(OrganizationInvitation)
            .where(
                OrganizationInvitation.status == InvitationStatus.PENDING,
                OrganizationInvitation.expires_at < now
            )
            .values(status=InvitationStatus.EXPIRED)
        )
        return result.rowcount

    async def resend_invitation(self, invitation: OrganizationInvitation, expires_in_hours: int = 168) -> tuple[OrganizationInvitation, str]:
        """Resend invitation with new token and extended expiration."""
        from openagent.core.security.tokens import create_token_pair
        token, token_hash, expires_at = create_token_pair()
        
        invitation.token_hash = token_hash
        invitation.expires_at = expires_at
        invitation.status = InvitationStatus.PENDING
        invitation.accepted_at = None
        invitation.revoked_at = None
        invitation.revoked_by = None
        
        await self.session.flush()
        return invitation, token