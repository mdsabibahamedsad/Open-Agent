from typing import TypeVar, Generic, Optional, List, Type, Any
from uuid import UUID
from sqlalchemy import select, func, delete, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase

from openagent.db.models.base import Base, UUIDMixin, TimestampMixin


ModelType = TypeVar("ModelType", bound=Base)


class BaseRepository(Generic[ModelType]):
    def __init__(self, model: Type[ModelType], session: AsyncSession):
        self.model = model
        self.session = session

    async def create(self, **kwargs) -> ModelType:
        instance = self.model(**kwargs)
        self.session.add(instance)
        await self.session.flush()
        await self.session.refresh(instance)
        return instance

    async def get_by_id(self, id: UUID) -> Optional[ModelType]:
        result = await self.session.execute(
            select(self.model).where(self.model.id == id)
        )
        return result.scalar_one_or_none()

    async def get_by_id_with_org(self, id: UUID, organization_id: UUID) -> Optional[ModelType]:
        result = await self.session.execute(
            select(self.model).where(
                self.model.id == id,
                self.model.organization_id == organization_id
            )
        )
        return result.scalar_one_or_none()

    async def list(
        self,
        organization_id: Optional[UUID] = None,
        limit: int = 20,
        offset: int = 0,
        order_by: str = "created_at",
        order_desc: bool = True,
        **filters
    ) -> List[ModelType]:
        query = select(self.model)
        
        if organization_id and hasattr(self.model, 'organization_id'):
            query = query.where(self.model.organization_id == organization_id)
        
        for key, value in filters.items():
            if hasattr(self.model, key):
                query = query.where(getattr(self.model, key) == value)
        
        order_column = getattr(self.model, order_by, self.model.created_at)
        if order_desc:
            query = query.order_by(order_column.desc())
        else:
            query = query.order_by(order_column.asc())
        
        query = query.limit(limit).offset(offset)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def count(self, organization_id: Optional[UUID] = None, **filters) -> int:
        query = select(func.count(self.model.id))
        
        if organization_id and hasattr(self.model, 'organization_id'):
            query = query.where(self.model.organization_id == organization_id)
        
        for key, value in filters.items():
            if hasattr(self.model, key):
                query = query.where(getattr(self.model, key) == value)
        
        result = await self.session.execute(query)
        return result.scalar_one()

    async def update(self, id: UUID, **kwargs) -> Optional[ModelType]:
        instance = await self.get_by_id(id)
        if instance is None:
            return None
        
        for key, value in kwargs.items():
            if hasattr(instance, key):
                setattr(instance, key, value)
        
        await self.session.flush()
        await self.session.refresh(instance)
        return instance

    async def update_with_org(self, id: UUID, organization_id: UUID, **kwargs) -> Optional[ModelType]:
        instance = await self.get_by_id_with_org(id, organization_id)
        if instance is None:
            return None
        
        for key, value in kwargs.items():
            if hasattr(instance, key):
                setattr(instance, key, value)
        
        await self.session.flush()
        await self.session.refresh(instance)
        return instance

    async def delete(self, id: UUID) -> bool:
        instance = await self.get_by_id(id)
        if instance is None:
            return False
        
        await self.session.delete(instance)
        await self.session.flush()
        return True

    async def delete_with_org(self, id: UUID, organization_id: UUID) -> bool:
        instance = await self.get_by_id_with_org(id, organization_id)
        if instance is None:
            return False
        
        await self.session.delete(instance)
        await self.session.flush()
        return True

    async def soft_delete(self, id: UUID) -> Optional[ModelType]:
        if not hasattr(self.model, 'deleted_at'):
            return await self.delete(id)
        
        from datetime import datetime, timezone
        instance = await self.get_by_id(id)
        if instance is None:
            return None
        
        instance.deleted_at = datetime.now(timezone.utc)
        await self.session.flush()
        await self.session.refresh(instance)
        return instance

    async def soft_delete_with_org(self, id: UUID, organization_id: UUID) -> Optional[ModelType]:
        if not hasattr(self.model, 'deleted_at'):
            return await self.delete_with_org(id, organization_id)
        
        from datetime import datetime, timezone
        instance = await self.get_by_id_with_org(id, organization_id)
        if instance is None:
            return None
        
        instance.deleted_at = datetime.now(timezone.utc)
        await self.session.flush()
        await self.session.refresh(instance)
        return instance

    async def exists(self, id: UUID) -> bool:
        result = await self.session.execute(
            select(func.count(self.model.id)).where(self.model.id == id)
        )
        return result.scalar_one() > 0

    async def exists_with_org(self, id: UUID, organization_id: UUID) -> bool:
        result = await self.session.execute(
            select(func.count(self.model.id)).where(
                self.model.id == id,
                self.model.organization_id == organization_id
            )
        )
        return result.scalar_one() > 0