from typing import Optional, List
from uuid import UUID
from datetime import datetime, timezone
from sqlalchemy import select, func, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.db.repositories.base import BaseRepository
from openagent.db.models import Session


class SessionRepository(BaseRepository[Session]):
    def __init__(self, session: AsyncSession):
        super().__init__(Session, session)

    async def get_by_token_hash(self, token_hash: str) -> Optional[Session]:
        result = await self.session.execute(
            select(Session).where(Session.token_hash == token_hash)
        )
        return result.scalar_one_or_none()

    async def list_by_user(self, user_id: UUID, limit: int = 20, offset: int = 0) -> List[Session]:
        result = await self.session.execute(
            select(Session)
            .where(Session.user_id == user_id)
            .order_by(Session.last_seen_at.desc().nullslast())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def list_active_by_user(self, user_id: UUID) -> List[Session]:
        now = datetime.now(timezone.utc)
        result = await self.session.execute(
            select(Session)
            .where(
                Session.user_id == user_id,
                Session.revoked_at.is_(None),
                Session.expires_at > now
            )
            .order_by(Session.last_seen_at.desc().nullslast())
        )
        return list(result.scalars().all())

    async def revoke_all_for_user(self, user_id: UUID, except_session_id: Optional[UUID] = None) -> int:
        now = datetime.now(timezone.utc)
        query = update(Session).where(
            Session.user_id == user_id,
            Session.revoked_at.is_(None),
        )
        if except_session_id:
            query = query.where(Session.id != except_session_id)
        query = query.values(revoked_at=now)
        result = await self.session.execute(query)
        return result.rowcount

    async def cleanup_expired(self) -> int:
        now = datetime.now(timezone.utc)
        result = await self.session.execute(
            delete(Session).where(Session.expires_at < now)
        )
        return result.rowcount