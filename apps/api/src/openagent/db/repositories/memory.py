"""Memory repository with advanced search capabilities including vector search."""

from typing import Optional, List, Dict, Any
from uuid import UUID
from datetime import datetime, timezone
from sqlalchemy import select, func, delete, and_, or_, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from openagent.db.repositories.base import BaseRepository
from openagent.db.models.memory import (
    Memory, MemoryType, MemoryScope, MemoryVisibility, MemoryStatus,
    MemoryEmbeddingStatus, MemorySourceType, MemoryVersion,
    MemoryAccessLog, MemoryEmbedding, MemoryLink, MemoryLink,
    MemoryConflict, MemoryConsolidationJob, MemoryPolicy, MemoryPolicy,
)
from openagent.db.models.conversation import Conversation, Message, ConversationStatus, MessageRole


class MemoryRepository(BaseRepository[Memory]):
    def __init__(self, session: AsyncSession):
        super().__init__(Memory, session)

    async def list_by_user(self, organization_id: UUID, user_id: UUID, limit: int = 20, offset: int = 0) -> List[Memory]:
        result = await self.session.execute(
            select(Memory)
            .where(Memory.organization_id == organization_id, Memory.user_id == user_id)
            .order_by(Memory.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def list_by_agent(self, organization_id: UUID, agent_id: UUID, limit: int = 20, offset: int = 0) -> List[Memory]:
        result = await self.session.execute(
            select(Memory)
            .where(Memory.organization_id == organization_id, Memory.agent_id == agent_id)
            .order_by(Memory.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def list_by_type(self, organization_id: UUID, memory_type: MemoryType, limit: int = 20, offset: int = 0) -> List[Memory]:
        result = await self.session.execute(
            select(Memory)
            .where(Memory.organization_id == organization_id, Memory.memory_type == memory_type)
            .order_by(Memory.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def list_by_scope(self, organization_id: UUID, scope: MemoryScope, limit: int = 20, offset: int = 0) -> List[Memory]:
        result = await self.session.execute(
            select(Memory)
            .where(Memory.organization_id == organization_id, Memory.scope == scope)
            .order_by(Memory.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def list_by_visibility(self, organization_id: UUID, visibility: MemoryVisibility, limit: int = 20, offset: int = 0) -> List[Memory]:
        result = await self.session.execute(
            select(Memory)
            .where(Memory.organization_id == organization_id, Memory.visibility == visibility)
            .order_by(Memory.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def list_by_status(self, organization_id: UUID, status: MemoryStatus, limit: int = 20, offset: int = 0) -> List[Memory]:
        result = await self.session.execute(
            select(Memory)
            .where(Memory.organization_id == organization_id, Memory.status == status)
            .order_by(Memory.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def list_by_task(self, organization_id: UUID, task_id: UUID, limit: int = 20, offset: int = 0) -> List[Memory]:
        result = await self.session.execute(
            select(Memory)
            .where(Memory.organization_id == organization_id, Memory.task_id == task_id)
            .order_by(Memory.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def list_by_conversation(self, organization_id: UUID, conversation_id: UUID, limit: int = 20, offset: int = 0) -> List[Memory]:
        result = await self.session.execute(
            select(Memory)
            .where(Memory.organization_id == organization_id, Memory.conversation_id == conversation_id)
            .order_by(Memory.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def list_by_agent_run(self, organization_id: UUID, agent_run_id: UUID, limit: int = 20, offset: int = 0) -> List[Memory]:
        result = await self.session.execute(
            select(Memory)
            .where(Memory.organization_id == organization_id, Memory.agent_run_id == agent_run_id)
            .order_by(Memory.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def list_by_orchestration_run(self, organization_id: UUID, orchestration_run_id: UUID, limit: int = 20, offset: int = 0) -> List[Memory]:
        result = await self.session.execute(
            select(Memory)
            .where(Memory.organization_id == organization_id, Memory.orchestration_run_id == orchestration_run_id)
            .order_by(Memory.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def list_by_team(self, organization_id: UUID, team_id: UUID, limit: int = 20, offset: int = 0) -> List[Memory]:
        result = await self.session.execute(
            select(Memory)
            .where(Memory.organization_id == organization_id, Memory.team_id == team_id)
            .order_by(Memory.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def list_by_source(self, organization_id: UUID, source_type: str, source_id: str, limit: int = 20, offset: int = 0) -> List[Memory]:
        result = await self.session.execute(
            select(Memory)
            .where(Memory.organization_id == organization_id, Memory.source_type == source_type, Memory.source_id == source_id)
            .order_by(Memory.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def search_by_content(self, organization_id: UUID, query: str, limit: int = 20, offset: int = 0) -> List[Memory]:
        """Full-text search on memory content using PostgreSQL's text search."""
        result = await self.session.execute(
            select(Memory)
            .where(
                Memory.organization_id == organization_id,
                Memory.status == "active",
                Memory.deleted_at.is_(None),
                Memory.content.ilike(f"%{query}%")
            )
            .order_by(Memory.importance.desc(), Memory.confidence.desc(), Memory.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def search_by_tags(self, organization_id: UUID, tags: List[str], match_all: bool = False, limit: int = 20, offset: int = 0) -> List[Memory]:
        """Search memories by tags."""
        if not tags:
            return []
        
        if match_all:
            # All tags must be present
            query = select(Memory).where(
                Memory.organization_id == organization_id,
                Memory.status == "active",
                Memory.deleted_at.is_(None),
            )
            for tag in tags:
                query = query.where(Memory.tags.contains([tag]))
        else:
            # Any tag matches
            query = select(Memory).where(
                Memory.organization_id == organization_id,
                Memory.status == "active",
                Memory.deleted_at.is_(None),
                Memory.tags.overlap(tags)
            )
        
        query = query.order_by(Memory.importance.desc(), Memory.confidence.desc(), Memory.created_at.desc()).limit(limit).offset(offset)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def vector_search(
        self, 
        organization_id: UUID, 
        query_embedding: List[float], 
        limit: int = 10, 
        offset: int = 0,
        similarity_threshold: float = 0.7,
        scope: Optional[str] = None,
        memory_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Vector similarity search using pgvector.
        Requires pgvector extension and the embedding index to be created.
        """
        # Build the similarity query using pgvector's cosine similarity
        # This requires the pgvector extension and the embedding index
        query = text("""
            SELECT m.*, 
                   1 - (m.embedding <=> :query_embedding) AS similarity
            FROM memories m
            WHERE m.organization_id = :org_id
              AND m.status = 'active'
              AND m.deleted_at IS NULL
              AND m.embedding IS NOT NULL
              AND m.embedding_status = 'ready'
        """)
        
        params = {"org_id": str(organization_id), "query_embedding": query_embedding}
        
        if scope:
            query += " AND m.scope = :scope"
            params["scope"] = scope
        if memory_type:
            query += " AND m.memory_type = :mem_type"
            params["mem_type"] = memory_type
        
        query += """
            AND (1 - (m.embedding <=> :query_embedding)) >= :threshold
            ORDER BY similarity DESC
            LIMIT :limit OFFSET :offset
        """
        
        params["threshold"] = similarity_threshold
        params["limit"] = limit
        params["offset"] = offset
        
        result = await self.session.execute(query, params)
        return [dict(row._mapping) for row in result]

    async def hybrid_search(
        self,
        organization_id: UUID,
        query: str,
        query_embedding: Optional[List[float]] = None,
        limit: int = 10,
        offset: int = 0,
        scope: Optional[str] = None,
        memory_type: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Hybrid search combining keyword and vector search.
        """
        # Build the query dynamically
        conditions = [
            "m.organization_id = :org_id",
            "m.status = 'active'",
            "m.deleted_at IS NULL"
        ]
        params = {"org_id": str(organization_id), "limit": limit, "offset": offset}
        
        # Add keyword search
        if query:
            conditions.append("m.content ILIKE :query")
            params["query"] = f"%{query}%"
        
        # Add scope filter
        if scope:
            conditions.append("m.scope = :scope")
            params["scope"] = scope
        
        # Add memory type filter
        if memory_type:
            conditions.append("m.memory_type = :mem_type")
            params["mem_type"] = memory_type
        
        # Add tags filter
        if tags:
            conditions.append("m.tags @> :tags")
            params["tags"] = tags
        
        # Build the query
        select_cols = "m.*, 1.0 as text_score"
        order_by = "m.importance DESC, m.confidence DESC, m.created_at DESC"
        
        if query_embedding is not None:
            select_cols += ", 1 - (m.embedding <=> :query_embedding) AS vector_score"
            params["query_embedding"] = query_embedding
            order_by = "COALESCE(vector_score, 0) * 0.7 + text_score * 0.3 DESC, m.importance DESC"
        
        where_clause = " AND ".join(conditions)
        query = f"""
            SELECT {select_cols}
            FROM memories m
            WHERE {where_clause}
            ORDER BY {order_by}
            LIMIT :limit OFFSET :offset
        """
        
        result = await self.session.execute(text(query), params)
        return [dict(row._mapping) for row in result]

    async def delete_expired(self) -> int:
        now = datetime.now(timezone.utc)
        result = await self.session.execute(
            delete(Memory).where(Memory.expires_at.is_not(None), Memory.expires_at < now)
        )
        return result.rowcount

    async def get_pending_embeddings(self, organization_id: UUID, limit: int = 100) -> List[Memory]:
        """Get memories that need embedding generation."""
        result = await self.session.execute(
            select(Memory)
            .where(
                Memory.organization_id == organization_id,
                Memory.embedding_status == "pending",
                Memory.status == "active",
                Memory.deleted_at.is_(None),
            )
            .order_by(Memory.created_at.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def update_embedding(self, memory_id: UUID, embedding: List[float], model: str, dimensions: int) -> bool:
        result = await self.session.execute(
            select(Memory).where(Memory.id == memory_id)
        )
        memory = result.scalar_one_or_none()
        if not memory:
            return False
        
        memory.embedding = embedding
        memory.embedding_status = "ready"
        memory.embedding_model = model
        memory.embedding_dimensions = len(embedding)
        memory.embedded_at = datetime.now(timezone.utc)
        memory.embedding_error = None
        memory.embedding_retries = 0
        await self.session.flush()
        return True

    async def mark_embedding_failed(self, memory_id: UUID, error: str) -> bool:
        result = await self.session.execute(
            select(Memory).where(Memory.id == memory_id)
        )
        memory = result.scalar_one_or_none()
        if not memory:
            return False
        
        memory.embedding_status = "failed"
        memory.embedding_error = error
        memory.embedding_retries += 1
        memory.last_embedding_attempt_at = datetime.now(timezone.utc)
        await self.session.flush()
        return True

    async def get_memory_with_versions(self, memory_id: UUID) -> Optional[Memory]:
        result = await self.session.execute(
            select(Memory).where(Memory.id == memory_id)
        )
        return result.scalar_one_or_none()

    async def create_version(self, memory: Memory, changed_by: Optional[UUID], change_reason: str) -> MemoryVersion:
        version = MemoryVersion(
            memory_id=memory.id,
            version=memory.version,
            content=memory.content,
            summary=memory.summary,
            structured_data=memory.structured_data,
            confidence=memory.confidence,
            importance=memory.importance,
            importance_factors=memory.importance_factors,
            tags=memory.tags,
            change_reason=change_reason,
            changed_by=changed_by,
            embedding=memory.embedding,
            embedding_model=memory.embedding_model,
            embedding_dimensions=memory.embedding_dimensions,
        )
        self.session.add(version)
        memory.version += 1
        await self.session.flush()
        return version

    async def log_access(self, log: MemoryAccessLog) -> MemoryAccessLog:
        self.session.add(log)
        await self.session.flush()
        return log

    async def increment_access_count(self, memory_id: UUID, accessed_by: Optional[UUID], agent_id: Optional[UUID]) -> bool:
        result = await self.session.execute(
            select(Memory).where(Memory.id == memory_id)
        )
        memory = result.scalar_one_or_none()
        if not memory:
            return False
        
        memory.access_count += 1
        memory.last_accessed_at = datetime.now(timezone.utc)
        memory.last_accessed_by = accessed_by
        await self.session.flush()
        return True


class MemoryVersionRepository(BaseRepository[MemoryVersion]):
    def __init__(self, session: AsyncSession):
        super().__init__(MemoryVersion, session)

    async def list_by_memory(self, memory_id: UUID, limit: int = 10, offset: int = 0) -> List[MemoryVersion]:
        result = await self.session.execute(
            select(MemoryVersion)
            .where(MemoryVersion.memory_id == memory_id)
            .order_by(MemoryVersion.version.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def get_version(self, memory_id: UUID, version: int) -> Optional[MemoryVersion]:
        result = await self.session.execute(
            select(MemoryVersion).where(
                MemoryVersion.memory_id == memory_id,
                MemoryVersion.version == version
            )
        )
        return result.scalar_one_or_none()


class MemoryAccessLogRepository(BaseRepository[MemoryAccessLog]):
    def __init__(self, session: AsyncSession):
        super().__init__(MemoryAccessLog, session)

    async def list_by_memory(self, memory_id: UUID, limit: int = 50, offset: int = 0) -> List[MemoryAccessLog]:
        result = await self.session.execute(
            select(MemoryAccessLog)
            .where(MemoryAccessLog.memory_id == memory_id)
            .order_by(MemoryAccessLog.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def list_by_organization(self, organization_id: UUID, limit: int = 100, offset: int = 0) -> List[MemoryAccessLog]:
        result = await self.session.execute(
            select(MemoryAccessLog)
            .where(MemoryAccessLog.organization_id == organization_id)
            .order_by(MemoryAccessLog.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())


class MemoryEmbeddingRepository(BaseRepository[MemoryEmbedding]):
    def __init__(self, session: AsyncSession):
        super().__init__(MemoryEmbedding, session)

    async def get_by_memory_and_model(self, memory_id: UUID, model: str) -> Optional[MemoryEmbedding]:
        result = await self.session.execute(
            select(MemoryEmbedding).where(
                MemoryEmbedding.memory_id == memory_id,
                MemoryEmbedding.model == model
            )
        )
        return result.scalar_one_or_none()

    async def list_by_memory(self, memory_id: UUID) -> List[MemoryEmbedding]:
        result = await self.session.execute(
            select(MemoryEmbedding).where(MemoryEmbedding.memory_id == memory_id)
        )
        return list(result.scalars().all())


class MemoryLinkRepository(BaseRepository[MemoryLink]):
    def __init__(self, session: AsyncSession):
        super().__init__(MemoryLink, session)

    async def list_outgoing(self, source_memory_id: UUID) -> List[MemoryLink]:
        result = await self.session.execute(
            select(MemoryLink).where(MemoryLink.source_memory_id == source_memory_id)
        )
        return list(result.scalars().all())

    async def list_incoming(self, target_memory_id: UUID) -> List[MemoryLink]:
        result = await self.session.execute(
            select(MemoryLink).where(MemoryLink.target_memory_id == target_memory_id)
        )
        return list(result.scalars().all())

    async def get_link(self, source_id: UUID, target_id: UUID, link_type: str) -> Optional[MemoryLink]:
        result = await self.session.execute(
            select(MemoryLink).where(
                MemoryLink.source_memory_id == source_id,
                MemoryLink.target_memory_id == target_id,
                MemoryLink.link_type == link_type
            )
        )
        return result.scalar_one_or_none()


class MemoryConflictRepository(BaseRepository[MemoryConflict]):
    def __init__(self, session: AsyncSession):
        super().__init__(MemoryConflict, session)

    async def list_open(self, organization_id: UUID, limit: int = 50, offset: int = 0) -> List[MemoryConflict]:
        result = await self.session.execute(
            select(MemoryConflict)
            .where(MemoryConflict.organization_id == organization_id, MemoryConflict.status == "open")
            .order_by(MemoryConflict.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())


class MemoryConsolidationJobRepository(BaseRepository[MemoryConsolidationJob]):
    def __init__(self, session: AsyncSession):
        super().__init__(MemoryConsolidationJob, session)

    async def list_by_organization(self, organization_id: UUID, limit: int = 50, offset: int = 0) -> List[MemoryConsolidationJob]:
        result = await self.session.execute(
            select(MemoryConsolidationJob)
            .where(MemoryConsolidationJob.organization_id == organization_id)
            .order_by(MemoryConsolidationJob.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())


class MemoryPolicyRepository(BaseRepository[MemoryPolicy]):
    def __init__(self, session: AsyncSession):
        super().__init__(MemoryPolicy, session)

    async def get_by_organization(self, organization_id: UUID) -> Optional[MemoryPolicy]:
        result = await self.session.execute(
            select(MemoryPolicy).where(MemoryPolicy.organization_id == organization_id)
        )
        return result.scalar_one_or_none()

    async def create_or_update(self, policy: MemoryPolicy) -> MemoryPolicy:
        existing = await self.get_by_organization(policy.organization_id)
        if existing:
            for key, value in policy.__dict__.items():
                if not key.startswith('_'):
                    setattr(existing, key, value)
            await self.session.flush()
            return existing
        return await self.create(**policy.__dict__)


class ConversationRepository(BaseRepository[Conversation]):
    def __init__(self, session: AsyncSession):
        super().__init__(Conversation, session)

    async def list_by_user(self, organization_id: UUID, user_id: UUID, limit: int = 20, offset: int = 0) -> List[Conversation]:
        result = await self.session.execute(
            select(Conversation)
            .where(Conversation.organization_id == organization_id, Conversation.user_id == user_id)
            .order_by(Conversation.updated_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def list_by_agent(self, organization_id: UUID, agent_id: UUID, limit: int = 20, offset: int = 0) -> List[Conversation]:
        result = await self.session.execute(
            select(Conversation)
            .where(Conversation.organization_id == organization_id, Conversation.agent_id == agent_id)
            .order_by(Conversation.updated_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())


class MessageRepository(BaseRepository[Message]):
    def __init__(self, session: AsyncSession):
        super().__init__(Message, session)

    async def list_by_conversation(self, conversation_id: UUID, limit: int = 50, offset: int = 0) -> List[Message]:
        result = await self.session.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def count_by_conversation(self, conversation_id: UUID) -> int:
        result = await self.session.execute(
            select(func.count(Message.id)).where(Message.conversation_id == conversation_id)
        )
        return result.scalar_one()

    async def get_last_messages(self, conversation_id: UUID, count: int = 10) -> List[Message]:
        result = await self.session.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc())
            .limit(count)
        )
        messages = list(result.scalars().all())
        return list(reversed(messages))