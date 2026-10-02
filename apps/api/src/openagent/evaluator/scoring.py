"""Scoring, consensus & policy-driven decisions (MP20).

Scores never imply truth by themselves: PASS requires score >= threshold AND
all required deterministic checks AND no critical safety failure. Uncertainty
stays visible; disagreement is never hidden.
"""

from __future__ import annotations

from typing import Any, Optional

from openagent.evaluator.types import (
    CheckResult,
    ConsensusOutcome,
    CorrectionStrategy,
    EvalDecision,
    EvalScores,
    EvaluationDecision,
    EvaluationStatus,
    FailureClass,
)


def normalize_score(value: Any) -> float:
    """Accept 0..1 or 0..100; clamp and round (no meaningless precision)."""
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.0
    if score > 1.0:  # assume 0..100 scale
        score = score / 100.0
    return round(min(1.0, max(0.0, score)), 4)


def combine_consensus(votes: list[dict[str, Any]]) -> dict[str, Any]:
    """Combine deterministic + LLM + independent votes.

    Each vote: {source, decision: PASS|FAIL|UNCERTAIN, score, confidence,
    weight?}. Returns {outcome, score, confidence, reason_codes}.
    """
    if not votes:
        return {"outcome": ConsensusOutcome.INSUFFICIENT_EVIDENCE,
                "score": 0.0, "confidence": 0.0,
                "reason_codes": ["no_evaluator_votes"]}
    total_w = sum(float(v.get("weight", 1.0)) for v in votes) or 1.0
    score = sum(normalize_score(v.get("score", 0.0)) * float(v.get("weight", 1.0))
                for v in votes) / total_w
    confidence = sum(normalize_score(v.get("confidence", 0.5)) * float(v.get("weight", 1.0))
                     for v in votes) / total_w
    decisions = {str(v.get("decision", "UNCERTAIN")).upper() for v in votes}
    if decisions == {"PASS"}:
        outcome = ConsensusOutcome.AGREEMENT
    elif decisions == {"FAIL"}:
        outcome = ConsensusOutcome.AGREEMENT
    elif decisions <= {"PASS", "FAIL", "UNCERTAIN"} and len(decisions) > 1:
        outcome = ConsensusOutcome.DISAGREEMENT
    else:
        outcome = ConsensusOutcome.INSUFFICIENT_EVIDENCE
    codes = [f"{v.get('source', 'evaluator')}:{v.get('decision', '?')}" for v in votes]
    return {"outcome": outcome, "score": round(score, 4),
            "confidence": round(confidence, 4), "reason_codes": codes}


