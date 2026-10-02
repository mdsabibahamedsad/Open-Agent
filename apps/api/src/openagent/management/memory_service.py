"""Memory Service: Core memory management with write pipeline, retrieval, and lifecycle management."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
from uuid import UUID

import structlog
from sqlalchemy import select, func, delete, and_, or_, update, func as sql_func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from openagent.db.models import Agent, AuditLog
from openagent.db.models.memory import (
    Memory, MemoryType, MemoryScope, MemoryVisibility, MemoryStatus,
    MemoryEmbeddingStatus, MemorySourceType, MemoryVersion,
    MemoryAccessLog, MemoryEmbedding, MemoryLink, MemoryLink,
    MemoryConflict, MemoryConsolidationJob, MemoryPolicy, MemoryLink,
    MemoryConflict, MemoryConsolidationJob, MemoryPolicy, MemoryLink,
)
from openagent.db.models.conversation import Conversation, Message, ConversationStatus, MessageRole
from openagent.db.repositories.memory import (
    MemoryRepository, MemoryVersionRepository, MemoryAccessLogRepository,
    MemoryEmbeddingRepository, MemoryLinkRepository, MemoryConflictRepository,
    MemoryConsolidationJobRepository, MemoryPolicyRepository,
)
from openagent.db.repositories.memory import ConversationRepository, MessageRepository
from openagent.db.repositories.agent_run import AgentRunRepository
from openagent.db.repositories.agent import AgentRepository
from openagent.db.repositories.task import TaskRepository
from openagent.db.repositories.team import TeamRepository
from openagent.db.repositories.orchestration import OrchestrationRunRepository
from openagent.management.providers import MemoryProvider, EmbeddingProvider
from openagent.orchestration.events import record_metric
from openagent.orchestration.security import sanitize_dict, contains_secret_key
from openagent.orchestration.events import publish_event
from openagent.core.config import get_settings

logger = structlog.get_logger("memory.service")

# Regex patterns for extraction
FACT_PATTERN = re.compile(r'\b(?:is|are|equals?|was|were|has|have|had)\s+([^.!?]+)', re.IGNORECASE)
PREFERENCE_PATTERN = re.compile(r'\b(?:prefer|like|dislike|favorite|favourite)\s+([^.!?]+)', re.IGNORECASE)
DECISION_PATTERN = re.compile(r'\b(?:decide|decided|choose|chose|agree|agreed)\s+(?:to\s+)?([^.!?]+)', re.IGNORECASE)
PROCEDURE_PATTERN = re.compile(r'\b(?:step|first|then|next|finally)\s+([^.!?]+)', re.IGNORECASE)
ENTITY_PATTERN = re.compile(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b')

# Secret patterns for redaction
SECRET_PATTERNS = [
    re.compile(r'(?i)(api[_-]?key|apikey)\s*[:=]\s*["\']?([^\s"\']+)', re.IGNORECASE),
    re.compile(r'(?i)(password|passwd|secret|token|api_key|private_key|access_token|refresh_token)\s*[:=]\s*["\']?([^\s"\']+)', re.IGNORECASE),
    re.compile(r'(?i)(authorization|bearer)\s+([^\s]+)', re.IGNORECASE),
]


class MemoryExtractionError(Exception):
    pass


class MemoryValidationError(Exception):
    pass


class MemoryWritePipeline:
    """Pipeline for processing memory candidates through extraction, validation, and deduplication."""

    def __init__(
        self,
        embedding_provider: Optional[EmbeddingProvider] = None,
        similarity_threshold: float = 0.85,
    ):
        self.embedding_provider = embedding_provider
        self.similarity_threshold = similarity_threshold

    async def extract_candidates(
        self,
        text: str,
        source_type: str,
        context: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Extract memory candidates from text."""
        candidates = []

        # Extract facts
        for match in FACT_PATTERN.finditer(text):
            candidates.append({
                "type": MemoryType.SEMANTIC,
                "content": match.group(0).strip(),
                "extracted_fact": match.group(1).strip(),
                "confidence": 0.7,
                "source_span": match.span(),
            })

        # Extract preferences
        for match in PREFERENCE_PATTERN.finditer(text):
            candidates.append({
                "type": MemoryType.SEMANTIC,
                "content": match.group(0).strip(),
                "extracted_fact": match.group(1).strip(),
                "confidence": 0.8,
                "source_span": match.span(),
                "importance_factors": [MemoryImportanceFactor.USER_PREFERENCE.value],
            })

        # Extract decisions
        for match in DECISION_PATTERN.finditer(text):
            candidates.append({
                "type": MemoryType.EPISODIC,
                "content": match.group(0).strip(),
                "extracted_fact": match.group(1).strip(),
                "confidence": 0.75,
                "source_span": match.span(),
                "importance_factors": [MemoryImportanceFactor.TASK_CRITICAL.value],
            })

        # Extract procedures
        for match in PROCEDURE_PATTERN.finditer(text):
            candidates.append({
                "type": MemoryType.PROCEDURAL,
                "content": match.group(0).strip(),
                "extracted_fact": match.group(1).strip(),
                "confidence": 0.7,
                "source_span": match.span(),
            })

        return candidates

    def classify_memory(self, candidate: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """Classify memory candidate into appropriate type and scope."""
        memory_type = candidate.get("type", MemoryType.SHORT_TERM)

        # Determine scope based on context
        scope = MemoryScope.CONVERSATION
        if context.get("task_id"):
            scope = MemoryScope.TASK
        elif context.get("agent_id"):
            scope = MemoryScope.AGENT
        elif context.get("team_id"):
            scope = MemoryScope.TEAM

        return {
            **candidate,
            "memory_type": memory_type,
            "scope": scope,
        }

    def validate_candidate(self, candidate: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Validate memory candidate."""
        errors = []

        content = candidate.get("content", "")
        if not content or len(content.strip()) < 3:
            errors.append("Content too short")

        if len(content) > 50000:
            errors.append("Content too long")

        confidence = candidate.get("confidence", 0.5)
        if not 0 <= confidence <= 1:
            errors.append("Confidence must be between 0 and 1")

        return len(errors) == 0, errors

    def sanitize_content(self, content: str) -> str:
        """Remove secrets from content."""
        sanitized = content
        for pattern in SECRET_PATTERNS:
            sanitized = pattern.sub(r'\1=[REDACTED]', sanitized)
        return sanitized

    async def check_duplicates(
        self,
        session: AsyncSession,
        organization_id: UUID,
        candidate: Dict[str, Any],
    ) -> List[Memory]:
        """Check for duplicate memories."""
        content_hash = hashlib.sha256(candidate["content"].encode()).hexdigest()[:32]

        # Check for exact content match
        result = await session.execute(
            select(Memory).where(
                Memory.organization_id == organization_id,
                Memory.content == candidate["content"],
                Memory.deleted_at.is_(None),
            )
        )
        exact_matches = list(result.scalars().all())

        # Check for semantic similarity if embedding exists
        semantic_matches = []
        # This would use vector search if embeddings are available

        return exact_matches + semantic_matches


class MemoryService:
    """Main memory service orchestrating the write pipeline, retrieval, and lifecycle."""

    def __init__(
        self,
        db: AsyncSession,
        embedding_provider: Optional[EmbeddingProvider] = None,
    ):
        self.db = db
        self.write_pipeline = MemoryWritePipeline(embedding_provider)
        self.memory_repo = MemoryRepository(db)
        self.version_repo = MemoryVersionRepository(db)
        self.access_log_repo = MemoryAccessLogRepository(db)
        self.embedding_repo = MemoryEmbeddingRepository(db)
        self.link_repo = MemoryLinkRepository(db)
        self.conflict_repo = MemoryConflictRepository(db)
        self.consolidation_job_repo = MemoryConsolidationJobRepository(db)
        self.policy_repo = MemoryPolicyRepository(db)
        self.conversation_repo = ConversationRepository(db)
        self.message_repo = MessageRepository(db)
        self.agent_run_repo = AgentRunRepository(db)
        self.agent_repo = AgentRepository(db)
        self.task_repo = TaskRepository(db)
        self.team_repo = TeamRepository(db)
        self.orchestration_repo = OrchestrationRunRepository(db)
        self.agent_repo = AgentRepository(db)

    # ==================== Write Pipeline ====================

    async def create_memory(
        self,
        organization_id: UUID,
        content: str,
        memory_type: MemoryType = MemoryType.SHORT_TERM,
        scope: MemoryScope = MemoryScope.CONVERSATION,
        visibility: MemoryVisibility = MemoryVisibility.PRIVATE,
        agent_id: Optional[UUID] = None,
        user_id: Optional[UUID] = None,
        team_id: Optional[UUID] = None,
        task_id: Optional[UUID] = None,
        conversation_id: Optional[UUID] = None,
        agent_run_id: Optional[UUID] = None,
        orchestration_run_id: Optional[UUID] = None,
        source_type: MemorySourceType = MemorySourceType.AGENT_OUTPUT,
        source_id: Optional[str] = None,
        source_location: Optional[str] = None,
        structured_data: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
        confidence: float = 0.5,
        confidence_source: Optional[str] = None,
        importance: float = 0.5,
        importance_factors: Optional[List[str]] = None,
        expires_at: Optional[datetime] = None,
        summary: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Memory:
        """Create a new memory through the write pipeline."""
        # Sanitize content
        content = self._sanitize_content(content)

        # Build memory object
        memory = Memory(
            organization_id=organization_id,
            user_id=user_id,
            agent_id=agent_id,
            team_id=team_id,
            task_id=task_id,
            conversation_id=conversation_id,
            agent_run_id=agent_run_id,
            orchestration_run_id=orchestration_run_id,
            memory_type=memory_type,
            scope=scope,
            visibility=visibility,
            content=content,
            summary=summary,
            structured_data=structured_data or {},
            source_type=source_type,
            source_id=source_id,
            source_location=source_location,
            tags=tags or [],
            confidence=confidence,
            confidence_source=confidence_source,
            importance=importance,
            importance_factors=importance_factors or [],
            expires_at=expires_at,
            status="active",
        )

        # Check for duplicates
        duplicates = await self._check_duplicates(content, organization_id)
        if duplicates:
            # Could merge or reject based on policy
            pass

        self.db.add(memory)
        await self.db.flush()

        # Queue embedding generation
        await self._queue_embedding_generation(memory)

        # Log access
        await self._log_access(memory, "write")

        return memory

    async def _sanitize_content(self, content: str) -> str:
        """Sanitize content by removing secrets."""
        sanitized = content
        for pattern in SECRET_PATTERNS:
            sanitized = pattern.sub(r'\1=[REDACTED]', sanitized)
        return sanitized

    async def _check_duplicates(self, content: str, organization_id: UUID) -> List[Memory]:
        """Check for duplicate memories."""
        result = await self.db.execute(
            select(Memory).where(
                Memory.organization_id == organization_id,
                Memory.content == content,
                Memory.deleted_at.is_(None),
            )
        )
        return list(result.scalars().all())

    async def _queue_embedding_generation(self, memory: Memory) -> None:
        """Queue embedding generation for a memory."""
        # In production, this would queue to a background job
        # For now, we'll trigger it asynchronously
        pass

    async def _log_access(self, memory: Memory, access_type: str, accessed_by: Optional[UUID] = None, agent_id: Optional[UUID] = None) -> None:
        """Log memory access."""
        log = MemoryAccessLog(
            memory_id=memory.id,
            organization_id=memory.organization_id,
            accessed_by=accessed_by,
            agent_id=agent_id,
            access_type=access_type,
            metadata={},
        )
        self.db.add(access_log)
        await self.db.flush()

    # ==================== Retrieval ====================

    async def retrieve_memories(
        self,
        organization_id: UUID,
        query: str = "",
        scope: Optional[str] = None,
        memory_type: Optional[str] = None,
        tags: Optional[List[str]] = None,
        agent_id: Optional[UUID] = None,
        user_id: Optional[UUID] = None,
        task_id: Optional[UUID] = None,
        conversation_id: Optional[UUID] = None,
        team_id: Optional[UUID] = None,
        scope_filter: Optional[str] = None,
        memory_type_filter: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
        use_vector_search: bool = True,
        query_embedding: Optional[List[float]] = None,
        similarity_threshold: float = 0.7,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Memory]:
        """Hybrid search combining keyword and vector search."""
        # Build query conditions
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
        if scope_filter:
            conditions.append("m.scope = :scope")
            params["scope"] = scope_filter

        # Add memory type filter
        if memory_type_filter:
            conditions.append("m.memory_type = :mem_type")
            params["mem_type"] = memory_type_filter

        # Add agent filter
        if agent_id:
            conditions.append("m.agent_id = :agent_id")
            params["agent_id"] = str(agent_id)

        # Add task filter
        if task_id:
            conditions.append("m.task_id = :task_id")
            params["task_id"] = str(task_id)

        # Add conversation filter
        if conversation_id:
            conditions.append("m.conversation_id = :conv_id")
            params["conv_id"] = str(conversation_id)

        # Add team filter
        if team_id:
            conditions.append("m.team_id = :team_id")
            params["team_id"] = str(team_id)

        # Add tags filter
        if tags:
            conditions.append("m.tags @> :tags")
            params["tags"] = tags

        # Add visibility filter
        conditions.append("m.visibility IN ('private', 'authorized', 'team', 'organization', 'shared')")

        # Build the query
        select_cols = "m.*"
        order_by = "m.importance DESC, m.confidence DESC, m.created_at DESC"

        if query_embedding is not None:
            select_cols += ", 1 - (m.embedding <=> :query_embedding) AS vector_score"
            params["query_embedding"] = query_embedding
            # Hybrid ranking: 70% vector, 30% importance/recency
            order_by = "COALESCE(vector_score, 0) * 0.7 + m.importance * 0.2 + (m.confidence * 0.1) DESC"

        where_clause = " AND ".join(conditions)
        query = f"""
            SELECT {select_cols}
            FROM memories m
            WHERE {where_clause}
            ORDER BY {order_by}
            LIMIT :limit OFFSET :offset
        """

        result = await self.db.execute(text(query), params)
        return [row for row in result]

    async def retrieve_by_context(
        self,
        organization_id: UUID,
        context: Dict[str, Any],
        limit: int = 20,
    ) -> List[Memory]:
        """Retrieve memories relevant to a given context."""
        query_parts = []

        if "query" in context:
            query_parts.append(context["query"])

        if "task" in context:
            query_parts.append(f"task: {context['task']}")

        if "topic" in context:
            query_parts.append(context["topic"])

        query = " ".join(query_parts) if query_parts else ""

        return await self.retrieve_memories(
            organization_id=organization_id,
            query=query,
            limit=limit,
        )

    async def retrieve_by_task(
        self,
        organization_id: UUID,
        task_id: UUID,
        limit: int = 20,
    ) -> List[Memory]:
        """Retrieve all memories associated with a task."""
        return await self.memory_repo.list_by_task(organization_id, task_id, limit=limit)

    async def retrieve_by_conversation(
        self,
        organization_id: UUID,
        conversation_id: UUID,
        limit: int = 50,
    ) -> List[Memory]:
        """Retrieve all memories from a conversation."""
        return await self.memory_repo.list_by_conversation(organization_id, conversation_id, limit=limit)

    async def retrieve_by_agent(
        self,
        organization_id: UUID,
        agent_id: UUID,
        limit: int = 20,
    ) -> List[Memory]:
        """Retrieve memories for a specific agent."""
        return await self.memory_repo.list_by_agent(organization_id, agent_id, limit=limit)

    async def retrieve_by_agent_run(
        self,
        organization_id: UUID,
        agent_run_id: UUID,
        limit: int = 20,
    ) -> List[Memory]:
        """Retrieve memories from an agent run."""
        return await self.memory_repo.list_by_agent_run(organization_id, agent_run_id, limit=limit)

    # ==================== Memory Lifecycle ====================

    async def update_memory(
        self,
        organization_id: UUID,
        memory_id: UUID,
        content: Optional[str] = None,
        summary: Optional[str] = None,
        structured_data: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
        confidence: Optional[float] = None,
        importance: Optional[float] = None,
        importance_factors: Optional[List[str]] = None,
        visibility: Optional[str] = None,
        expires_at: Optional[datetime] = None,
        status: Optional[str] = None,
        changed_by: Optional[UUID] = None,
        change_reason: str = "",
        ) -> Memory:
        """Update memory with version tracking."""
        result = await self.db.execute(
            select(Memory).where(Memory.id == memory_id, Memory.organization_id == organization_id)
        )
        memory = result.scalar_one_or_none()
        if not memory:
            raise MemoryNotFoundError(f"Memory {memory_id} not found")

        # Create version before updating
        if changed_by or content is not None:
            await self.version_repo.create_version(memory, changed_by, change_reason)

        if content is not None:
            memory.content = self._sanitize_content(content)
        if summary is not None:
            memory.summary = summary
        if structured_data is not None:
            memory.structured_data = structured_data
        if tags is not None:
            memory.tags = tags
        if confidence is not None:
            memory.confidence = confidence
        if importance is not None:
            memory.importance = importance
        if importance_factors is not None:
            memory.importance_factors = importance_factors
        if tags is not None:
            memory.tags = tags
        if visibility is not None:
            memory.visibility = MemoryVisibility(visibility)
        if expires_at is not None:
            memory.expires_at = expires_at
        if status is not None:
            memory.status = MemoryStatus(status)

        await self.db.flush()
        await self._log_access(memory, "update")
        return memory

        async def supersede_memory(
            self,
            memory_id: UUID,
            organization_id: UUID,
            new_content: str,
            superseded_by_id: UUID,
            changed_by: Optional[UUID] = None,
            ) -> Memory:
            """Supersede a memory with a new version."""
            result = await self.db.execute(
                select(Memory).where(Memory.id == memory_id, Memory.organization_id == organization_id)
            )
            memory = result.scalar_one_or_none()
            if not memory:
                raise MemoryNotFoundError(f"Memory {memory_id} not found")
    
            # Create new memory that supersedes this one
            new_memory = Memory(
                organization_id=organization_id,
                content=new_content,
                summary=f"Supersedes: {memory.content[:100]}",
                source_type=MemorySourceType.AGENT_OUTPUT,
                scope=memory.scope,
                visibility=memory.visibility,
                parent_memory_id=memory.id,
            )
    
            memory.status = MemoryStatus.SUPERSEDED
            memory.superseded_by_id = superseded_by_id
    
            self.db.add(new_memory)
            await self.db.flush()
            return new_memory
    
        async def revoke_memory(
            self,
            memory_id: UUID,
            organization_id: UUID,
            reason: str,
            revoked_by: UUID,
        ) -> Memory:
            """Revoke a memory (mark as revoked but keep for audit)."""
            result = await self.db.execute(
                select(Memory).where(Memory.id == memory_id, Memory.organization_id == organization_id)
            )
            memory = result.scalar_one_or_none()
            if not memory:
                raise MemoryNotFoundError(f"Memory {memory_id} not found")
    
            memory.status = MemoryStatus.REVOKED
            memory.metadata = {**memory.metadata, "revoked_reason": reason, "revoked_by": str(revoked_by)}
            await self.db.flush()
            return memory
    
        async def delete_memory(
            self,
            memory_id: UUID,
            organization_id: UUID,
            hard: bool = False,
        ) -> bool:
            """Delete a memory (soft or hard delete)."""
            result = await self.db.execute(
                select(Memory).where(Memory.id == memory_id, Memory.organization_id == organization_id)
            )
            memory = result.scalar_one_or_none()
            if not memory:
                raise MemoryNotFoundError(f"Memory {memory_id} not found")
    
            if hard:
                await self.db.delete(memory)
            else:
                memory.status = MemoryStatus.DELETED
                memory.deleted_at = datetime.now(timezone.utc)
    
            await self.db.flush()
            return True
    
        async def promote_memory(
            self,
            memory_id: UUID,
            organization_id: UUID,
            new_type: MemoryType,
            new_scope: MemoryScope,
            promoted_by: UUID,
        ) -> Memory:
            """Promote memory to a higher-level type/scope."""
            result = await self.db.execute(
                select(Memory).where(Memory.id == memory_id, Memory.organization_id == organization_id)
            )
            memory = result.scalar_one_or_none()
            if not memory:
                raise MemoryNotFoundError(f"Memory {memory_id} not found")
    
            old_type = memory.memory_type
            old_scope = memory.scope
            memory.memory_type = new_type
            memory.scope = new_scope
    
            await self.version_repo.create_version(memory, promoted_by, f"Promoted from {old_type.value}/{old_scope.value} to {new_type.value}/{new_scope.value}")
            await self.db.flush()
            return memory
    
        # ==================== Review & Correction ====================
    
        async def submit_review(
            self,
            memory_id: UUID,
            organization_id: UUID,
            reviewer_id: UUID,
            status: str,
            criteria_results: List[Dict[str, Any]],
            issues: Optional[List[str]] = None,
            required_changes: Optional[List[str]] = None,
            evidence: Optional[List[str]] = None,
        ) -> Memory:
            """Submit a review for a memory."""
            result = await self.db.execute(
                select(Memory).where(Memory.id == memory_id, Memory.organization_id == organization_id)
            )
            memory = result.scalar_one_or_none()
            if not memory:
                raise MemoryNotFoundError(f"Memory {memory_id} not found")
    
            # Create review record
            # This would create a ReviewResult record
            # For now, update memory status based on review
            if status == "approved":
                memory.status = "active"
            elif status == "revision_required":
                memory.status = "revision_required"
            elif status == "rejected":
                memory.status = "rejected"
    
            await self.db.flush()
            return memory
    
        async def correct_memory(
            self,
            memory_id: UUID,
            organization_id: UUID,
            corrected_content: str,
            corrected_by: UUID,
            reason: str,
        ) -> Memory:
            """Correct a memory (creates new version, marks old as superseded)."""
            result = await self.db.execute(
                select(Memory).where(Memory.id == memory_id, Memory.organization_id == organization_id)
            )
            memory = result.scalar_one_or_none()
            if not memory:
                raise MemoryNotFoundError(f"Memory {memory_id} not found")
    
            # Create corrected version
            corrected = Memory(
                organization_id=organization_id,
                content=corrected_content,
                source_type=MemorySourceType.EXPLICIT,
                scope=memory.scope,
                visibility=memory.visibility,
                parent_memory_id=memory.id,
                source_id=memory.source_id,
                source_location=memory.source_location,
                confidence=1.0,
                confidence_source="explicit_user_statement",
                importance=memory.importance,
            )
    
            # Mark original as superseded
            memory.status = MemoryStatus.SUPERSEDED
            memory.superseded_by_id = corrected.id
    
            self.db.add(corrected)
            await self.db.flush()
            return corrected
    
        # ==================== Conflict Resolution ====================
    
        async def detect_conflicts(
            self,
            organization_id: UUID,
            memory_id: UUID,
        ) -> Optional[MemoryConflict]:
            """Detect conflicts between memories."""
            result = await self.db.execute(
                select(Memory).where(Memory.id == memory_id, Memory.organization_id == organization_id)
            )
            memory = result.scalar_one_or_none()
            if not memory:
                return None
    
            # Find potentially conflicting memories
            similar = await self.db.execute(
                select(Memory).where(
                    Memory.organization_id == organization_id,
                    Memory.id != memory_id,
                    Memory.status == "active",
                    Memory.deleted_at.is_(None),
                    Memory.content.ilike(f"%{memory.content[:50]}%"),
                ).limit(10)
            )
    
            similar_memories = list(similar.scalars().all())
            if not similar_memories:
                return None
    
            # Check for contradictions (simplified)
            conflicts = []
            for other in similar_memories:
                # Simple check: different content but similar topic
                if other.content != memory.content:
                    # Could use more sophisticated NLP here
                    claims = [
                        {"source": str(memory.id), "claim": memory.content},
                        {"source": str(other.id), "claim": other.content},
                    ]
                    if claims not in [c["claims"] for c in (await self._get_conflicts(organization_id))]:
                        # Create conflict record
                        conflict = MemoryConflict(
                            organization_id=organization_id,
                            claims=claims,
                            sources=[{"memory_id": str(memory.id)}, {"memory_id": str(other.id)}],
                            evidence=[{"source": str(memory.id), "content": memory.content[:200]},
                                     {"source": str(other.id), "content": other.content[:200]}],
                            confidence={str(memory.id): memory.confidence, str(other.id): other.confidence},
                            status="open",
                        )
                        self.db.add(conflict)
                        await self.db.flush()
                        return conflict
    
            return None
    
        async def resolve_conflict(
            self,
            conflict_id: UUID,
            organization_id: UUID,
            resolution: str,
            resolved_by: UUID,
            reason: str = "",
        ) -> MemoryConflict:
            """Resolve a memory conflict."""
            result = await self.db.execute(
                select(MemoryConflict).where(MemoryConflict.id == conflict_id, MemoryConflict.organization_id == organization_id)
            )
            conflict = result.scalar_one_or_none()
            if not conflict:
                raise ValueError(f"Conflict {conflict_id} not found")
    
            conflict.status = "resolved"
            conflict.resolution = resolution
            conflict.resolved_by = resolved_by
            conflict.resolved_at = datetime.now(timezone.utc)
            conflict.resolution_reason = reason
    
            # Apply resolution to memories
            if resolution == "supersede":
                # Implementation would depend on specific case
                pass
            elif resolution == "keep_both":
                # Both memories remain active
                pass
    
            await self.db.flush()
            return conflict
    
        # ==================== Consolidation ====================
    
        async def run_consolidation(
            self,
            organization_id: UUID,
            scope: str = "organization",
            scope_id: Optional[UUID] = None,
            memory_type: Optional[str] = None,
        ) -> MemoryConsolidationJob:
            """Run memory consolidation for an organization/scope."""
            job = MemoryConsolidationJob(
                organization_id=organization_id,
                scope=scope,
                scope_id=scope_id,
                memory_type=memory_type,
                status="running",
                started_at=datetime.now(timezone.utc),
            )
            self.db.add(job)
            await self.db.flush()
    
            try:
                # Find memories to consolidate
                memories = await self._get_memories_for_consolidation(
                    organization_id, scope, scope_id, memory_type
                )
    
                # Group by similarity
                groups = await self._group_similar_memories(memories)
    
                # Consolidate each group
                output_count = 0
                for group in groups:
                    if len(group) > 1:
                        consolidated = await self._consolidate_group(group)
                        output_count += 1
    
                job.status = "completed"
                job.completed_at = datetime.now(timezone.utc)
                job.input_memory_count = len(memories)
                job.output_memory_count = output_count
    
            except Exception as e:
                job.status = "failed"
                job.error = str(e)
    
            job.completed_at = datetime.now(timezone.utc)
            await self.db.flush()
            return job
    
        async def _get_memories_for_consolidation(
            self,
            organization_id: UUID,
            scope: str,
            scope_id: Optional[UUID],
            memory_type: Optional[str],
        ) -> List[Memory]:
            query = select(Memory).where(
                Memory.organization_id == organization_id,
                Memory.status == "active",
                Memory.deleted_at.is_(None),
            )
    
            if scope_id:
                query = query.where(Memory.orchestration_run_id == scope_id)
            if memory_type:
                query = query.where(Memory.memory_type == memory_type)
    
            result = await self.db.execute(query.limit(1000))
            return list(result.scalars().all())
    
        async def _group_similar_memories(self, memories: List[Memory]) -> List[List[Memory]]:
            """Group memories by similarity."""
            # Simplified grouping - in production would use embedding similarity
            groups = []
            processed = set()
    
            for memory in memories:
                if memory.id in processed:
                    continue
    
                group = [memory]
                processed.add(memory.id)
    
                for other in memories:
                    if other.id in processed:
                        continue
                    # Simple similarity check
                    if self._are_similar(memory, other):
                        group.append(other)
                        processed.add(other.id)
    
                if len(group) > 1:
                    groups.append(group)
    
            return groups
    
        def _are_similar(self, m1: Memory, m2: Memory) -> bool:
            # Simple similarity check - could use embeddings
            words1 = set(m1.content.lower().split())
            words2 = set(m2.content.lower().split())
            if not words1 or not words2:
                return False
            intersection = words1 & words2
            union = words1 | words2
            return len(intersection) / len(union) > 0.7
    
        async def _consolidate_group(self, group: List[Memory]) -> Memory:
            """Consolidate a group of similar memories into one."""
            # Sort by importance and confidence
            group.sort(key=lambda m: (m.importance, m.confidence), reverse=True)
    
            # Create consolidated memory
            primary = group[0]
            consolidated_content = "\n\n".join([m.content for m in group])
    
            consolidated = Memory(
                organization_id=primary.organization_id,
                content=consolidated_content,
                summary=f"Consolidated from {len(group)} memories",
                memory_type=primary.memory_type,
                scope=primary.scope,
                visibility=primary.visibility,
                source_type=MemorySourceType.CONSOLIDATED,
                source_id=f"consolidated_{group[0].id}",
                confidence=sum(m.confidence for m in group) / len(group),
                importance=max(m.importance for m in group),
                importance_factors=list(set().union(*[m.importance_factors for m in group])),
                tags=list(set().union(*[m.tags for m in group])),
                parent_memory_id=group[0].id,
            )
    
            # Mark originals as superseded
            for m in group[1:]:
                m.status = MemoryStatus.SUPERSEDED
                m.superseded_by_id = None  # Will be set after flush
    
            self.db.add(consolidated)
            await self.db.flush()
            return consolidated
    
        # ==================== Decay & Expiration ====================
    
        async def apply_decay(self, organization_id: UUID) -> int:
            """Apply decay to memories based on age and access patterns."""
            # Reduce importance of old, unaccessed memories
            cutoff = datetime.now(timezone.utc) - timedelta(days=90)
            result = await self.db.execute(
                select(Memory).where(
                    Memory.organization_id == organization_id,
                    Memory.status == "active",
                    Memory.deleted_at.is_(None),
                    Memory.last_accessed_at < cutoff,
                    Memory.importance > 0.1,
                )
            )
    
            decayed = 0
            for memory in result.scalars().all():
                # Reduce importance by 10% per quarter of inactivity
                memory.importance = max(0.1, memory.importance * 0.9)
                decayed += 1
    
            if decayed > 0:
                await self.db.flush()
    
            return decayed
    
        async def expire_memories(self) -> int:
            """Expire memories past their expiration date."""
            now = datetime.now(timezone.utc)
            result = await self.db.execute(
                update(Memory)
                .where(
                    Memory.expires_at.is_not(None),
                    Memory.expires_at < datetime.now(timezone.utc),
                    Memory.status == "active",
                )
                .values(status=MemoryStatus.EXPIRED.value)
            )
            return result.rowcount
    
        # ==================== Embedding Management ====================
    
        async def generate_embedding(self, memory_id: UUID) -> bool:
            """Generate embedding for a memory."""
            result = await self.db.execute(
                select(Memory).where(Memory.id == memory_id)
            )
            memory = result.scalar_one_or_none()
            if not memory:
                return False
    
            # This would call the embedding provider
            # For now, mark as pending
            memory.embedding_status = MemoryEmbeddingStatus.PENDING
            await self.db.flush()
            return True
    
        async def retry_failed_embeddings(self, organization_id: UUID) -> int:
            """Retry failed embedding generations."""
            result = await self.db.execute(
                select(Memory).where(
                    Memory.organization_id == organization_id,
                    Memory.embedding_status == "failed",
                    Memory.embedding_retries < 3,
                ).limit(100)
            )
    
            retried = 0
            for memory in result.scalars().all():
                memory.embedding_status = "pending"
                memory.embedding_error = None
                memory.embedding_retries += 1
                retried += 1
    
            if retried > 0:
                await self.db.flush()
    
            return retried
    
        # ==================== Access Control ====================
    
        async def check_access(
            self,
            memory_id: UUID,
            user_id: UUID,
            organization_id: UUID,
            required_permission: str = "read",
        ) -> bool:
            """Check if user has access to memory."""
            result = await self.db.execute(
                select(Memory).where(Memory.id == memory_id, Memory.organization_id == organization_id)
            )
            memory = result.scalar_one_or_none()
            if not memory:
                return False
    
            # Check visibility and permissions
            if memory.visibility == MemoryVisibility.PRIVATE:
                return memory.user_id == user_id or memory.agent_id == user_id
            elif memory.visibility == MemoryVisibility.TEAM:
                # Check team membership
                return True  # Simplified
            elif memory.visibility == MemoryVisibility.ORGANIZATION:
                return True  # Organization members can access
    
            return False
    
        # ==================== Export/Import ====================
    
        async def export_memories(
            self,
            organization_id: UUID,
            user_id: UUID,
            filters: Optional[Dict[str, Any]] = None,
        ) -> Dict[str, Any]:
            """Export memories for backup/transfer."""
            memories = await self.retrieve_memories(
                organization_id=organization_id,
                user_id=user_id,
                limit=10000,
            )
    
            return {
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "organization_id": str(organization_id),
                "user_id": str(user_id),
                "count": len(memories),
                "memories": [
                    {
                        "id": str(m.id),
                        "content": m.content,
                        "memory_type": m.memory_type.value,
                        "scope": m.scope.value,
                        "visibility": m.visibility.value,
                        "source_type": m.source_type.value,
                        "tags": m.tags,
                        "confidence": m.confidence,
                        "importance": m.importance,
                        "created_at": m.created_at.isoformat(),
                    }
                    for m in memories
                ],
            }
    
        async def import_memories(
            self,
            organization_id: UUID,
            user_id: UUID,
            memories_data: List[Dict[str, Any]],
        ) -> int:
            """Import memories from export."""
            imported = 0
            for mem_data in memories_data:
                try:
                    await self.create_memory(
                        organization_id=organization_id,
                        user_id=user_id,
                        content=mem_data["content"],
                        memory_type=MemoryType(mem_data["memory_type"]),
                        scope=MemoryScope(mem_data["scope"]),
                        visibility=MemoryVisibility(mem_data["visibility"]),
                        tags=mem_data.get("tags", []),
                        confidence=mem_data.get("confidence", 0.5),
                        importance=mem_data.get("importance", 0.5),
                        source_type=MemorySourceType.IMPORTED,
                    )
                    imported += 1
                except Exception as e:
                    logger.warning("Failed to import memory", error=str(e))
    
            return imported
    
        # ==================== Analytics ====================
    
        async def get_memory_stats(self, organization_id: UUID) -> Dict[str, Any]:
            """Get memory statistics for an organization."""
            total = await self.db.execute(
                select(func.count(Memory.id)).where(
                    Memory.organization_id == organization_id,
                    Memory.deleted_at.is_(None),
                )
            )
            total_count = total.scalar_one()
    
            by_type = await self.db.execute(
                select(Memory.memory_type, func.count(Memory.id))
                .where(Memory.organization_id == organization_id, Memory.deleted_at.is_(None))
                .group_by(Memory.memory_type)
            )
    
            by_status = await self.db.execute(
                select(Memory.status, func.count(Memory.id))
                .where(Memory.organization_id == organization_id, Memory.deleted_at.is_(None))
                .group_by(Memory.status)
            )
    
            avg_confidence = await self.db.execute(
                select(func.avg(Memory.confidence)).where(
                    Memory.organization_id == organization_id,
                    Memory.deleted_at.is_(None),
                )
            )
    
            return {
                "total_memories": total_count,
                "by_type": {row[0]: row[1] for row in by_type},
                "by_status": {row[0]: row[1] for row in by_status},
                "average_confidence": float(avg_confidence.scalar_one() or 0),
            }
    
        async def get_agent_memory_stats(self, organization_id: UUID, agent_id: UUID) -> Dict[str, Any]:
            """Get memory statistics for a specific agent."""
            count = await self.db.execute(
                select(func.count(Memory.id)).where(
                    Memory.organization_id == organization_id,
                    Memory.agent_id == agent_id,
                    Memory.deleted_at.is_(None),
                )
            )
            return {
                "agent_id": str(agent_id),
                "memory_count": count.scalar_one(),
            }
    
        # ==================== Helper Methods ====================
    
        async def _get_conflicts(self, organization_id: UUID) -> List[Dict[str, Any]]:
            result = await self.db.execute(
                select(MemoryConflict).where(
                    MemoryConflict.organization_id == organization_id,
                    MemoryConflict.status == "open",
                )
            )
            return [
                {
                    "id": str(c.id),
                    "claims": c.claims,
                    "sources": c.sources,
                    "evidence": c.evidence,
                    "confidence": c.confidence,
                }
                for c in result.scalars().all()
            ]
    
        async def _record_event(self, event_type: str, organization_id: UUID, payload: Dict[str, Any]) -> None:
            await publish_event(
                self.db,
                event_type=event_type,
                organization_id=organization_id,
                aggregate_id=uuid.uuid4(),
                payload=payload,
            )
    
        # ==================== Conversation Memory ====================
    
        async def create_conversation_memory(
            self,
            conversation_id: UUID,
            organization_id: UUID,
            content: str,
            source_type: MemorySourceType = MemorySourceType.CONVERSATION,
        ) -> Memory:
            """Create a memory from conversation content."""
            return await self.create_memory(
                organization_id=organization_id,
                conversation_id=conversation_id,
                content=content,
                source_type=source_type,
                memory_type=MemoryType.CONVERSATION,
                scope=MemoryScope.CONVERSATION,
            )
    
        async def get_conversation_summary(self, conversation_id: UUID) -> Optional[str]:
            """Generate a summary of conversation memories."""
            memories = await self.retrieve_by_conversation(conversation_id=UUID(conversation_id), limit=100)
            if not memories:
                return None
    
            summary_parts = []
            for m in memories[:10]:
                if m.summary:
                    summary_parts.append(m.summary)
                elif len(m.content) > 50:
                    summary_parts.append(m.content[:200] + "...")
                else:
                    summary_parts.append(m.content)
    
            return "\n".join(summary_parts)
    
    
class MemoryNotFoundError(Exception):
    pass