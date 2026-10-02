"""Background jobs for memory lifecycle management."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

import structlog
from sqlalchemy import select, update, delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.core.config import get_settings
from openagent.db.session import get_db
from openagent.db.models.memory import (
    Memory, MemoryStatus, MemoryEmbeddingStatus, MemoryConsolidationJob,
)
from openagent.management.embedding_providers import create_embedding_provider
from openagent.core.config import get_settings as get_core_settings

logger = structlog.get_logger("memory.jobs")


class MemoryJobRunner:
    """Runs background memory maintenance jobs."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.settings = get_settings()
        self.embedding_provider = None

    async def _get_embedding_provider(self):
        """Get or create embedding provider."""
        if self.embedding_provider is None:
            settings = get_core_settings()
            self.embedding_provider = create_embedding_provider({
                "type": getattr(settings, "EMBEDDING_PROVIDER", "mock"),
                "model": getattr(settings, "EMBEDDING_MODEL", "text-embedding-3-small"),
                "api_key": getattr(settings, "OPENAI_API_KEY", None),
                "base_url": getattr(settings, "OPENAI_BASE_URL", None),
            })
        return self.embedding_provider

    async def generate_embeddings(self, batch_size: int = 50) -> int:
        """Generate embeddings for memories that need them."""
        provider = await self._get_embedding_provider()
        if not provider:
            logger.warning("No embedding provider available")
            return 0

        # Get memories needing embeddings
        result = await self.db.execute(
            select(Memory).where(
                Memory.embedding_status == "pending",
                Memory.status == "active",
                Memory.deleted_at.is_(None),
            ).limit(100)
        )
        memories = list(result.scalars().all())

        if not memories:
            return 0

        processed = 0
        for memory in memories:
            try:
                # Generate embedding
                provider = await self._get_embedding_provider()
                result = await provider.embed_single(memory.content)
                
                memory.embedding = result.embedding
                memory.embedding_status = MemoryEmbeddingStatus.READY
                memory.embedding_model = provider.model_name
                memory.embedding_dimensions = provider.dimensions
                memory.embedded_at = datetime.now(timezone.utc)
                memory.embedding_error = None
                memory.embedding_retries = 0
                
                processed += 1
                
            except Exception as e:
                logger.error(f"Failed to generate embedding for memory {memory.id}", error=str(e))
                memory.embedding_status = MemoryEmbeddingStatus.FAILED
                memory.embedding_error = str(e)
                memory.embedding_retries += 1
                memory.last_embedding_attempt_at = datetime.now(timezone.utc)

        await self.db.commit()
        logger.info(f"Generated embeddings for {processed} memories")
        return processed

    async def retry_failed_embeddings(self, max_retries: int = 3) -> int:
        """Retry failed embedding generations."""
        result = await self.db.execute(
            select(Memory).where(
                Memory.embedding_status == "failed",
                Memory.embedding_retries < 3,
            ).limit(50)
        )
        memories = list(result.scalars().all())

        if not memories:
            return 0

        retried = 0
        for memory in memories:
            memory.embedding_status = "pending"
            memory.embedding_error = None
            memory.embedding_retries += 1
            retried += 1

        await self.db.commit()
        logger.info(f"Reset {retried} failed embeddings for retry")
        return retried

    async def cleanup_stale_embeddings(self, max_age_hours: int = 24) -> int:
        """Clean up memories stuck in embedding generation."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        
        result = await self.db.execute(
            select(Memory).where(
                Memory.embedding_status == "pending",
                Memory.embedded_at.is_not(None),
                Memory.embedded_at < cutoff,
            ).limit(100)
        )
        memories = list(result.scalars().all())

        reset = 0
        for memory in memories:
            memory.embedding_status = "pending"
            memory.embedding_error = "Timed out, resetting for retry"
            memory.embedding_retries += 1
            reset += 1

        if reset > 0:
            await self.db.commit()
            logger.info(f"Reset {reset} stale embeddings for retry")

        return reset


class MemoryLifecycleJobRunner:
    """Runs memory lifecycle management jobs."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def expire_memories(self) -> int:
        """Expire memories past their expiration date."""
        now = datetime.now(timezone.utc)
        result = await self.db.execute(
            update(Memory)
            .where(
                Memory.expires_at.is_not(None),
                Memory.expires_at < now,
                Memory.status == "active",
            )
            .values(status=MemoryStatus.EXPIRED.value)
        )
        expired = result.rowcount
        
        if expired > 0:
            await self.db.commit()
            logger.info(f"Expired {expired} memories")
        
        return expired

    async def apply_decay(
        self,
        organization_id: Optional[str] = None,
        decay_threshold_days: int = 90,
        decay_factor: float = 0.9,
        min_importance: float = 0.1,
    ) -> int:
        """Apply decay to old, unaccessed memories."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=decay_threshold_days)
        
        query = select(Memory).where(
            Memory.status == "active",
            Memory.deleted_at.is_(None),
            Memory.last_accessed_at < cutoff,
            Memory.importance > 0.1,
        )
        
        if organization_id:
            query = query.where(Memory.organization_id == organization_id)
        
        result = await self.db.execute(query.limit(1000))
        memories = list(result.scalars().all())

        decayed = 0
        for memory in result.scalars().all():
            new_importance = max(0.1, memory.importance * 0.9)
            if new_importance != memory.importance:
                memory.importance = new_importance
                decayed += 1

        if decayed > 0:
            await self.db.commit()
            logger.info(f"Applied decay to {decayed} memories")
        
        return decayed

    async def cleanup_revoked(self, max_age_days: int = 30) -> int:
        """Clean up revoked memories older than max_age_days."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        
        result = await self.db.execute(
            select(Memory).where(
                Memory.status == "revoked",
                Memory.updated_at < cutoff,
            ).limit(1000)
        )
        memories = list(result.scalars().all())
        
        deleted = 0
        for memory in memories:
            await self.db.delete(memory)
            deleted += 1
        
        if deleted > 0:
            await self.db.commit()
            logger.info(f"Permanently deleted {deleted} revoked memories")
        
        return deleted