def decide(*, score: float, confidence: float,
           required_checks: list[CheckResult],
           quality_threshold: float = 0.7,
           confidence_threshold: float = 0.6,
           failure_class: FailureClass = FailureClass.UNKNOWN,
           failure_reason: str = "",
           consensus: Optional[ConsensusOutcome] = None,
           disagreement_policy: str = "CONSERVATIVE_FAIL",
           ) -> EvalDecision:
    """Policy-driven decision. Deterministic checks dominate scores."""
    score = normalize_score(score)
    confidence = normalize_score(confidence)
    failed_required = [c for c in required_checks if c.required and not c.passed]
    safety_hit = any(c.critical_safety and not c.passed for c in required_checks)

    if safety_hit:
        return EvalDecision(EvaluationDecision.FAIL, EvaluationStatus.FAILED,
                            EvalScores(score, confidence,
                                       ["critical_safety_failure"] +
                                       [c.name for c in required_checks
                                        if c.critical_safety and not c.passed]),
                            failure_class=failure_class or FailureClass.SECURITY_ERROR,
                            failure_reason=failure_reason or "critical safety check failed",
                            correction_strategy=CorrectionStrategy.STOP)
    if consensus == ConsensusOutcome.DISAGREEMENT:
        policy = (disagreement_policy or "CONSERVATIVE_FAIL").upper()
        if policy == "HUMAN_REVIEW":
            return EvalDecision(EvaluationDecision.REQUEST_HUMAN,
                                EvaluationStatus.UNCERTAIN,
                                EvalScores(score, confidence, ["evaluator_disagreement"]),
                                failure_class=failure_class,
                                uncertainty_reason="evaluators disagree; human review required")
        if policy in ("SECOND_REVIEW", "MORE_EVIDENCE"):
            return EvalDecision(EvaluationDecision.ESCALATE,
                                EvaluationStatus.UNCERTAIN,
                                EvalScores(score, confidence, ["evaluator_disagreement"]),
                                failure_class=failure_class,
                                uncertainty_reason="evaluators disagree; second review required")
        return EvalDecision(EvaluationDecision.FAIL, EvaluationStatus.FAILED,
                            EvalScores(score, confidence, ["evaluator_disagreement"]),
                            failure_class=failure_class,
                            failure_reason=failure_reason or "evaluator disagreement (conservative fail)",
                            correction_strategy=CorrectionStrategy.STOP)
    if failed_required:
        names = [c.name for c in failed_required]
        return EvalDecision(EvaluationDecision.FAIL, EvaluationStatus.FAILED,
                            EvalScores(score, confidence,
                                       ["required_check_failed"] + names),
                            failure_class=failure_class,
                            failure_reason=failure_reason or
                            f"required checks failed: {', '.join(names)}",
                            correction_strategy=_strategy_for(failure_class))
    if confidence < confidence_threshold:
        return EvalDecision(EvaluationDecision.REQUEST_HUMAN,
                            EvaluationStatus.UNCERTAIN,
                            EvalScores(score, confidence, ["low_confidence"]),
                            failure_class=failure_class,
                            uncertainty_reason=(
                                f"confidence {confidence} < {confidence_threshold}; "
                                "human review required"))
    if score < quality_threshold:
        return EvalDecision(EvaluationDecision.CORRECT, EvaluationStatus.FAILED,
                            EvalScores(score, confidence, ["below_threshold"]),
                            failure_class=(failure_class if failure_class != FailureClass.UNKNOWN
                                           else FailureClass.QUALITY_FAILURE),
                            failure_reason=failure_reason or
                            f"score {score} < threshold {quality_threshold}",
                            correction_strategy=_strategy_for(failure_class))
    return EvalDecision(EvaluationDecision.PASS, EvaluationStatus.PASSED,
                        EvalScores(score, confidence, ["threshold_met"]),
                        failure_class=FailureClass.UNKNOWN)


def _strategy_for(failure_class: FailureClass) -> CorrectionStrategy:
    mapping = {
        FailureClass.TRANSIENT: CorrectionStrategy.RETRY_WITH_BACKOFF,
        FailureClass.TOOL_ERROR: CorrectionStrategy.RETRY_WITH_NEW_TOOL,
        FailureClass.NETWORK_ERROR: CorrectionStrategy.RETRY_WITH_BACKOFF,
        FailureClass.AUTH_ERROR: CorrectionStrategy.STOP,
        FailureClass.VALIDATION_ERROR: CorrectionStrategy.MODIFY_PARAMETERS,
        FailureClass.MODEL_ERROR: CorrectionStrategy.RETRY_WITH_NEW_MODEL,
        FailureClass.CONTEXT_ERROR: CorrectionStrategy.EXPAND_CONTEXT,
        FailureClass.PLANNING_ERROR: CorrectionStrategy.REPLAN,
        FailureClass.EXECUTION_ERROR: CorrectionStrategy.RETRY_SAME,
        FailureClass.DATA_ERROR: CorrectionStrategy.MODIFY_PARAMETERS,
        FailureClass.POLICY_ERROR: CorrectionStrategy.STOP,
        FailureClass.SECURITY_ERROR: CorrectionStrategy.STOP,
        FailureClass.REQUIREMENT_MISMATCH: CorrectionStrategy.REQUEST_HUMAN,
        FailureClass.QUALITY_FAILURE: CorrectionStrategy.REFINE_PROMPT,
        FailureClass.UNKNOWN: CorrectionStrategy.RETRY_SAME,
    }
    return mapping.get(failure_class, CorrectionStrategy.RETRY_SAME)
