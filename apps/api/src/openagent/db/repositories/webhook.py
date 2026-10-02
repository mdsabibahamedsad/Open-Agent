from typing import Optional, List
from uuid import UUID
from datetime import datetime, timezone
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.db.repositories.base import BaseRepository
from openagent.db.models.webhook import Webhook, WebhookStatus
from openagent.db.models.api_key import ApiKey


class WebhookRepository(BaseRepository[Webhook]):
    def __init__(self, session: AsyncSession):
        super().__init__(Webhook, session)

    async def list_active(self, organization_id: UUID, limit: int = 20, offset: int = 0) -> List[Webhook]:
        result = await self.session.execute(
            select(Webhook)
            .where(Webhook.organization_id == organization_id, Webhook.status == WebhookStatus.ACTIVE)
            .order_by(Webhook.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def get_by_event_type(self, organization_id: UUID, event_type: str) -> List[Webhook]:
        result = await self.session.execute(
            select(Webhook)
            .where(
                Webhook.organization_id == organization_id,
                Webhook.status == WebhookStatus.ACTIVE,
                Webhook.event_types.contains([event_type])
            )
        )
        return list(result.scalars().all())


class ApiKeyRepository(BaseRepository[ApiKey]):
    def __init__(self, session: AsyncSession):
        super().__init__(ApiKey, session)

    async def get_by_key_hash(self, key_hash: str) -> Optional[ApiKey]:
        result = await self.session.execute(
            select(ApiKey).where(ApiKey.key_hash == key_hash)
        )
        return result.scalar_one_or_none()

    async def get_by_prefix(self, key_prefix: str) -> Optional[ApiKey]:
        result = await self.session.execute(
            select(ApiKey).where(ApiKey.key_prefix == key_prefix)
        )
        return result.scalar_one_or_none()

    async def list_by_user(self, user_id: UUID, limit: int = 20, offset: int = 0) -> List[ApiKey]:
        result = await self.session.execute(
            select(ApiKey)
            .where(ApiKey.user_id == user_id)
            .order_by(ApiKey.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def list_by_organization(self, organization_id: UUID, limit: int = 20, offset: int = 0) -> List[ApiKey]:
        result = await self.session.execute(
            select(ApiKey)
            .where(ApiKey.organization_id == organization_id)
            .order_by(ApiKey.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def update_last_used(self, key_id: UUID) -> Optional[ApiKey]:
        now = datetime.now(timezone.utc)
        result = await self.session.execute(
            update(ApiKey)
            .where(ApiKey.id == key_id)
            .values(last_used_at=now)
            .returning(ApiKey)
        )
        return result.scalar_one_or_none()

    async def revoke(self, key_id: UUID) -> Optional[ApiKey]:
        now = datetime.now(timezone.utc)
        result = await self.session.execute(
            update(ApiKey)
            .where(ApiKey.id == key_id)
            .values(deleted_at=now)
            .returning(ApiKey)
        )
        return result.scalar_one_or_none()