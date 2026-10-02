from typing import Optional, List
from uuid import UUID
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.db.repositories.base import BaseRepository
from openagent.db.models.credential import Credential, CredentialType, CredentialStatus
from openagent.db.models.integration import Integration, IntegrationProvider, IntegrationStatus
from openagent.db.models.mcp import MCPServer, MCPTransport, MCPServerStatus


class CredentialRepository(BaseRepository[Credential]):
    def __init__(self, session: AsyncSession):
        super().__init__(Credential, session)

    async def list_by_provider(self, organization_id: UUID, provider: str, limit: int = 20, offset: int = 0) -> List[Credential]:
        result = await self.session.execute(
            select(Credential)
            .where(Credential.organization_id == organization_id, Credential.provider == provider)
            .order_by(Credential.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def list_by_type(self, organization_id: UUID, credential_type: CredentialType, limit: int = 20, offset: int = 0) -> List[Credential]:
        result = await self.session.execute(
            select(Credential)
            .where(Credential.organization_id == organization_id, Credential.credential_type == credential_type)
            .order_by(Credential.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def list_expiring(self, organization_id: UUID, days: int = 30) -> List[Credential]:
        from datetime import datetime, timezone, timedelta
        threshold = datetime.now(timezone.utc) + timedelta(days=days)
        result = await self.session.execute(
            select(Credential)
            .where(
                Credential.organization_id == organization_id,
                Credential.expires_at.is_not(None),
                Credential.expires_at <= threshold,
                Credential.status == CredentialStatus.ACTIVE
            )
            .order_by(Credential.expires_at.asc())
        )
        return list(result.scalars().all())


class IntegrationRepository(BaseRepository[Integration]):
    def __init__(self, session: AsyncSession):
        super().__init__(Integration, session)

    async def list_by_provider(self, organization_id: UUID, provider: IntegrationProvider, limit: int = 20, offset: int = 0) -> List[Integration]:
        result = await self.session.execute(
            select(Integration)
            .where(Integration.organization_id == organization_id, Integration.provider == provider)
            .order_by(Integration.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def list_by_credential(self, credential_id: UUID) -> List[Integration]:
        result = await self.session.execute(
            select(Integration).where(Integration.credential_id == credential_id)
        )
        return list(result.scalars().all())


class MCPServerRepository(BaseRepository[MCPServer]):
    def __init__(self, session: AsyncSession):
        super().__init__(MCPServer, session)

    async def list_by_transport(self, organization_id: UUID, transport: MCPTransport, limit: int = 20, offset: int = 0) -> List[MCPServer]:
        result = await self.session.execute(
            select(MCPServer)
            .where(MCPServer.organization_id == organization_id, MCPServer.transport == transport)
            .order_by(MCPServer.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def list_by_credential(self, credential_id: UUID) -> List[MCPServer]:
        result = await self.session.execute(
            select(MCPServer).where(MCPServer.credential_id == credential_id)
        )
        return list(result.scalars().all())