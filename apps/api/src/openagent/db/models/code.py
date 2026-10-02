"""Code agent SQLAlchemy models (mirrors alembic 016_add_code_agent)."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy import JSON as SA_JSON
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from openagent.db.models.base import Base, TimestampMixin, SoftDeleteMixin, UUIDMixin


class RepositoryProvider(str, enum.Enum):
    local = "local"
    generic = "generic"
    github = "github"
    gitlab = "gitlab"
    bitbucket = "bitbucket"


class RepositoryStatus(str, enum.Enum):
    CONNECTED = "connected"
    SYNCING = "syncing"
    ERROR = "error"
    DISCONNECTED = "disconnected"


class WorkspaceStatus(str, enum.Enum):
    CREATING = "CREATING"
    READY = "READY"
    BUSY = "BUSY"
    DIRTY = "DIRTY"
    CHECKING = "CHECKING"
    TESTING = "TESTING"
    COMMITTING = "COMMITTING"
    ERROR = "ERROR"
    CLEANING = "CLEANING"
    DELETED = "DELETED"


class CodingTaskStatus(str, enum.Enum):
    QUEUED = "QUEUED"
    INITIALIZING = "INITIALIZING"
    ANALYZING = "ANALYZING"
    PLANNING = "PLANNING"
    EDITING = "EDITING"
    VALIDATING = "VALIDATING"
    TESTING = "TESTING"
    REVIEWING = "REVIEWING"
    WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
    COMMITTING = "COMMITTING"
    READY_FOR_PR = "READY_FOR_PR"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMED_OUT = "TIMED_OUT"


class TaskRiskLevel(str, enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ExecutionStatus(str, enum.Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"


class ReviewStatus(str, enum.Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    BLOCKED = "BLOCKED"


class ReviewSeverity(str, enum.Enum):
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class PatchStatus(str, enum.Enum):
    PROPOSED = "PROPOSED"
    VALIDATED = "VALIDATED"
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"


class PRStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    READY = "READY"
    OPENED = "OPENED"
    MERGED = "MERGED"
    CLOSED = "CLOSED"


class Repository(TimestampMixin, SoftDeleteMixin, UUIDMixin, Base):
    __tablename__ = "repositories"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True)
    provider: Mapped[RepositoryProvider] = mapped_column(
        SQLEnum(RepositoryProvider, name="repository_provider", create_constraint=False),
        default=RepositoryProvider.generic, nullable=False)
    external_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(500), nullable=False)
    clone_url: Mapped[str] = mapped_column(Text, nullable=False)
    default_branch: Mapped[str] = mapped_column(String(255), default="main", nullable=False)
    visibility: Mapped[str] = mapped_column(String(20), default="private", nullable=False)
    status: Mapped[RepositoryStatus] = mapped_column(
        SQLEnum(RepositoryStatus, name="repository_status", create_constraint=False),
        default=RepositoryStatus.CONNECTED, nullable=False)
    # Opaque handle into the credential system; raw secrets never stored here.
    credential_ref: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    provider_config: Mapped[Dict[str, Any]] = mapped_column(SA_JSON, default=dict, nullable=False)
    last_synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    meta: Mapped[Dict[str, Any]] = mapped_column("metadata", SA_JSON, default=dict, nullable=False)


class CodeWorkspace(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "code_workspaces"

    workspace_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True)
    repository_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False, index=True)
    task_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("code_tasks.id", ondelete="SET NULL", use_alter=True),
        nullable=True)
    branch: Mapped[str] = mapped_column(String(255), nullable=False)
    base_revision: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    current_revision: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    # Host path — server-side only, never exposed to the model or API responses.
    filesystem_root: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[WorkspaceStatus] = mapped_column(
        SQLEnum(WorkspaceStatus, name="workspace_status", create_constraint=False),
        default=WorkspaceStatus.CREATING, nullable=False, index=True)
    # Snapshot of pre-existing user changes at creation (protection ledger).
    user_changes_snapshot: Mapped[List[Any]] = mapped_column(SA_JSON, default=list, nullable=False)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    meta: Mapped[Dict[str, Any]] = mapped_column("metadata", SA_JSON, default=dict, nullable=False)


class CodingTask(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "code_tasks"

    task_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True)
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    agent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True)
    repository_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False, index=True)
    workspace_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("code_workspaces.id", ondelete="SET NULL"),
        nullable=True)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    branch: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    base_revision: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    status: Mapped[CodingTaskStatus] = mapped_column(
        SQLEnum(CodingTaskStatus, name="coding_task_status", create_constraint=False),
        default=CodingTaskStatus.QUEUED, nullable=False, index=True)
    risk_level: Mapped[TaskRiskLevel] = mapped_column(
        SQLEnum(TaskRiskLevel, name="task_risk_level", create_constraint=False),
        default=TaskRiskLevel.MEDIUM, nullable=False)
    max_steps: Mapped[int] = mapped_column(Integer, default=50, nullable=False)
    max_duration_seconds: Mapped[int] = mapped_column(Integer, default=3600, nullable=False)
    budgets: Mapped[Dict[str, Any]] = mapped_column(SA_JSON, default=dict, nullable=False)
    current_step: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    result: Mapped[Optional[Dict[str, Any]]] = mapped_column(SA_JSON, nullable=True)
    meta: Mapped[Dict[str, Any]] = mapped_column("metadata", SA_JSON, default=dict, nullable=False)


class CodeTaskStep(UUIDMixin, Base):
    __tablename__ = "code_task_steps"

    task_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("code_tasks.id", ondelete="CASCADE"),
        nullable=False, index=True)
    step_no: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="PENDING", nullable=False)
    # Redacted I/O summaries (never raw secrets / full dumps).
    input_summary: Mapped[Dict[str, Any]] = mapped_column(SA_JSON, default=dict, nullable=False)
    output_summary: Mapped[Dict[str, Any]] = mapped_column(SA_JSON, default=dict, nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CodeFileIndex(UUIDMixin, Base):
    __tablename__ = "code_file_index"

    repository_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False, index=True)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    size: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    mtime_ns: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    indexed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CodeSymbol(UUIDMixin, Base):
    __tablename__ = "code_symbols"

    repository_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    file: Mapped[str] = mapped_column(Text, nullable=False)
    line_start: Mapped[int] = mapped_column(Integer, nullable=False)
    line_end: Mapped[int] = mapped_column(Integer, nullable=False)
    signature: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    parent: Mapped[str] = mapped_column(String(500), default="", nullable=False)


class CodeReference(UUIDMixin, Base):
    __tablename__ = "code_references"

    repository_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False, index=True)
    from_file: Mapped[str] = mapped_column(Text, nullable=False)
    from_symbol: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    to_name: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    line: Mapped[int] = mapped_column(Integer, nullable=False)


class CodeDependency(UUIDMixin, Base):
    __tablename__ = "code_dependencies"

    repository_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False, index=True)
    file: Mapped[str] = mapped_column(Text, nullable=False)
    manager: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    version_spec: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    scope: Mapped[str] = mapped_column(String(40), default="runtime", nullable=False)


class CodeChunk(UUIDMixin, Base):
    __tablename__ = "code_chunks"

    repository_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False, index=True)
    file: Mapped[str] = mapped_column(Text, nullable=False)
    symbol: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    line_start: Mapped[int] = mapped_column(Integer, nullable=False)
    line_end: Mapped[int] = mapped_column(Integer, nullable=False)


class CodeEmbedding(UUIDMixin, Base):
    __tablename__ = "code_embeddings"

    repository_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False, index=True)
    chunk_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("code_chunks.id", ondelete="CASCADE"), nullable=True)
    provider: Mapped[str] = mapped_column(String(100), default="none", nullable=False)
    dimensions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    vector: Mapped[List[Any]] = mapped_column(SA_JSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CodeExecutionRun(UUIDMixin, Base):
    __tablename__ = "code_execution_runs"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True)
    task_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("code_tasks.id", ondelete="SET NULL"),
        nullable=True, index=True)
    profile: Mapped[str] = mapped_column(String(30), nullable=False)
    command: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[ExecutionStatus] = mapped_column(
        SQLEnum(ExecutionStatus, name="execution_status", create_constraint=False),
        default=ExecutionStatus.QUEUED, nullable=False)
    exit_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Storage references for (possibly large) output — never inline dumps.
    stdout_ref: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    stderr_ref: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    stdout_tail: Mapped[str] = mapped_column(Text, default="", nullable=False)
    diagnostics: Mapped[Dict[str, Any]] = mapped_column(SA_JSON, default=dict, nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CodeTestResult(UUIDMixin, Base):
    __tablename__ = "code_test_results"

    execution_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("code_execution_runs.id", ondelete="CASCADE"),
        nullable=True, index=True)
    task_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("code_tasks.id", ondelete="SET NULL"),
        nullable=True, index=True)
    suite: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    file: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # passed|failed|skipped
    duration_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CodeReview(UUIDMixin, Base):
    __tablename__ = "code_reviews"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True)
    task_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("code_tasks.id", ondelete="SET NULL"), nullable=True)
    repository_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="SET NULL"), nullable=True)
    reviewer: Mapped[str] = mapped_column(String(40), default="static", nullable=False)
    status: Mapped[ReviewStatus] = mapped_column(
        SQLEnum(ReviewStatus, name="review_status", create_constraint=False),
        default=ReviewStatus.PENDING, nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class CodeReviewFinding(UUIDMixin, Base):
    __tablename__ = "code_review_findings"

    review_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("code_reviews.id", ondelete="CASCADE"),
        nullable=False, index=True)
    severity: Mapped[ReviewSeverity] = mapped_column(
        SQLEnum(ReviewSeverity, name="review_severity", create_constraint=False),
        default=ReviewSeverity.INFO, nullable=False)
    file: Mapped[str] = mapped_column(Text, nullable=False)
    line: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    finding: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[str] = mapped_column(Text, default="", nullable=False)
    suggested_fix: Mapped[str] = mapped_column(Text, default="", nullable=False)


class CodePatch(UUIDMixin, Base):
    __tablename__ = "code_patches"

    task_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("code_tasks.id", ondelete="SET NULL"), nullable=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True)
    files: Mapped[List[Any]] = mapped_column(SA_JSON, default=list, nullable=False)
    # Storage ref for the full diff (large diffs never inline).
    diff_ref: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    insertions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    deletions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[PatchStatus] = mapped_column(
        SQLEnum(PatchStatus, name="patch_status", create_constraint=False),
        default=PatchStatus.PROPOSED, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CodeCommit(UUIDMixin, Base):
    __tablename__ = "code_commits"

    task_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("code_tasks.id", ondelete="SET NULL"), nullable=True)
    repository_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False, index=True)
    sha: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    branch: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    files: Mapped[List[Any]] = mapped_column(SA_JSON, default=list, nullable=False)
    validation: Mapped[Dict[str, Any]] = mapped_column(SA_JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CodePullRequest(UUIDMixin, Base):
    __tablename__ = "code_pull_requests"

    task_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("code_tasks.id", ondelete="SET NULL"), nullable=True)
    repository_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    branch: Mapped[str] = mapped_column(String(255), nullable=False)
    base: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[PRStatus] = mapped_column(
        SQLEnum(PRStatus, name="pr_status", create_constraint=False),
        default=PRStatus.DRAFT, nullable=False)
    url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    meta: Mapped[Dict[str, Any]] = mapped_column("metadata", SA_JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CodeIndexJob(UUIDMixin, Base):
    __tablename__ = "code_index_jobs"

    repository_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), default="QUEUED", nullable=False, index=True)
    files_indexed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    symbols_indexed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CodeEvent(UUIDMixin, Base):
    __tablename__ = "code_events"

    event_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True)
    task_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("code_tasks.id", ondelete="SET NULL"), nullable=True)
    workspace_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("code_workspaces.id", ondelete="SET NULL"), nullable=True)
    payload: Mapped[Dict[str, Any]] = mapped_column(SA_JSON, default=dict, nullable=False)
    meta: Mapped[Dict[str, Any]] = mapped_column("metadata", SA_JSON, default=dict, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
