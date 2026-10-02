"""Evaluator, verification, self-correction & quality-control API (MP20).

Tenant isolation is enforced by comparing the path organization_id against
the authenticated org context. RBAC reuses existing evaluation:* permissions
plus evaluation:decide/admin. Terminal evaluation states are immutable: failed
evaluations never silently become success — correction creates NEW linked
evaluations. There is intentionally no force_success/disable_evaluation API.
"""

from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.api.dependencies import get_current_org_context
from openagent.db.models.evaluation import (
    Benchmark,
    BenchmarkRun,
    CorrectionAttempt,
    CorrectionPlan,
    Evaluation,
    EvaluationDisagreement,
    EvaluationEvidence,
    EvaluationFeedback,
    EvaluationResult,
    EvaluationRubric,
    EvaluationRubricVersion,
    EvaluationStatus,
    QualityGate,
    VerificationCheck,
)
from openagent.db.session import get_db
from openagent.evaluator.benchmarks import BenchmarkError
from openagent.evaluator.correction import (
    CorrectionBudget,
    CorrectionError,
    SelfCorrectionEngine,
    check_budget,
)
from openagent.evaluator.criteria import BUILTIN_RUBRICS, parse_criteria
from openagent.evaluator.engine import CreateEvaluation, EvaluatorEngine, EvaluatorError
from openagent.evaluator.gates import (
    BUILTIN_GATES,
    evaluate_gate,
    get_builtin_gate,
)
from openagent.evaluator.metrics import inc as metrics_inc
from openagent.evaluator.types import (
    CorrectionStrategy,
    is_known_evaluation_type,
)
from openagent.services.authorization import AuthorizationContext, AuthorizationService

router = APIRouter(prefix="/organizations/{organization_id}/evaluations", tags=["evaluations"])
rubrics_router = APIRouter(prefix="/organizations/{organization_id}/evaluation-rubrics",
                           tags=["evaluation-rubrics"])
gates_router = APIRouter(prefix="/organizations/{organization_id}/quality-gates",
                         tags=["quality-gates"])
benchmarks_router = APIRouter(prefix="/organizations/{organization_id}/benchmarks",
                              tags=["benchmarks"])
quality_router = APIRouter(prefix="/organizations/{organization_id}/quality",
                           tags=["quality"])


def _org_or_403(ctx: AuthorizationContext, organization_id: UUID) -> None:
    if ctx.organization_id != organization_id and not ctx.is_platform_owner:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Cross-organization access denied")


def _err(exc: Exception) -> HTTPException:
    code_map = {"NOT_FOUND": 404, "CROSS_TENANT": 403, "SELF_EVALUATION": 403,
                "IMMUTABLE": 409, "INVALID_STATE": 409, "ILLEGAL_TRANSITION": 409,
                "INVALID_VOTE": 400, "INVALID_VERDICT": 400,
                "EVIDENCE_TAMPERED": 409, "NOTHING_TO_CORRECT": 409,
                "FORBIDDEN_STRATEGY": 403}
    if isinstance(exc, (BenchmarkError, CorrectionError)):
        return HTTPException(status_code=code_map.get(exc.code, 400), detail=str(exc))
    return HTTPException(status_code=code_map.get(exc.code, 400), detail=str(exc))


def _serialize(e: Evaluation) -> dict[str, Any]:
    return {"id": str(e.id), "organization_id": str(e.organization_id),
            "evaluation_type": e.evaluation_type,
            "status": str(e.status.value if hasattr(e.status, "value") else e.status).upper(),
            "evaluator_type": str(e.evaluator_type.value if hasattr(e.evaluator_type, "value")
                                  else e.evaluator_type),
            "task_id": e.task_id, "agent_id": str(e.agent_id) if e.agent_id else None,
            "agent_run_id": str(e.run_id) if e.run_id else None,
            "workflow_id": str(e.workflow_id) if e.workflow_id else None,
            "workflow_execution_id": str(e.workflow_execution_id)
            if e.workflow_execution_id else None,
            "parent_evaluation_id": str(e.parent_evaluation_id)
            if e.parent_evaluation_id else None,
            "attempt_number": e.attempt_number,
            "decision": e.decision, "score": e.score, "confidence": e.confidence,
            "failure_class": e.failure_class, "failure_reason": e.failure_reason,
            "uncertainty_reason": e.uncertainty_reason,
            "criteria": e.criteria or {}, "result": e.result or {},
            "input_hash": e.input_hash, "output_hash": e.output_hash,
            "evaluator_version": e.evaluator_version,
            "rubric_version": e.rubric_version, "policy_version": e.policy_version,
            "model_version": e.model_version,
            "verification_version": e.verification_version,
            "created_at": e.created_at.isoformat() if e.created_at else None,
            "completed_at": e.completed_at.isoformat() if e.completed_at else None}


# -- schemas ---------------------------------------------------------------
class EvidenceInput(BaseModel):
    evidence_type: str = Field(min_length=1, max_length=64)
    content: dict[str, Any] = Field(default_factory=dict)
    source: str = Field(default="", max_length=256)
    source_type: str = Field(default="", max_length=64)
    source_id: str = Field(default="", max_length=256)
    tool_id: str = Field(default="", max_length=256)
    trust: Optional[str] = Field(default=None, max_length=32)


class EvaluationCreate(BaseModel):
    evaluation_type: str = Field(default="TASK_SUCCESS", max_length=64)
    task_id: Optional[str] = Field(default=None, max_length=255)
    agent_id: Optional[UUID] = None
    agent_run_id: Optional[UUID] = None
    workflow_id: Optional[UUID] = None
    workflow_execution_id: Optional[UUID] = None
    evaluator_type: str = Field(default="automated", max_length=32)
    criteria: Any = None
    goal: str = Field(default="", max_length=4000)
    input_ref: Any = None
    output_ref: Any = None
    evidence: list[EvidenceInput] = Field(default_factory=list)
    quality_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    confidence_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    generator_model: str = Field(default="", max_length=255)


