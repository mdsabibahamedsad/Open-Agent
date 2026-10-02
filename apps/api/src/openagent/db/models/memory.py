import uuid
from datetime import datetime
from typing import Optional, Dict, Any, TYPE_CHECKING, List
from sqlalchemy import String, Text, JSON, ForeignKey, Index, Enum as SQLEnum, Float, Integer, Boolean, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID, ARRAY, JSONB
import enum

from openagent.db.models.base import Base, TimestampMixin, UUIDMixin, SoftDeleteMixin

if TYPE_CHECKING:
    from openagent.db.models.organization import Organization
    from openagent.db.models.user import User
    from openagent.db.models.agent import Agent
    from openagent.db.models.agent_run import AgentRun
    from openagent.db.models.task import Task
    from openagent.db.models.conversation import Conversation
    from openagent.db.models.team import Team
    from openagent.db.models.agent_run import AgentRun


class MemoryType(str, enum.Enum):
    WORKING = "working"
    SHORT_TERM = "short_term"
    CONVERSATION = "conversation"
    TASK = "task"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"
    AGENT = "agent"
    TEAM = "team"
    ORGANIZATION = "organization"
    USER = "user"
    SHARED = "shared"


class MemoryScope(str, enum.Enum):
    GLOBAL = "global"
    PLATFORM = "platform"
    ORGANIZATION = "organization"
    DEPARTMENT = "department"
    TEAM = "team"
    USER = "user"
    AGENT = "agent"
    WORKFLOW = "workflow"
    ORCHESTRATION = "orchestration"
    TASK = "task"
    CONVERSATION = "conversation"
    PRIVATE = "private"


class MemoryVisibility(str, enum.Enum):
    PRIVATE = "private"
    AUTHORIZED = "authorized"
    TEAM = "team"
    ORGANIZATION = "organization"
    SHARED = "shared"


class MemorySourceType(str, enum.Enum):
    USER_MESSAGE = "user_message"
    AGENT_OUTPUT = "agent_output"
    TOOL_RESULT = "tool_result"
    DOCUMENT = "document"
    WORKFLOW = "workflow"
    TASK = "task"
    SYSTEM = "system"
    IMPORTED = "imported"
    EXPLICIT = "explicit"
    AGENT_INFERENCE = "agent_inference"
    MODEL_GENERATED = "model_generated"
    CONSOLIDATED = "consolidated"


class MemoryConfidenceSource(str, enum.Enum):
    EXPLICIT_USER_STATEMENT = "explicit_user_statement"
    VERIFIED_TOOL_RESULT = "verified_tool_result"
    DOCUMENT = "document"
    AGENT_INFERENCE = "agent_inference"
    MODEL_GENERATED = "model_generated"
    IMPORTED = "imported"
    CONSOLIDATED = "consolidated"