class ConsolidationJobRunner:
    """Runs memory consolidation jobs."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def run_consolidation(
        self,
        organization_id: str,
        scope: str = "organization",
        scope_id: Optional[str] = None,
        memory_type: Optional[str] = None,
        max_groups: int = 100,
        similarity_threshold: float = 0.8,
    ) -> dict:
        """Run a consolidation job."""
        from openagent.db.models.memory import MemoryConsolidationJob
        from sqlalchemy import select
        
        # Create job record
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
            # This would be implemented with the MemoryService
            # For now, return a placeholder
            job.status = "completed"
            job.completed_at = datetime.now(timezone.utc)
            job.input_memory_count = 0
            job.output_memory_count = 0
            await self.db.flush()
            
            return {
                "job_id": str(job.id),
                "status": "completed",
                "input_count": 0,
                "output_count": 0,
            }
        except Exception as e:
            job.status = "failed"
            job.error = str(e)
            job.completed_at = datetime.now(timezone.utc)
            await self.db.flush()
            raise


class EmbeddingRetryRunner:
    """Handles retry logic for failed embeddings."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def retry_failed(self, max_retries: int = 3) -> int:
        """Retry failed embedding generations."""
        from openagent.db.models.memory import Memory
        from sqlalchemy import select, update
        
        result = await self.db.execute(
            select(Memory).where(
                Memory.embedding_status == "failed",
                Memory.embedding_retries < 3,
            ).limit(50)
        )
        memories = list(result.scalars().all())

        if not memories:
            return 0

        reset = 0
        for memory in memories:
            memory.embedding_status = "pending"
            memory.embedding_error = None
            memory.embedding_retries += 1
            memory.last_embedding_attempt_at = datetime.now(timezone.utc)
            reset += 1

        if reset > 0:
            await self.db.commit()
            logger.info(f"Reset {reset} failed embeddings for retry")
        
        return reset


async def run_embedding_generation_job(db: AsyncSession) -> int:
    """Main entry point for embedding generation job."""
    runner = MemoryJobRunner(db)
    return await runner.generate_embeddings()


async def run_embedding_retry_job(db: AsyncSession) -> int:
    """Retry failed embeddings."""
    runner = EmbeddingRetryRunner(db)
    return await runner.retry_failed()


async def run_memory_expiration_job(db: AsyncSession) -> int:
    """Main entry point for memory expiration job."""
    runner = MemoryLifecycleJobRunner(db)
    return await runner.expire_memories()


async def run_memory_decay_job(
    db: AsyncSession,
    organization_id: Optional[str] = None,
) -> int:
    """Main entry point for memory decay job."""
    runner = MemoryLifecycleJobRunner(db)
    return await runner.apply_decay(organization_id=organization_id)


async def run_consolidation_job(
    db: AsyncSession,
    organization_id: str,
    scope: str = "organization",
    scope_id: Optional[str] = None,
    memory_type: Optional[str] = None,
) -> dict:
    """Main entry point for consolidation job."""
    runner = ConsolidationJobRunner(db)
    return await runner.run_consolidation(
        organization_id=organization_id,
        scope=scope,
        scope_id=scope_id,
        memory_type=memory_type,
    )


async def run_embedding_retry_job(db: AsyncSession) -> int:
    """Retry failed embeddings."""
    runner = EmbeddingRetryRunner(db)
    return await runner.retry_failed()


async def run_embedding_cleanup_job(db: AsyncSession) -> int:
    """Clean up stale embeddings."""
    runner = MemoryJobRunner(db)
    return await runner.cleanup_stale_embeddings()