class CheckInput(BaseModel):
    kind: str = Field(min_length=1, max_length=64)
    name: str = Field(default="", max_length=200)
    target: Any = None
    evidence_type: str = Field(default="", max_length=64)
    evidence_id: str = Field(default="", max_length=64)
    params: dict[str, Any] = Field(default_factory=dict)
    required: bool = True
    critical_safety: bool = False
    min_trust: str = Field(default="", max_length=32)


class VerifyInput(BaseModel):
    checks: list[CheckInput] = Field(min_length=1)


class VoteInput(BaseModel):
    source: str = Field(min_length=1, max_length=128)
    decision: str = Field(pattern="^(?i)(pass|fail|uncertain)$")
    score: float = Field(ge=0.0, le=100.0)
    confidence: float = Field(ge=0.0, le=100.0)
    reason_codes: list[str] = Field(default_factory=list)
    weight: float = Field(default=1.0, ge=0.0, le=10.0)
    model: str = Field(default="", max_length=255)


class LLMVoteInput(BaseModel):
    model: str = Field(min_length=1, max_length=255)
    generator_model: str = Field(default="", max_length=255)
    allow_self_evaluation: bool = False
    source: str = Field(default="llm", max_length=128)
    max_tokens: int = Field(default=1024, ge=128, le=4096)


class FinalizeInput(BaseModel):
    quality_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    confidence_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    disagreement_policy: str = Field(default="CONSERVATIVE_FAIL", max_length=32)
    request_human_on_uncertain: bool = True


class RetryInput(BaseModel):
    reason: str = Field(default="", max_length=2000)


class CorrectInput(BaseModel):
    strategy: Optional[str] = Field(default=None, max_length=40)
    changes: dict[str, Any] = Field(default_factory=dict)
    root_cause: dict[str, Any] = Field(default_factory=dict)
    risk_level: str = Field(default="LOW", max_length=20)


class AttemptInput(BaseModel):
    action: dict[str, Any] = Field(default_factory=dict)
    outcome: dict[str, Any] = Field(default_factory=dict)
    failure: Optional[str] = Field(default=None, max_length=2000)
    failure_class: Optional[str] = Field(default=None, max_length=40)
    usage: dict[str, Any] = Field(default_factory=dict)
    budget: dict[str, Any] = Field(default_factory=dict)


class FeedbackInput(BaseModel):
    verdict: str = Field(pattern="^(correct|incorrect|partially_correct)$")
    reason: str = Field(default="", max_length=4000)
    feedback: str = Field(default="", max_length=4000)


def _to_records(items: list[EvidenceInput], organization_id: UUID,
                execution_id: str = "", agent_id: str = ""):
    from openagent.evaluator.evidence import EvidenceCollector
    collector = EvidenceCollector(organization_id=str(organization_id),
                                  execution_id=execution_id, agent_id=agent_id)
    for item in items:
        try:
            etype = EvidenceType(item.evidence_type.upper())
        except ValueError:
            raise HTTPException(status_code=400,
                                detail=f"Unknown evidence type '{item.evidence_type}'")
        trust = None
        if item.trust:
            try:
                trust = EvidenceTrust(item.trust.upper())
            except ValueError:
                raise HTTPException(status_code=400,
                                    detail=f"Unknown evidence trust '{item.trust}'")
        collector.add(etype, item.content, source=item.source,
                      source_type=item.source_type, source_id=item.source_id,
                      tool_id=item.tool_id, trust=trust)
    return collector.records()


