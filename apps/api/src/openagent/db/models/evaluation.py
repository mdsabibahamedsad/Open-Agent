import uuid
from datetime import datetime
from typing import Optional, Dict, Any, TYPE_CHECKING
from sqlalchemy import String, Text, JSON, ForeignKey, Index, Enum as SQLEnum, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
import enum

from openagent.db.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from openagent.db.models.organization import Organization
    from openagent.db.models.agent_run import AgentRun


class EvaluatorType(str, enum.Enum):
    HUMAN = "human"
    LLM = "llm"
    RULE_BASED = "rule_based"
    AUTOMATED = "automated"
    COMPOSITE = "composite"


class EvaluationStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"  # legacy terminal alias (pre-MP20); new code uses PASSED/FAILED
    FAILED = "failed"
    PASSED = "passed"
    UNCERTAIN = "uncertain"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"
    ERROR = "error"


class Evaluation(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "evaluations"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    run_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    workflow_execution_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_executions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    evaluator_type: Mapped[EvaluatorType] = mapped_column(
        SQLEnum(EvaluatorType, name="evaluator_type", create_constraint=True),
        default=EvaluatorType.AUTOMATED,
        nullable=False
    )
    status: Mapped[EvaluationStatus] = mapped_column(
        SQLEnum(EvaluationStatus, name="evaluation_status", create_constraint=True),
        default=EvaluationStatus.PENDING,
        nullable=False
    )
    score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    criteria: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    result: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    # MP20 quality-control fields (all additive; historical rows stay valid).
    evaluation_type: Mapped[str] = mapped_column(String(64), nullable=False,
                                                default="TASK_SUCCESS", index=True)
    task_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    agent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    workflow_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflows.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    parent_evaluation_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("evaluations.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    attempt_number: Mapped[int] = mapped_column(nullable=False, default=0)
    decision: Mapped[Optional[str]] = mapped_column(String(30), nullable=True, index=True)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    failure_class: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    failure_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    uncertainty_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    input_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    output_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    evaluator_version: Mapped[str] = mapped_column(String(64), nullable=False,
                                                  default="evaluator-v1")
    rubric_version: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    policy_version: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    model_version: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    verification_version: Mapped[str] = mapped_column(String(64), nullable=False,
                                                     default="verification-v1")

    # Reverse side of Organization.evaluations (same pre-existing gap as Approval).
    organization: Mapped["Organization"] = relationship(back_populates="evaluations")

    __table_args__ = (
        Index("ix_evaluations_organization_id", "organization_id"),
        Index("ix_evaluations_run_id", "run_id"),
        Index("ix_evaluations_workflow_execution_id", "workflow_execution_id"),
        Index("ix_evaluations_evaluator_type", "evaluator_type"),
        Index("ix_evaluations_status", "status"),
        Index("ix_evaluations_organization_created", "organization_id", "created_at"),
        Index("ix_evaluations_org_type", "organization_id", "evaluation_type"),
        Index("ix_evaluations_org_decision", "organization_id", "decision"),
        Index("ix_evaluations_task", "task_id"),
        Index("ix_evaluations_parent", "parent_evaluation_id"),
    )


def _org_fk() -> Any:
    return mapped_column(UUID(as_uuid=True),
                         ForeignKey("organizations.id", ondelete="CASCADE"),
                         nullable=False, index=True)


class EvaluationEvidence(TimestampMixin, UUIDMixin, Base):
    """Immutable captured evidence (content_hash detects post-capture edits)."""

    __tablename__ = "evaluation_evidence"

    evaluation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("evaluations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    organization_id: Mapped[uuid.UUID] = _org_fk()
    evidence_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    trust: Mapped[str] = mapped_column(String(32), nullable=False, default="UNVERIFIED",
                                       index=True)
    content: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    source: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    source_type: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    source_id: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    captured_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    __table_args__ = (
        Index("ix_evaluation_evidence_eval", "evaluation_id"),
        Index("ix_evaluation_evidence_org_trust", "organization_id", "trust"),
    )


class EvaluationResult(TimestampMixin, UUIDMixin, Base):
    """One immutable per-evaluator vote (never updated; disagreement visible)."""

    __tablename__ = "evaluation_results"

    evaluation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("evaluations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    organization_id: Mapped[uuid.UUID] = _org_fk()
    source: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    decision: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    reason_codes: Mapped[Dict[str, Any]] = mapped_column(JSON, default=list, nullable=False)
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    model: Mapped[str] = mapped_column(String(255), nullable=False, default="")

    __table_args__ = (
        Index("ix_evaluation_results_eval", "evaluation_id"),
        Index("ix_evaluation_results_org_decision", "organization_id", "decision"),
    )


class VerificationCheck(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "verification_checks"

    evaluation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("evaluations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    organization_id: Mapped[uuid.UUID] = _org_fk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    passed: Mapped[bool] = mapped_column(nullable=False, default=False, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    required: Mapped[bool] = mapped_column(nullable=False, default=True)
    critical_safety: Mapped[bool] = mapped_column(nullable=False, default=False)
    evidence_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")

    __table_args__ = (Index("ix_verification_checks_eval", "evaluation_id"),)


class EvaluationDisagreement(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "evaluation_disagreements"

    evaluation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("evaluations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    organization_id: Mapped[uuid.UUID] = _org_fk()
    votes: Mapped[Dict[str, Any]] = mapped_column(JSON, default=list, nullable=False)
    policy: Mapped[str] = mapped_column(String(64), nullable=False, default="CONSERVATIVE_FAIL")
    resolution: Mapped[str] = mapped_column(String(64), nullable=False, default="")

    __table_args__ = (Index("ix_evaluation_disagreements_eval", "evaluation_id"),)


class EvaluationRubric(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "evaluation_rubrics"

    organization_id: Mapped[uuid.UUID] = _org_fk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    criteria: Mapped[Dict[str, Any]] = mapped_column(JSON, default=list, nullable=False)
    quality_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.7)
    confidence_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.6)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True, index=True)
    version: Mapped[int] = mapped_column(nullable=False, default=1)

    __table_args__ = (
        Index("ix_evaluation_rubrics_org_active", "organization_id", "is_active"),
        Index("ix_evaluation_rubrics_org_name", "organization_id", "name"),
    )


class EvaluationRubricVersion(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "evaluation_rubric_versions"

    rubric_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("evaluation_rubrics.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    organization_id: Mapped[uuid.UUID] = _org_fk()
    version: Mapped[int] = mapped_column(nullable=False)
    criteria: Mapped[Dict[str, Any]] = mapped_column(JSON, default=list, nullable=False)

    __table_args__ = (Index("ix_evaluation_rubric_versions_rubric", "rubric_id"),)


class CorrectionPlan(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "correction_plans"

    evaluation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("evaluations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    organization_id: Mapped[uuid.UUID] = _org_fk()
    attempt_number: Mapped[int] = mapped_column(nullable=False, default=1)
    failure_class: Mapped[str] = mapped_column(String(40), nullable=False, default="UNKNOWN")
    root_cause: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    proposed_strategy: Mapped[str] = mapped_column(String(40), nullable=False)
    changes: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False, default="LOW")
    approval_required: Mapped[bool] = mapped_column(nullable=False, default=False)
    approval_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("approvals.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="proposed",
                                        index=True)
    result: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    __table_args__ = (
        Index("ix_correction_plans_eval", "evaluation_id"),
        Index("ix_correction_plans_org_status", "organization_id", "status"),
    )


class CorrectionAttempt(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "correction_attempts"

    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("correction_plans.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    evaluation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("evaluations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    organization_id: Mapped[uuid.UUID] = _org_fk()
    attempt_number: Mapped[int] = mapped_column(nullable=False, default=1)
    action: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    outcome: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending",
                                        index=True)
    failure_signature: Mapped[str] = mapped_column(String(64), nullable=False, default="")

    __table_args__ = (Index("ix_correction_attempts_plan", "plan_id"),)


class EvaluationFeedback(TimestampMixin, UUIDMixin, Base):
    """Human reviewer feedback. Never rewrites history (append-only)."""

    __tablename__ = "evaluation_feedback"

    evaluation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("evaluations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    organization_id: Mapped[uuid.UUID] = _org_fk()
    reviewer_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    verdict: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    feedback: Mapped[str] = mapped_column(Text, nullable=False, default="")

    __table_args__ = (Index("ix_evaluation_feedback_eval", "evaluation_id"),)


class QualityGate(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "quality_gates"

    organization_id: Mapped[uuid.UUID] = _org_fk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    required_checks: Mapped[Dict[str, Any]] = mapped_column(JSON, default=list, nullable=False)
    thresholds: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    failure_behavior: Mapped[str] = mapped_column(String(30), nullable=False, default="FAIL")
    approval_required: Mapped[bool] = mapped_column(nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True, index=True)
    version: Mapped[int] = mapped_column(nullable=False, default=1)

    __table_args__ = (
        Index("ix_quality_gates_org_active", "organization_id", "is_active"),
        Index("ix_quality_gates_org_name", "organization_id", "name"),
    )


class Benchmark(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "benchmarks"

    organization_id: Mapped[uuid.UUID] = _org_fk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    dataset: Mapped[Dict[str, Any]] = mapped_column(JSON, default=list, nullable=False)
    criteria: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True, index=True)

    __table_args__ = (Index("ix_benchmarks_org_active", "organization_id", "is_active"),)


class BenchmarkRun(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "benchmark_runs"

    benchmark_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("benchmarks.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    organization_id: Mapped[uuid.UUID] = _org_fk()
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="running",
                                        index=True)
    scores: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    items: Mapped[Dict[str, Any]] = mapped_column(JSON, default=list, nullable=False)
    baseline_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("benchmark_runs.id", ondelete="SET NULL"),
        nullable=True)
    regression: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    __table_args__ = (Index("ix_benchmark_runs_benchmark", "benchmark_id"),)