from typing import Optional, List
from uuid import UUID
from datetime import datetime, timezone
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from openagent.db.repositories.base import BaseRepository
from openagent.db.models import ServiceAccount, ServiceAccountStatus, ServiceAccountPermission
from openagent.core.security.tokens import create_token_pair


class ServiceAccountRepository(BaseRepository[ServiceAccount]):
    def __init__(self, session: AsyncSession):
        super().__init__(ServiceAccount, session)

    async def get_by_key_prefix(self, key_prefix: str) -> Optional[ServiceAccount]:
        result = await self.session.execute(
            select(ServiceAccount).where(ServiceAccount.key_prefix == key_prefix)
        )
        return result.scalar_one_or_none()

    async def get_by_key_hash(self, key_hash: str) -> Optional[ServiceAccount]:
        result = await self.session.execute(
            select(ServiceAccount).where(ServiceAccount.key_hash == key_hash)
        )
        return result.scalar_one_or_none()

    async def list_by_organization(
        self,
        organization_id: UUID,
        status: Optional[ServiceAccountStatus] = None,
        limit: int = 20,
        offset: int = 0
    ) -> List[ServiceAccount]:
        query = select(ServiceAccount).where(ServiceAccount.organization_id == organization_id)
        if status:
            query = query.where(ServiceAccount.status == status)
        query = query.order_by(ServiceAccount.created_at.desc()).limit(limit).offset(offset)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_with_permissions(self, account_id: UUID) -> Optional[ServiceAccount]:
        result = await self.session.execute(
            select(ServiceAccount)
            .options(selectinload(ServiceAccount.account_permissions).selectinload(ServiceAccountPermission.permission))
            .where(ServiceAccount.id == account_id)
        )
        return result.scalar_one_or_none()

    async def create_service_account(
        self,
        organization_id: UUID,
        name: str,
        description: Optional[str],
        created_by: UUID,
        permissions: List[UUID],
        expires_at: Optional[datetime] = None
    ) -> tuple[ServiceAccount, str]:
        """Create service account and return (account, raw_key)."""
        token, token_hash, _ = create_token_pair()
        key_prefix = f"sa_{token[:8]}"
        
        account = ServiceAccount(
            organization_id=organization_id,
            name=name,
            description=description,
            key_hash=token_hash,
            key_prefix=key_prefix,
            created_by=created_by,
            expires_at=expires_at,
        )
        self.session.add(account)
        await self.session.flush()
        
        # Add permissions
        for perm_id in permissions:
            sap = ServiceAccountPermission(service_account_id=account.id, permission_id=perm_id)
            self.session.add(sap)
        
        await self.session.flush()
        return account, token

    async def update_last_used(self, account_id: UUID) -> Optional[ServiceAccount]:
        now = datetime.now(timezone.utc)
        result = await self.session.execute(
            update(ServiceAccount)
            .where(ServiceAccount.id == account_id)
            .values(last_used_at=now)
            .returning(ServiceAccount)
        )
        return result.scalar_one_or_none()

    async def revoke(self, account_id: UUID) -> Optional[ServiceAccount]:
        now = datetime.now(timezone.utc)
        result = await self.session.execute(
            update(ServiceAccount)
            .where(ServiceAccount.id == account_id)
            .values(status=ServiceAccountStatus.REVOKED, deleted_at=now)
            .returning(ServiceAccount)
        )
        return result.scalar_one_or_none()

    async def rotate_key(self, account_id: UUID) -> tuple[ServiceAccount, str]:
        """Rotate service account key and return (account, new_raw_key)."""
        token, token_hash, _ = create_token_pair()
        key_prefix = f"sa_{token[:8]}"
        
        result = await self.session.execute(
            update(ServiceAccount)
            .where(ServiceAccount.id == account_id)
            .values(key_hash=token_hash, key_prefix=key_prefix, last_used_at=None)
            .returning(ServiceAccount)
        )
        account = result.scalar_one_or_none()
        return account, token

    async def set_permissions(self, account_id: UUID, permission_ids: List[UUID]) -> None:
        from sqlalchemy import delete
        # Remove existing permissions
        await self.session.execute(
            delete(ServiceAccountPermission).where(ServiceAccountPermission.service_account_id == account_id)
        )
        # Add new permissions
        for perm_id in permission_ids:
            sap = ServiceAccountPermission(service_account_id=account_id, permission_id=perm_id)
            self.session.add(sap)
        await self.session.flush()

    async def get_permissions(self, account_id: UUID) -> List[UUID]:
        result = await self.session.execute(
            select(ServiceAccountPermission.permission_id).where(
                ServiceAccountPermission.service_account_id == account_id
            )
        )
        return [row[0] for row in result.all()]

    async def expire_old_accounts(self) -> int:
        now = datetime.now(timezone.utc)
        result = await self.session.execute(
            update(ServiceAccount)
            .where(
                ServiceAccount.status == ServiceAccountStatus.ACTIVE,
                ServiceAccount.expires_at.is_not(None),
                ServiceAccount.expires_at < now
            )
            .values(status=ServiceAccountStatus.EXPIRED)
        )
        return result.rowcount