# -- evaluations -------------------------------------------------------------
@router.get("", summary="List evaluations")
async def list_evaluations(organization_id: UUID,
                           status_filter: Optional[str] = Query(default=None, alias="status"),
                           decision: Optional[str] = None,
                           evaluation_type: Optional[str] = None,
                           agent_id: Optional[UUID] = None,
                           workflow_id: Optional[UUID] = None,
                           task_id: Optional[str] = None,
                           limit: int = Query(default=50, ge=1, le=200),
                           offset: int = Query(default=0, ge=0),
                           db: AsyncSession = Depends(get_db),
                           ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_permission(ctx, "evaluation:read")
    q = select(Evaluation).where(Evaluation.organization_id == organization_id)
    if status_filter:
        try:
            q = q.where(Evaluation.status == EvaluationStatus(status_filter.lower()))
        except ValueError:
            raise HTTPException(status_code=400, detail="Unknown status")
    if decision:
        q = q.where(Evaluation.decision == decision.upper())
    if evaluation_type:
        q = q.where(Evaluation.evaluation_type == evaluation_type.upper())
    if agent_id:
        q = q.where(Evaluation.agent_id == agent_id)
    if workflow_id:
        q = q.where(Evaluation.workflow_id == workflow_id)
    if task_id:
        q = q.where(Evaluation.task_id == task_id)
    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar() or 0
    rows = (await db.execute(q.order_by(Evaluation.created_at.desc())
                             .limit(limit).offset(offset))).scalars().all()
    return {"items": [_serialize(e) for e in rows], "total": total,
            "limit": limit, "offset": offset}


@router.post("", status_code=201, summary="Create evaluation (agent claims are not proof)")
async def create_evaluation(organization_id: UUID, body: EvaluationCreate,
                            db: AsyncSession = Depends(get_db),
                            ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_permission(ctx, "evaluation:create")
    if not is_known_evaluation_type(body.evaluation_type):
        raise HTTPException(status_code=400, detail="Unknown evaluation type")
    try:
        evaluation = await EvaluatorEngine(db).create_evaluation(CreateEvaluation(
            organization_id=organization_id,
            evaluation_type=body.evaluation_type.upper(),
            task_id=body.task_id, agent_id=body.agent_id,
            agent_run_id=body.agent_run_id, workflow_id=body.workflow_id,
            workflow_execution_id=body.workflow_execution_id,
            evaluator_type=body.evaluator_type, criteria=body.criteria,
            goal=body.goal, input_ref=body.input_ref, output_ref=body.output_ref,
            model_version=body.generator_model or None,
            quality_threshold=body.quality_threshold,
            confidence_threshold=body.confidence_threshold),
            _to_records(body.evidence, organization_id,
                        "", str(body.agent_id or "")))
        await db.commit()
    except EvaluatorError as exc:
        raise _err(exc)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    metrics_inc("evaluations_total")
    return _serialize(evaluation)


async def _detail(organization_id: UUID, evaluation_id: UUID, db: AsyncSession):
    result = await db.execute(select(Evaluation).where(Evaluation.id == evaluation_id))
    evaluation = result.scalar_one_or_none()
    if evaluation is None or evaluation.organization_id != organization_id:
        raise HTTPException(status_code=404, detail="Evaluation not found")
    evidence = (await db.execute(select(EvaluationEvidence).where(
        EvaluationEvidence.evaluation_id == evaluation_id))).scalars().all()
    checks = (await db.execute(select(VerificationCheck).where(
        VerificationCheck.evaluation_id == evaluation_id))).scalars().all()
    votes = (await db.execute(select(EvaluationResult).where(
        EvaluationResult.evaluation_id == evaluation_id))).scalars().all()
    plans = (await db.execute(select(CorrectionPlan).where(
        CorrectionPlan.evaluation_id == evaluation_id))).scalars().all()
    feedback = (await db.execute(select(EvaluationFeedback).where(
        EvaluationFeedback.evaluation_id == evaluation_id))).scalars().all()
    disagreements = (await db.execute(select(EvaluationDisagreement).where(
        EvaluationDisagreement.evaluation_id == evaluation_id))).scalars().all()
    data = _serialize(evaluation)
    data["evidence"] = [{"id": str(r.id), "evidence_type": r.evidence_type,
                         "trust": r.trust, "content": r.content,
                         "source": r.source, "source_type": r.source_type,
                         "content_hash": r.content_hash,
                         "captured_at": r.captured_at.isoformat()
                         if r.captured_at else None} for r in evidence]
    data["checks"] = [{"name": c.name, "kind": c.kind, "passed": c.passed,
                       "reason": c.reason, "required": c.required,
                       "critical_safety": c.critical_safety} for c in checks]
    data["votes"] = [{"source": v.source, "decision": v.decision,
                      "score": v.score, "confidence": v.confidence,
                      "reason_codes": v.reason_codes, "weight": v.weight,
                      "model": v.model} for v in votes]
    data["correction_plans"] = [{"id": str(p.id), "strategy": p.proposed_strategy,
                                 "status": p.status,
                                 "failure_class": p.failure_class,
                                 "approval_required": p.approval_required,
                                 "approval_id": str(p.approval_id)
                                 if p.approval_id else None,
                                 "attempt_number": p.attempt_number} for p in plans]
    data["feedback"] = [{"verdict": f.verdict, "reason": f.reason,
                         "at": f.created_at.isoformat() if f.created_at else None}
                        for f in feedback]
    data["disagreements"] = [{"policy": d.policy, "resolution": d.resolution,
                              "votes": d.votes} for d in disagreements]
    return data


@router.get("/{evaluation_id}", summary="Get evaluation detail with evidence")
async def get_evaluation(organization_id: UUID, evaluation_id: UUID,
                         db: AsyncSession = Depends(get_db),
                         ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_permission(ctx, "evaluation:read")
    return await _detail(organization_id, evaluation_id, db)


@router.post("/{evaluation_id}/verify", summary="Run deterministic verification checks")
async def verify_evaluation(organization_id: UUID, evaluation_id: UUID,
                            body: VerifyInput,
                            db: AsyncSession = Depends(get_db),
                            ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_permission(ctx, "evaluation:decide")
    try:
        results = await EvaluatorEngine(db).run_checks(
            evaluation_id, organization_id=organization_id,
            checks=[{"kind": c.kind, "name": c.name or c.kind, "target": c.target,
                     "evidence_type": c.evidence_type,
                     "evidence_id": c.evidence_id, "params": c.params,
                     "required": c.required,
                     "critical_safety": c.critical_safety,
                     "min_trust": c.min_trust} for c in body.checks])
        await db.commit()
    except EvaluatorError as exc:
        raise _err(exc)
    metrics_inc("deterministic_checks_total", len(results))
    metrics_inc("deterministic_checks_passed",
                sum(1 for r in results if r.passed))
    return {"checks": [{"name": r.name, "passed": r.passed, "reason": r.reason,
                        "required": r.required} for r in results]}


@router.post("/{evaluation_id}/vote", summary="Record an evaluator vote (immutable)")
async def record_vote(organization_id: UUID, evaluation_id: UUID, body: VoteInput,
                      db: AsyncSession = Depends(get_db),
                      ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_permission(ctx, "evaluation:decide")
    try:
        vote = await EvaluatorEngine(db).record_vote(
            evaluation_id, organization_id=organization_id, source=body.source,
            decision=body.decision, score=body.score, confidence=body.confidence,
            reason_codes=body.reason_codes, weight=body.weight, model=body.model)
        await db.commit()
    except EvaluatorError as exc:
        raise _err(exc)
    return {"source": vote.source, "decision": vote.decision,
            "score": vote.score, "confidence": vote.confidence}


@router.post("/{evaluation_id}/llm-vote", summary="LLM vote via registered provider")
async def llm_vote(organization_id: UUID, evaluation_id: UUID, body: LLMVoteInput,
                   db: AsyncSession = Depends(get_db),
                   ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_permission(ctx, "evaluation:decide")
    from openagent.evaluator.config import EvaluatorSettings
    settings = EvaluatorSettings()
    if not settings.ENABLE_LLM_EVALUATION:
        raise HTTPException(status_code=403,
                            detail="LLM evaluation is disabled by configuration")
    from openagent.runtime.agent_core import model_provider_registry
    provider = model_provider_registry.get_for_model(body.model)
    if provider is None:
        raise HTTPException(status_code=501,
                            detail=f"No registered provider for model '{body.model}'; "
                                   "deterministic verification remains available")
    # Token budget enforced pre-call (cost accounted from usage post-call).
    max_tokens = min(body.max_tokens, settings.MAX_EVALUATION_TOKENS)
    if max_tokens < 128:
        raise HTTPException(status_code=403,
                            detail="Evaluation token budget exhausted")
    try:
        parsed = await EvaluatorEngine(db).run_llm_vote(
            evaluation_id, organization_id=organization_id, provider=provider,
            model=body.model, generator_model=body.generator_model,
            allow_self_evaluation=body.allow_self_evaluation and settings.ALLOW_SELF_EVALUATION,
            source=body.source, max_tokens=max_tokens)
        await db.commit()
    except EvaluatorError as exc:
        raise _err(exc)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    metrics_inc("llm_votes_total")
    return parsed


@router.post("/{evaluation_id}/finalize", summary="Combine votes+checks into a decision")
async def finalize_evaluation(organization_id: UUID, evaluation_id: UUID,
                              body: FinalizeInput,
                              db: AsyncSession = Depends(get_db),
                              ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_permission(ctx, "evaluation:decide")
    try:
        outcome = await EvaluatorEngine(db).finalize(
            evaluation_id, organization_id=organization_id,
            quality_threshold=body.quality_threshold,
            confidence_threshold=body.confidence_threshold,
            disagreement_policy=body.disagreement_policy,
            request_human_on_uncertain=body.request_human_on_uncertain)
        await db.commit()
    except EvaluatorError as exc:
        raise _err(exc)
    metrics_inc(f"evaluations_{outcome['status'].lower()}"
                if outcome["status"] in ("PASSED", "FAILED", "UNCERTAIN") else "evaluations_error")
    if outcome["status"] == "UNCERTAIN" and outcome.get("approval_id"):
        metrics_inc("human_reviews_total")
    return outcome


@router.post("/{evaluation_id}/retry", summary="Retry via a NEW linked evaluation")
async def retry_evaluation(organization_id: UUID, evaluation_id: UUID,
                           body: RetryInput,
                           db: AsyncSession = Depends(get_db),
                           ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_permission(ctx, "evaluation:decide")
    result = await db.execute(select(Evaluation).where(Evaluation.id == evaluation_id))
    source = result.scalar_one_or_none()
    if source is None or source.organization_id != organization_id:
        raise HTTPException(status_code=404, detail="Evaluation not found")
    try:
        child = await EvaluatorEngine(db).create_evaluation(CreateEvaluation(
            organization_id=organization_id,
            evaluation_type=source.evaluation_type,
            task_id=source.task_id, agent_id=source.agent_id,
            agent_run_id=source.run_id, workflow_id=source.workflow_id,
            workflow_execution_id=source.workflow_execution_id,
            evaluator_type=str(source.evaluator_type.value
                               if hasattr(source.evaluator_type, "value")
                               else source.evaluator_type),
            criteria=source.criteria, goal="",
            parent_evaluation_id=source.id,
            attempt_number=int(source.attempt_number or 0) + 1,
            model_version=source.model_version))
        await db.commit()
    except EvaluatorError as exc:
        raise _err(exc)
    metrics_inc("retries_total")
    return {"evaluation_id": str(child.id), "parent_id": str(source.id),
            "attempt_number": child.attempt_number, "reason": body.reason}


@router.post("/{evaluation_id}/correct", summary="Build a correction plan")
async def correct_evaluation(organization_id: UUID, evaluation_id: UUID,
                             body: CorrectInput,
                             db: AsyncSession = Depends(get_db),
                             ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_permission(ctx, "evaluation:decide")
    from openagent.evaluator.config import EvaluatorSettings
    if not EvaluatorSettings().ENABLE_SELF_CORRECTION:
        raise HTTPException(status_code=403, detail="Self-correction is disabled")
    if body.strategy:
        try:
            CorrectionStrategy(body.strategy.upper())
        except ValueError:
            raise HTTPException(status_code=400,
                                detail=f"Unknown strategy '{body.strategy}'")
    try:
        plan = await SelfCorrectionEngine(db).build_plan(
            evaluation_id, organization_id=organization_id,
            strategy=body.strategy.upper() if body.strategy else None,
            changes=body.changes, root_cause=body.root_cause,
            risk_level=body.risk_level)
        await db.commit()
    except EvaluatorError as exc:
        raise _err(exc)
    except CorrectionError as exc:
        raise _err(exc)
    metrics_inc("corrections_total")
    return {"plan_id": str(plan.id), "strategy": plan.proposed_strategy,
            "failure_class": plan.failure_class,
            "approval_required": plan.approval_required, "status": plan.status}


@router.post("/{evaluation_id}/feedback", summary="Append-only human feedback")
async def submit_feedback(organization_id: UUID, evaluation_id: UUID,
                          body: FeedbackInput,
                          db: AsyncSession = Depends(get_db),
                          ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_permission(ctx, "evaluation:create")
    try:
        row = await EvaluatorEngine(db).submit_feedback(
            evaluation_id, organization_id=organization_id,
            reviewer_id=ctx.user_id, verdict=body.verdict,
            reason=body.reason, feedback=body.feedback)
        await db.commit()
    except EvaluatorError as exc:
        raise _err(exc)
    metrics_inc("feedback_total")
    return {"verdict": row.verdict}


@router.get("/{evaluation_id}/evidence", summary="List captured evidence")
async def list_evidence(organization_id: UUID, evaluation_id: UUID,
                        db: AsyncSession = Depends(get_db),
                        ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_permission(ctx, "evaluation:read")
    data = await _detail(organization_id, evaluation_id, db)
    return {"evaluation_id": str(evaluation_id), "evidence": data["evidence"]}


@router.get("/{evaluation_id}/history", summary="Votes, checks, plans, feedback timeline")
async def evaluation_history(organization_id: UUID, evaluation_id: UUID,
                             db: AsyncSession = Depends(get_db),
                             ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_permission(ctx, "evaluation:read")
    data = await _detail(organization_id, evaluation_id, db)
    attempts = (await db.execute(select(CorrectionAttempt).where(
        CorrectionAttempt.evaluation_id == evaluation_id))).scalars().all()
    return {"evaluation_id": str(evaluation_id),
            "votes": data["votes"], "checks": data["checks"],
            "plans": data["correction_plans"], "feedback": data["feedback"],
            "disagreements": data["disagreements"],
            "attempts": [{"plan_id": str(a.plan_id),
                          "attempt_number": a.attempt_number,
                          "status": a.status,
                          "outcome": a.outcome} for a in attempts]}


# -- correction attempts (record-only; server owns budget/loop verdicts) -------
attempts_router = APIRouter(prefix="/organizations/{organization_id}/correction-plans",
                            tags=["corrections"])


class AttemptRecord(BaseModel):
    action: dict[str, Any] = Field(default_factory=dict)
    outcome: dict[str, Any] = Field(default_factory=dict)
    failure: Optional[str] = Field(default=None, max_length=2000)
    failure_class: Optional[str] = Field(default=None, max_length=40)
    usage: dict[str, Any] = Field(default_factory=dict)
    budget: dict[str, Any] = Field(default_factory=dict)


@attempts_router.get("", summary="List correction plans")
async def list_plans(organization_id: UUID,
                     status_filter: Optional[str] = Query(default=None, alias="status"),
                     limit: int = Query(default=50, ge=1, le=200),
                     offset: int = Query(default=0, ge=0),
                     db: AsyncSession = Depends(get_db),
                     ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_permission(ctx, "evaluation:read")
    q = select(CorrectionPlan).where(CorrectionPlan.organization_id == organization_id)
    if status_filter:
        q = q.where(CorrectionPlan.status == status_filter.lower())
    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar() or 0
    rows = (await db.execute(q.order_by(CorrectionPlan.created_at.desc())
                             .limit(limit).offset(offset))).scalars().all()
    return {"items": [{"id": str(p.id), "evaluation_id": str(p.evaluation_id),
                       "strategy": p.proposed_strategy, "status": p.status,
                       "failure_class": p.failure_class,
                       "approval_required": p.approval_required,
                       "attempt_number": p.attempt_number} for p in rows],
            "total": total}


@attempts_router.post("/{plan_id}/attempt", summary="Record a bounded correction attempt")
async def record_attempt(organization_id: UUID, plan_id: UUID, body: AttemptRecord,
                         db: AsyncSession = Depends(get_db),
                         ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_permission(ctx, "evaluation:decide")
    # Caller budgets are clamped to server policy: callers can tighten bounds
    # but never widen them beyond safe defaults.
    from openagent.evaluator.config import EvaluatorSettings
    server_cycles = EvaluatorSettings().MAX_CORRECTION_CYCLES
    safe_defaults = CorrectionBudget(max_correction_cycles=server_cycles)
    supplied = {k: v for k, v in (body.budget or {}).items()
                if k in CorrectionBudget.__dataclass_fields__}
    merged = {}
    for field_name in CorrectionBudget.__dataclass_fields__:
        default = getattr(safe_defaults, field_name)
        try:
            asked = float(supplied.get(field_name, default))
        except (TypeError, ValueError):
            asked = float(default)
        merged[field_name] = min(float(default), asked)
    budget = CorrectionBudget(**merged)
    exhausted = check_budget(budget, body.usage or {})
    if exhausted:
        raise HTTPException(status_code=409, detail=exhausted)
    # Server-side loop detection over recorded outcomes (no execution here).
    from openagent.evaluator.correction import failure_signature
    prior = (await db.execute(select(CorrectionAttempt).where(
        CorrectionAttempt.plan_id == plan_id))).scalars().all()
    signatures = [a.failure_signature for a in prior if a.failure_signature]
    signature = ""
    if body.failure:
        from openagent.db.models.evaluation import CorrectionPlan as PlanModel
        plan = (await db.execute(select(PlanModel).where(PlanModel.id == plan_id)
                                 )).scalar_one_or_none()
        if plan is None or plan.organization_id != organization_id:
            raise HTTPException(status_code=404, detail="Correction plan not found")
        signature = failure_signature(
            failure_class=body.failure_class or str(plan.failure_class),
            reason=body.failure,
            target_hash=str((body.action or {}).get("target_hash", "")),
            strategy=str(plan.proposed_strategy))
        if signatures.count(signature) >= 2:
            raise HTTPException(status_code=409,
                                detail="Correction loop detected; STOP required")
    from openagent.db.models.evaluation import CorrectionAttempt as AttemptModel
    plan_lookup = (await db.execute(select(CorrectionPlan).where(
        CorrectionPlan.id == plan_id))).scalar_one_or_none()
    if plan_lookup is None or plan_lookup.organization_id != organization_id:
        raise HTTPException(status_code=404, detail="Correction plan not found")
    attempt = AttemptModel(
        plan_id=plan_lookup.id, evaluation_id=plan_lookup.evaluation_id,
        organization_id=organization_id,
        attempt_number=len(prior) + 1, action=dict(body.action or {}),
        outcome=dict(body.outcome or {}),
        status="succeeded" if not body.failure else "failed",
        failure_signature=signature if body.failure else "")
    if body.failure:
        plan_lookup.status = "proposed"
        plan_lookup.result = {"last_failure": (body.failure or "")[:1000]}
    else:
        plan_lookup.status = "succeeded"
        plan_lookup.result = {"outcome": dict(body.outcome or {})}
    db.add(attempt)
    await db.commit()
    if not body.failure:
        metrics_inc("corrections_succeeded")
    return {"attempt_id": str(attempt.id), "status": attempt.status,
            "verdict": "DONE" if not body.failure else "RETRY"}


# -- rubrics -------------------------------------------------------------------
class RubricCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    criteria: list[dict[str, Any]] = Field(default_factory=list)
    quality_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    confidence_threshold: float = Field(default=0.6, ge=0.0, le=1.0)


class RubricUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    criteria: Optional[list[dict[str, Any]]] = None
    quality_threshold: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    confidence_threshold: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    is_active: Optional[bool] = None


def _serialize_rubric(r: EvaluationRubric) -> dict[str, Any]:
    return {"id": str(r.id), "name": r.name, "criteria": r.criteria,
            "quality_threshold": r.quality_threshold,
            "confidence_threshold": r.confidence_threshold,
            "is_active": r.is_active, "version": r.version}


@rubrics_router.get("", summary="List rubrics (built-ins included)")
async def list_rubrics(organization_id: UUID,
                       db: AsyncSession = Depends(get_db),
                       ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_permission(ctx, "evaluation:read")
    rows = (await db.execute(select(EvaluationRubric).where(
        EvaluationRubric.organization_id == organization_id))).scalars().all()
    builtins = [{"id": f"builtin:{name}", "name": rubric.name,
                 "criteria": [{"name": c.name, "description": c.description,
                               "weight": c.weight, "minimum_score": c.minimum_score,
                               "required": c.required, "method": c.method,
                               "params": c.params} for c in rubric.criteria],
                 "quality_threshold": rubric.quality_threshold,
                 "confidence_threshold": rubric.confidence_threshold,
                 "is_active": True, "version": rubric.version}
                for name, rubric in BUILTIN_RUBRICS.items()]
    return {"items": builtins + [_serialize_rubric(r) for r in rows]}


@rubrics_router.post("", status_code=201, summary="Create rubric (versioned)")
async def create_rubric(organization_id: UUID, body: RubricCreate,
                        db: AsyncSession = Depends(get_db),
                        ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_permission(ctx, "evaluation:admin")
    try:
        criteria = parse_criteria(body.criteria)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    rubric = EvaluationRubric(
        organization_id=organization_id, name=body.name,
        criteria=[{"name": c.name, "description": c.description, "weight": c.weight,
                   "minimum_score": c.minimum_score, "required": c.required,
                   "method": c.method, "params": c.params} for c in criteria],
        quality_threshold=body.quality_threshold,
        confidence_threshold=body.confidence_threshold, version=1)
    db.add(rubric)
    await db.flush()
    db.add(EvaluationRubricVersion(rubric_id=rubric.id,
                                  organization_id=organization_id, version=1,
                                  criteria=rubric.criteria))
    await db.commit()
    return _serialize_rubric(rubric)


@rubrics_router.patch("/{rubric_id}", summary="Update rubric (new version)")
async def update_rubric(organization_id: UUID, rubric_id: UUID, body: RubricUpdate,
                        db: AsyncSession = Depends(get_db),
                        ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_permission(ctx, "evaluation:admin")
    result = await db.execute(select(EvaluationRubric).where(
        EvaluationRubric.id == rubric_id))
    rubric = result.scalar_one_or_none()
    if rubric is None or rubric.organization_id != organization_id:
        raise HTTPException(status_code=404, detail="Rubric not found")
    if body.name is not None:
        rubric.name = body.name
    if body.quality_threshold is not None:
        rubric.quality_threshold = body.quality_threshold
    if body.confidence_threshold is not None:
        rubric.confidence_threshold = body.confidence_threshold
    if body.is_active is not None:
        rubric.is_active = body.is_active
    if body.criteria is not None:
        try:
            criteria = parse_criteria(body.criteria)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        rubric.version += 1
        rubric.criteria = [{"name": c.name, "description": c.description,
                            "weight": c.weight, "minimum_score": c.minimum_score,
                            "required": c.required, "method": c.method,
                            "params": c.params} for c in criteria]
        db.add(EvaluationRubricVersion(rubric_id=rubric.id,
                                      organization_id=organization_id,
                                      version=rubric.version,
                                      criteria=rubric.criteria))
    await db.commit()
    return _serialize_rubric(rubric)


# -- quality gates ---------------------------------------------------------------
class GateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    required_checks: list[dict[str, Any]] = Field(default_factory=list)
    thresholds: dict[str, Any] = Field(default_factory=dict)
    failure_behavior: str = Field(default="FAIL", max_length=30)
    approval_required: bool = False


class GateUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    required_checks: Optional[list[dict[str, Any]]] = None
    thresholds: Optional[dict[str, Any]] = None
    failure_behavior: Optional[str] = Field(default=None, max_length=30)
    approval_required: Optional[bool] = None
    is_active: Optional[bool] = None


class GateEvaluate(BaseModel):
    check_targets: dict[str, Any] = Field(default_factory=dict)
    score: float = Field(default=1.0, ge=0.0, le=100.0)
    confidence: float = Field(default=1.0, ge=0.0, le=100.0)
    approval_id: Optional[UUID] = None


def _serialize_gate(g: QualityGate) -> dict[str, Any]:
    return {"id": str(g.id), "name": g.name,
            "required_checks": g.required_checks, "thresholds": g.thresholds,
            "failure_behavior": g.failure_behavior,
            "approval_required": g.approval_required,
            "is_active": g.is_active, "version": g.version}


@gates_router.get("", summary="List quality gates (built-ins included)")
async def list_gates(organization_id: UUID,
                     db: AsyncSession = Depends(get_db),
                     ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_permission(ctx, "evaluation:read")
    rows = (await db.execute(select(QualityGate).where(
        QualityGate.organization_id == organization_id))).scalars().all()
    builtins = [{"id": f"builtin:{name}", **gate} for name, gate in BUILTIN_GATES.items()]
    return {"items": builtins + [_serialize_gate(g) for g in rows]}


@gates_router.post("", status_code=201, summary="Create quality gate")
async def create_gate(organization_id: UUID, body: GateCreate,
                      db: AsyncSession = Depends(get_db),
                      ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_permission(ctx, "evaluation:admin")
    if body.failure_behavior.upper() not in ("FAIL", "CORRECT", "RETRY", "ESCALATE",
                                             "REQUEST_HUMAN", "STOP"):
        raise HTTPException(status_code=400, detail="Unknown failure behavior")
    gate = QualityGate(organization_id=organization_id, name=body.name,
                       required_checks=body.required_checks,
                       thresholds=body.thresholds,
                       failure_behavior=body.failure_behavior.upper(),
                       approval_required=body.approval_required, version=1)
    db.add(gate)
    await db.commit()
    return _serialize_gate(gate)


@gates_router.patch("/{gate_id}", summary="Update quality gate")
async def update_gate(organization_id: UUID, gate_id: UUID, body: GateUpdate,
                      db: AsyncSession = Depends(get_db),
                      ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_permission(ctx, "evaluation:admin")
    result = await db.execute(select(QualityGate).where(QualityGate.id == gate_id))
    gate = result.scalar_one_or_none()
    if gate is None or gate.organization_id != organization_id:
        raise HTTPException(status_code=404, detail="Quality gate not found")
    if body.name is not None:
        gate.name = body.name
    if body.required_checks is not None:
        gate.required_checks = body.required_checks
        gate.version += 1
    if body.thresholds is not None:
        gate.thresholds = body.thresholds
    if body.failure_behavior is not None:
        if body.failure_behavior.upper() not in ("FAIL", "CORRECT", "RETRY", "ESCALATE",
                                                 "REQUEST_HUMAN", "STOP"):
            raise HTTPException(status_code=400, detail="Unknown failure behavior")
        gate.failure_behavior = body.failure_behavior.upper()
    if body.approval_required is not None:
        gate.approval_required = body.approval_required
    if body.is_active is not None:
        gate.is_active = body.is_active
    await db.commit()
    return _serialize_gate(gate)


@gates_router.post("/{gate_id}/evaluate", summary="Evaluate a gate (no side effects)")
async def evaluate_gate_endpoint(organization_id: UUID, gate_id: UUID,
                                 body: GateEvaluate,
                                 db: AsyncSession = Depends(get_db),
                                 ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_permission(ctx, "evaluation:decide")
    gate_def: Optional[dict[str, Any]] = None
    if str(gate_id).startswith("builtin:"):
        gate_def = get_builtin_gate(str(gate_id).split(":", 1)[1])
        if gate_def is None:
            raise HTTPException(status_code=404, detail="Quality gate not found")
    else:
        result = await db.execute(select(QualityGate).where(QualityGate.id == gate_id))
        gate = result.scalar_one_or_none()
        if gate is None or gate.organization_id != organization_id:
            raise HTTPException(status_code=404, detail="Quality gate not found")
        gate_def = {"name": gate.name, "required_checks": gate.required_checks,
                    "thresholds": gate.thresholds,
                    "failure_behavior": gate.failure_behavior,
                    "approval_required": gate.approval_required}
    outcome = await evaluate_gate(db=db, organization_id=organization_id,
                                  gate=gate_def,
                                  check_targets=body.check_targets,
                                  score=body.score, confidence=body.confidence)
    if outcome["approval_required"]:
        if body.approval_id is None:
            outcome["approval_status"] = "MISSING"
        else:
            from openagent.db.models.approval import Approval, ApprovalStatus
            approval = (await db.execute(select(Approval).where(
                Approval.id == body.approval_id))).scalar_one_or_none()
            if approval is None or approval.organization_id != organization_id:
                outcome["approval_status"] = "NOT_FOUND"
                outcome["passed"] = False
            elif approval.status != ApprovalStatus.APPROVED:
                outcome["approval_status"] = "NOT_GRANTED"
                outcome["passed"] = False
            else:
                outcome["approval_status"] = "GRANTED"
                outcome["passed"] = bool(outcome["passed_checks"])
    return outcome


# -- benchmarks ------------------------------------------------------------------
class BenchmarkCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    dataset: list[dict[str, Any]] = Field(default_factory=list)
    criteria: dict[str, Any] = Field(default_factory=dict)


class BenchmarkRunInput(BaseModel):
    items: list[dict[str, Any]] = Field(default_factory=list)
    baseline_run_id: Optional[UUID] = None
    score_keys: Optional[list[str]] = None


@benchmarks_router.get("", summary="List benchmarks")
async def list_benchmarks(organization_id: UUID,
                          db: AsyncSession = Depends(get_db),
                          ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_permission(ctx, "evaluation:read")
    rows = (await db.execute(select(Benchmark).where(
        Benchmark.organization_id == organization_id))).scalars().all()
    return {"items": [{"id": str(b.id), "name": b.name,
                       "dataset_size": len(b.dataset or []),
                       "is_active": b.is_active} for b in rows]}


@benchmarks_router.post("", status_code=201, summary="Create benchmark (data, not code)")
async def create_benchmark(organization_id: UUID, body: BenchmarkCreate,
                           db: AsyncSession = Depends(get_db),
                           ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_permission(ctx, "evaluation:admin")
    for item in body.dataset:
        if not isinstance(item, dict):
            raise HTTPException(status_code=400,
                                detail="Dataset items must be objects")
    benchmark = Benchmark(organization_id=organization_id, name=body.name,
                          dataset=body.dataset, criteria=body.criteria)
    db.add(benchmark)
    await db.commit()
    return {"id": str(benchmark.id), "name": benchmark.name}


@benchmarks_router.post("/{benchmark_id}/run", summary="Aggregate a benchmark run + regression")
async def run_benchmark_endpoint(organization_id: UUID, benchmark_id: UUID,
                                 body: BenchmarkRunInput,
                                 db: AsyncSession = Depends(get_db),
                                 ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_permission(ctx, "evaluation:decide")
    from openagent.evaluator.benchmarks import detect_regression
    result = await db.execute(select(Benchmark).where(Benchmark.id == benchmark_id))
    benchmark = result.scalar_one_or_none()
    if benchmark is None or benchmark.organization_id != organization_id:
        raise HTTPException(status_code=404, detail="Benchmark not found")
    aggregate: dict[str, float] = {}
    counts: dict[str, int] = {}
    failed = 0
    stored_items: list[dict[str, Any]] = []
    for index, item in enumerate(body.items):
        scores = item.get("scores", {}) if isinstance(item, dict) else {}
        if not isinstance(scores, dict):
            failed += 1
            stored_items.append({"index": index, "status": "error"})
            continue
        stored_items.append({"index": index, "status": "ok", "scores": scores,
                             "evaluation_id": item.get("evaluation_id")})
        for key, value in scores.items():
            if isinstance(value, (int, float)):
                aggregate[key] = aggregate.get(key, 0.0) + float(value)
                counts[key] = counts.get(key, 0) + 1
    scores = {k: round(aggregate[k] / counts[k], 4) for k in aggregate}
    scores["items_total"] = len(body.items)
    scores["items_failed"] = failed
    regression: dict[str, Any] = {"regressed": False, "regressions": []}
    if body.baseline_run_id:
        base = (await db.execute(select(BenchmarkRun).where(
            BenchmarkRun.id == body.baseline_run_id))).scalar_one_or_none()
        if base is None or base.organization_id != organization_id:
            raise HTTPException(status_code=404, detail="Baseline run not found")
        regression = detect_regression(baseline=dict(base.scores or {}),
                                       current=scores, keys=body.score_keys)
    run = BenchmarkRun(benchmark_id=benchmark.id, organization_id=organization_id,
                       status="completed", scores=scores, items=stored_items,
                       baseline_run_id=body.baseline_run_id, regression=regression)
    db.add(run)
    await db.commit()
    metrics_inc("benchmark_runs_total")
    return {"run_id": str(run.id), "status": run.status, "scores": scores,
            "regression": regression}


@benchmarks_router.get("/{benchmark_id}/runs", summary="List benchmark runs")
async def list_benchmark_runs(organization_id: UUID, benchmark_id: UUID,
                              db: AsyncSession = Depends(get_db),
                              ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_permission(ctx, "evaluation:read")
    result = await db.execute(select(Benchmark).where(Benchmark.id == benchmark_id))
    benchmark = result.scalar_one_or_none()
    if benchmark is None or benchmark.organization_id != organization_id:
        raise HTTPException(status_code=404, detail="Benchmark not found")
    runs = (await db.execute(select(BenchmarkRun).where(
        BenchmarkRun.benchmark_id == benchmark_id).order_by(
            BenchmarkRun.created_at.desc()))).scalars().all()
    return {"items": [{"id": str(r.id), "status": r.status, "scores": r.scores,
                       "regression": r.regression,
                       "created_at": r.created_at.isoformat() if r.created_at else None}
                      for r in runs]}


# -- quality overview --------------------------------------------------------------
@quality_router.get("/overview", summary="Quality dashboard aggregates")
async def quality_overview(organization_id: UUID,
                           db: AsyncSession = Depends(get_db),
                           ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_permission(ctx, "evaluation:read")
    by_status = (await db.execute(
        select(Evaluation.status, func.count()).where(
            Evaluation.organization_id == organization_id).group_by(
                Evaluation.status))).all()
    by_decision = (await db.execute(
        select(Evaluation.decision, func.count()).where(
            Evaluation.organization_id == organization_id).group_by(
                Evaluation.decision))).all()
    plans_open = (await db.execute(
        select(func.count()).select_from(CorrectionPlan).where(
            CorrectionPlan.organization_id == organization_id,
            CorrectionPlan.status.in_(["proposed", "running"])))).scalar() or 0
    disagreements = (await db.execute(
        select(func.count()).select_from(EvaluationDisagreement).where(
            EvaluationDisagreement.organization_id == organization_id))).scalar() or 0
    recent_failures = (await db.execute(
        select(Evaluation).where(
            Evaluation.organization_id == organization_id,
            Evaluation.status == EvaluationStatus.FAILED).order_by(
                Evaluation.created_at.desc()).limit(10))).scalars().all()
    from openagent.evaluator.metrics import snapshot as metrics_snapshot
    return {"by_status": {str(s.value if hasattr(s, "value") else s): c
                          for s, c in by_status},
            "by_decision": {str(d or "NONE"): c for d, c in by_decision},
            "open_correction_plans": plans_open,
            "disagreements_total": disagreements,
            "recent_failures": [{"id": str(e.id), "type": e.evaluation_type,
                                 "failure_class": e.failure_class,
                                 "score": e.score} for e in recent_failures],
            "metrics": metrics_snapshot()}