class MemoryStatus(str, enum.Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    EXPIRED = "expired"
    REVOKED = "revoked"
    SUPERSEDED = "superseded"
    DELETED = "deleted"
    QUARANTINED = "quarantined"
    PENDING = "pending"


class MemoryEmbeddingStatus(str, enum.Enum):
    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"
    STALE = "stale"


class MemoryImportanceFactor(str, enum.Enum):
    EXPLICITLY_SAVED = "explicitly_saved"
    REPEATEDLY_REFERENCED = "repeatedly_referenced"
    TASK_CRITICAL = "task_critical"
    ORGANIZATION_POLICY = "organization_policy"
    USER_PREFERENCE = "user_preference"
    FREQUENCY = "frequency"
    RECENCY = "recency"


class Memory(TimestampMixin, SoftDeleteMixin, UUIDMixin, Base):
    __tablename__ = "memories"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    agent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    team_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="SET NULL"), nullable=True, index=True
    )
    task_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True, index=True
    )
    conversation_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    agent_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    orchestration_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orchestration_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    
    # Core memory classification
    memory_type: Mapped[MemoryType] = mapped_column(
        SQLEnum(MemoryType, name="memory_type", create_constraint=True),
        default=MemoryType.SHORT_TERM,
        nullable=False, index=True
    )
    scope: Mapped[MemoryScope] = mapped_column(
        SQLEnum(MemoryScope, name="memory_scope", create_constraint=True),
        default=MemoryScope.CONVERSATION,
        nullable=False, index=True
    )
    visibility: Mapped[MemoryVisibility] = mapped_column(
        SQLEnum(MemoryVisibility, name="memory_visibility", create_constraint=True),
        default=MemoryVisibility.PRIVATE,
        nullable=False, index=True
    )
    
    # Content
    content: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    structured_data: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    
    # Embedding (for semantic search)
    embedding: Mapped[Optional[List[float]]] = mapped_column(ARRAY(Float), nullable=True)
    embedding_status: Mapped[MemoryEmbeddingStatus] = mapped_column(
        SQLEnum(MemoryEmbeddingStatus, name="memory_embedding_status", create_constraint=True),
        default=MemoryEmbeddingStatus.PENDING,
        nullable=False, index=True
    )
    embedding_model: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    embedding_dimensions: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    embedded_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    
    # Source & Provenance
    source_type: Mapped[MemorySourceType] = mapped_column(
        SQLEnum(MemorySourceType, name="memory_source_type", create_constraint=True),
        default=MemorySourceType.AGENT_OUTPUT,
        nullable=False, index=True
    )
    source_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    source_location: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_timestamp: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    provenance: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    
    # Confidence & Importance
    confidence: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    confidence_source: Mapped[Optional[MemoryConfidenceSource]] = mapped_column(
        SQLEnum(MemoryConfidenceSource, name="memory_confidence_source", create_constraint=True),
        nullable=True, index=True
    )
    importance: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    importance_factors: Mapped[List[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    
    # Metadata
    tags: Mapped[List[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    language: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    
    # Lifecycle
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    status: Mapped[MemoryStatus] = mapped_column(
        SQLEnum(MemoryStatus, name="memory_status", create_constraint=True),
        default=MemoryStatus.ACTIVE,
        nullable=False, index=True
    )
    valid_from: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    
    # Versioning
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    parent_memory_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memories.id", ondelete="SET NULL"), nullable=True, index=True
    )
    superseded_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memories.id", ondelete="SET NULL"), nullable=True, index=True
    )
    change_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    changed_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    
    # Access tracking
    access_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_accessed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_accessed_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    
    # Conflict resolution
    conflict_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memory_conflicts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    
    # Embedding status
    embedding_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    embedding_retries: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_embedding_attempt_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    organization: Mapped["Organization"] = relationship(back_populates="memories")
    # Pre-existing ambiguity fix: memories has multiple FKs to users.id, so the
    # User.memories join must name its FK explicitly (MP19 surfaced this while
    # running the suite; no behavior change beyond resolving the join).
    user: Mapped[Optional["User"]] = relationship(back_populates="memories",
                                                  foreign_keys=[user_id])
    agent: Mapped[Optional["Agent"]] = relationship()
    team: Mapped[Optional["Team"]] = relationship()
    task: Mapped[Optional["Task"]] = relationship()
    conversation: Mapped[Optional["Conversation"]] = relationship()
    agent_run: Mapped[Optional["AgentRun"]] = relationship()
    orchestration_run: Mapped[Optional["AgentRun"]] = relationship()
    parent_memory: Mapped[Optional["Memory"]] = relationship(remote_side="Memory.id", back_populates="child_memories", foreign_keys="Memory.parent_memory_id")
    child_memories: Mapped[List["Memory"]] = relationship(back_populates="parent_memory", foreign_keys="Memory.parent_memory_id")
    superseded_by: Mapped[Optional["Memory"]] = relationship(remote_side="Memory.id", back_populates="supersedes", foreign_keys="Memory.superseded_by_id")
    supersedes: Mapped[Optional["Memory"]] = relationship(back_populates="superseded_by", foreign_keys="Memory.superseded_by_id")
    conflict: Mapped[Optional["MemoryConflict"]] = relationship(back_populates="memories")
    
    # Access logs
    access_logs: Mapped[List["MemoryAccessLog"]] = relationship(back_populates="memory", cascade="all, delete-orphan")

    # Reverse sides expected by MemoryVersion/MemoryLink (pre-existing gaps that
    # broke mapper configuration for the whole suite).
    versions: Mapped[List["MemoryVersion"]] = relationship(back_populates="memory",
                                                           cascade="all, delete-orphan")
    outgoing_links: Mapped[List["MemoryLink"]] = relationship(
        back_populates="source_memory", foreign_keys="MemoryLink.source_memory_id",
        cascade="all, delete-orphan")
    incoming_links: Mapped[List["MemoryLink"]] = relationship(
        back_populates="target_memory", foreign_keys="MemoryLink.target_memory_id",
        cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_memories_organization_id", "organization_id"),
        Index("ix_memories_user_id", "user_id"),
        Index("ix_memories_agent_id", "agent_id"),
        Index("ix_memories_team_id", "team_id"),
        Index("ix_memories_task_id", "task_id"),
        Index("ix_memories_conversation_id", "conversation_id"),
        Index("ix_memories_agent_run_id", "agent_run_id"),
        Index("ix_memories_orchestration_run_id", "orchestration_run_id"),
        Index("ix_memories_memory_type", "memory_type"),
        Index("ix_memories_scope", "scope"),
        Index("ix_memories_visibility", "visibility"),
        Index("ix_memories_status", "status"),
        Index("ix_memories_expires_at", "expires_at"),
        Index("ix_memories_embedding_status", "embedding_status"),
        Index("ix_memories_confidence", "confidence"),
        Index("ix_memories_importance", "importance"),
        Index("ix_memories_source_type", "source_type"),
        Index("ix_memories_source_id", "source_id"),
        Index("ix_memories_parent_memory_id", "parent_memory_id"),
        Index("ix_memories_superseded_by_id", "superseded_by_id"),
        Index("ix_memories_conflict_id", "conflict_id"),
        Index("ix_memories_organization_created", "organization_id", "created_at"),
        Index("ix_memories_organization_status", "organization_id", "status"),
        Index("ix_memories_organization_type", "organization_id", "memory_type"),
        Index("ix_memories_organization_scope", "organization_id", "scope"),
        Index("ix_memories_organization_visibility", "organization_id", "visibility"),
        Index("ix_memories_confidence_importance", "confidence", "importance"),
        Index("ix_memories_created_at", "created_at"),
        # For pgvector similarity search (when pgvector is enabled):
        # Index("ix_memories_embedding", "embedding", postgresql_using="ivfflat", 
        #       postgresql_with={"lists": 100}, postgresql_ops={"embedding": "vector_cosine_ops"}),
    )


class MemoryVersion(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "memory_versions"

    memory_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    structured_data: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    importance: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    importance_factors: Mapped[List[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    tags: Mapped[List[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    change_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    changed_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    embedding: Mapped[Optional[List[float]]] = mapped_column(ARRAY(Float), nullable=True)
    embedding_model: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    embedding_dimensions: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    memory: Mapped["Memory"] = relationship(back_populates="versions")

    __table_args__ = (
        Index("ix_memory_versions_memory_id", "memory_id"),
        Index("ix_memory_versions_version", "memory_id", "version", unique=True),
    )


class MemoryAccessLog(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "memory_access_logs"

    memory_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    accessed_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    agent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    access_type: Mapped[str] = mapped_column(String(50), nullable=False)  # read, write, search, embed
    query: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    result_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    metadata: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    memory: Mapped["Memory"] = relationship(back_populates="access_logs")

    __table_args__ = (
        Index("ix_memory_access_logs_memory_id", "memory_id"),
        Index("ix_memory_access_logs_organization_id", "organization_id"),
        Index("ix_memory_access_logs_accessed_by", "accessed_by"),
        Index("ix_memory_access_logs_agent_id", "agent_id"),
        Index("ix_memory_access_logs_created_at", "created_at"),
    )


class MemoryEmbedding(TimestampMixin, UUIDMixin, Base):
    """Separate table for embeddings to support multiple embedding models/versions"""
    __tablename__ = "memory_embeddings"

    memory_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    model: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding: Mapped[List[float]] = mapped_column(ARRAY(Float), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[MemoryEmbeddingStatus] = mapped_column(
        SQLEnum(MemoryEmbeddingStatus, name="memory_embedding_status", create_constraint=True),
        default=MemoryEmbeddingStatus.PENDING,
        nullable=False, index=True
    )
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    retries: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    __table_args__ = (
        Index("ix_memory_embeddings_memory_id_model", "memory_id", "model", unique=True),
        Index("ix_memory_embeddings_model_status", "model", "status"),
    )


class MemoryLink(TimestampMixin, UUIDMixin, Base):
    """Links between memories (relationships, references, citations)"""
    __tablename__ = "memory_links"

    source_memory_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_memory_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    link_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)  # reference, citation, related, contradicts, supersedes
    strength: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    metadata: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    source_memory: Mapped["Memory"] = relationship(foreign_keys=[source_memory_id], back_populates="outgoing_links")
    target_memory: Mapped["Memory"] = relationship(foreign_keys=[target_memory_id], back_populates="incoming_links")

    __table_args__ = (
        Index("ix_memory_links_source", "source_memory_id"),
        Index("ix_memory_links_target", "target_memory_id"),
        Index("ix_memory_links_type", "link_type"),
        Index("ix_memory_links_unique", "source_memory_id", "target_memory_id", "link_type", unique=True),
    )


class MemoryConflict(TimestampMixin, UUIDMixin, Base):
    """Conflicting memories that need resolution"""
    __tablename__ = "memory_conflicts"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(50), default="open", nullable=False, index=True)  # open, resolved, deferred
    resolution: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # keep_both, prefer_newer, prefer_verified, supersede, require_human
    resolved_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    claims: Mapped[List[Dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    sources: Mapped[List[Dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    evidence: Mapped[List[Dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    confidence: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    memories: Mapped[List["Memory"]] = relationship(back_populates="conflict")

    __table_args__ = (
        Index("ix_memory_conflicts_organization_id", "organization_id"),
        Index("ix_memory_conflicts_status", "status"),
    )


class MemoryConsolidationJob(TimestampMixin, UUIDMixin, Base):
    """Background consolidation jobs"""
    __tablename__ = "memory_consolidation_jobs"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False, index=True)  # pending, running, completed, failed
    scope: Mapped[str] = mapped_column(String(50), nullable=False)  # agent, team, organization, all
    scope_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    memory_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    input_memory_count: Mapped[int] = mapped_column(Integer, default=0)
    output_memory_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    config: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    __table_args__ = (
        Index("ix_memory_consolidation_jobs_organization_id", "organization_id"),
        Index("ix_memory_consolidation_jobs_status", "status"),
    )


class MemoryPolicy(TimestampMixin, UUIDMixin, Base):
    """Organization-level memory policies"""
    __tablename__ = "memory_policies"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    memory_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    automatic_memory: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    retention_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    embedding_provider: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    embedding_model: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    allow_document_memory: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    allow_agent_memory: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    allow_shared_memory: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    auto_consolidation: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    consolidation_interval_hours: Mapped[int] = mapped_column(Integer, default=24, nullable=False)
    default_memory_type: Mapped[str] = mapped_column(String(50), default="short_term", nullable=False)
    default_scope: Mapped[str] = mapped_column(String(50), default="conversation", nullable=False)
    default_visibility: Mapped[str] = mapped_column(String(50), default="private", nullable=False)
    max_memories_per_agent: Mapped[int] = mapped_column(Integer, default=10000, nullable=False)
    max_embedding_retries: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    embedding_retry_delay_seconds: Mapped[int] = mapped_column(Integer, default=60, nullable=False)

    organization: Mapped["Organization"] = relationship(back_populates="memory_policy")

    __table_args__ = (
        Index("ix_memory_policies_organization_id", "organization_id", unique=True),
    )


# Add back_populates to Organization model (need to update Organization model)
# This will be handled via the existing Organization model's memories relationship