"""Central EvaluatorEngine (MP20).

Generation -> Execution -> Observation -> Evaluation -> Verification ->
Decision -> Correction / Retry / Escalation / Completion.

Invariants enforced server-side:

1. Agent claims are not proof (only evidence feeds decisions).
2. Evidence must be traceable (provenance + content hash on every record).
3. Deterministic verification dominates scores when available.
4. Evaluators cannot alter criteria (criteria snapshot hashed at creation).
5. Evaluated agents cannot mark themselves successful (separation enforced).
6. Failed evaluations never silently become success (terminal immutability;
   correction creates a NEW linked evaluation).
7. Uncertainty stays visible (UNCERTAIN is terminal and explicit).
8. Cross-tenant access denied (every method checks org).
9. Secrets never persisted (redaction before storage, via approvals hashing).
10. Prompt injection cannot alter policy (evaluated content framed as data).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.approvals.hashing import canonical_json, redact_params
from openagent.evaluator.criteria import RUBRIC_VERSION, parse_criteria, parse_goal_block
from openagent.evaluator.deterministic import run_check
from openagent.evaluator.evidence import verify_content_hash
from openagent.evaluator.scoring import combine_consensus, decide, normalize_score
from openagent.evaluator.types import (
    CheckResult,
    ConsensusOutcome,
    EvaluationStatus,
    EvidenceRecord,
    EvidenceTrust,
    EvidenceType,
    FailureClass,
    can_transition,
)

logger = structlog.get_logger("openagent.evaluator")

EVALUATOR_VERSION = "evaluator-v1"
VERIFICATION_VERSION = "verification-v1"


class EvaluatorError(Exception):
    def __init__(self, message: str, code: str = "EVALUATOR_ERROR"):
        super().__init__(message)
        self.code = code


@dataclass
class CreateEvaluation:
    organization_id: UUID
    evaluation_type: str = "TASK_SUCCESS"
    task_id: Optional[str] = None
    agent_id: Optional[UUID] = None
    agent_run_id: Optional[UUID] = None
    workflow_id: Optional[UUID] = None
    workflow_execution_id: Optional[UUID] = None
    evaluator_type: str = "automated"
    criteria: Any = None  # list | dict(goal block) | None
    goal: str = ""
    input_ref: Any = None
    output_ref: Any = None
    parent_evaluation_id: Optional[UUID] = None
    attempt_number: int = 0
    rubric_version: Optional[str] = None
    policy_version: str = "platform-v1"
    model_version: Optional[str] = None
    generator_model: str = ""  # recorded for separation enforcement
    quality_threshold: float = 0.7
    confidence_threshold: float = 0.6


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _hash_ref(value: Any) -> str:
    import hashlib
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


class EvaluatorEngine:
    def __init__(self, db: AsyncSession):
        self.db = db

    # -- create ---------------------------------------------------------
    async def create_evaluation(self, req: CreateEvaluation,
                                 evidence: Optional[list[EvidenceRecord]] = None) -> Any:
        from openagent.db.models.evaluation import Evaluation, EvaluationEvidence
        from openagent.db.models.evaluation import EvaluationStatus as DBStatus
        # NOTE: the DB enum uses lowercase values; the domain enum (types.py)
        # uses uppercase. Writes use the DB enum; reads normalize via .upper().
        criteria = parse_criteria(req.criteria)
        goal_block = parse_goal_block({"goal": req.goal} if isinstance(req.criteria, list)
                                      or req.criteria is None else req.criteria)
        redacted_input = redact_params(req.input_ref if isinstance(req.input_ref, (dict, list))
                                       else {"value": req.input_ref})
        redacted_output = redact_params(req.output_ref if isinstance(req.output_ref, (dict, list))
                                        else {"value": req.output_ref})
        evaluation = Evaluation(
            organization_id=req.organization_id, run_id=req.agent_run_id,
            workflow_execution_id=req.workflow_execution_id,
            evaluator_type=req.evaluator_type, status=DBStatus.PENDING,
            criteria={"criteria": [{"name": c.name, "description": c.description,
                                    "weight": c.weight, "minimum_score": c.minimum_score,
                                    "required": c.required, "method": c.method,
                                    "params": c.params} for c in criteria],
                      "goal": goal_block,
                      "criteria_hash": _hash_ref(criteria)},
            evaluation_type=(req.evaluation_type or "TASK_SUCCESS").upper(),
            task_id=req.task_id, agent_id=req.agent_id, workflow_id=req.workflow_id,
            parent_evaluation_id=req.parent_evaluation_id,
            attempt_number=req.attempt_number,
            input_hash=_hash_ref(redacted_input), output_hash=_hash_ref(redacted_output),
            evaluator_version=EVALUATOR_VERSION,
            rubric_version=req.rubric_version or RUBRIC_VERSION,
            policy_version=req.policy_version, model_version=req.model_version,
            verification_version=VERIFICATION_VERSION)
        self.db.add(evaluation)
        await self.db.flush()
        for record in evidence or []:
            self.db.add(EvaluationEvidence(
                evaluation_id=evaluation.id, organization_id=req.organization_id,
                evidence_type=record.evidence_type.value, trust=record.trust.value,
                content=dict(record.content), source=record.source,
                source_type=record.source_type, source_id=record.source_id,
                content_hash=record.content_hash,
                captured_at=_utcnow()))
        await self.db.flush()
        await self._audit(req.organization_id, None, "evaluation.created",
                          evaluation.id, {"type": evaluation.evaluation_type})
        await self._event("evaluation.created", evaluation, req.organization_id)
        logger.info("evaluation created", evaluation_id=str(evaluation.id),
                    type=evaluation.evaluation_type)
        return evaluation

    async def attach_evidence(self, evaluation_id: UUID, *,
                              organization_id: UUID,
                              records: list[EvidenceRecord]) -> int:
        from openagent.db.models.evaluation import EvaluationEvidence
        evaluation = await self._locked(evaluation_id)
        await self._require_org(evaluation, organization_id)
        if str(getattr(evaluation, "status", "")).upper() not in ("PENDING", "RUNNING"):
            raise EvaluatorError("Evidence is immutable once terminal",
                                 code="IMMUTABLE")
        count = 0
        for record in records:
            self.db.add(EvaluationEvidence(
                evaluation_id=evaluation.id, organization_id=organization_id,
                evidence_type=record.evidence_type.value, trust=record.trust.value,
                content=dict(record.content), source=record.source,
                source_type=record.source_type, source_id=record.source_id,
                content_hash=record.content_hash, captured_at=_utcnow()))
            count += 1
        await self.db.flush()
        return count

    # -- deterministic verification --------------------------------------
    async def run_checks(self, evaluation_id: UUID, *,
                         organization_id: UUID,
                         checks: list[dict[str, Any]]) -> list[CheckResult]:
        """Run deterministic checks against stored evidence. Preferred path."""
        from openagent.db.models.evaluation import EvaluationStatus as DBStatus
        from openagent.db.models.evaluation import VerificationCheck
        evaluation = await self._locked(evaluation_id)
        await self._require_org(evaluation, organization_id)
        self._ensure_mutable(evaluation)
        if str(evaluation.status.value if hasattr(evaluation.status, "value")
               else evaluation.status).lower() == "pending":
            evaluation.status = DBStatus.RUNNING
        evidence_rows = await self._evidence_rows(evaluation_id)
        results: list[CheckResult] = []
        for spec in checks:
            try:
                target = self._check_target(spec, evidence_rows)
                result = run_check(str(spec.get("kind", "")), target,
                                   dict(spec.get("params", {}) or {}),
                                   name=str(spec.get("name", spec.get("kind", ""))),
                                   required=bool(spec.get("required", True)))
            except EvaluatorError as exc:
                # Trust/type failures become failed checks, not aborted runs.
                result = run_check("__failed__", {}, {})
                result.name = str(spec.get("name", spec.get("kind", "")))
                result.required = bool(spec.get("required", True))
                result.passed = False
                result.reason = str(exc)
            result.critical_safety = bool(spec.get("critical_safety", False))
            results.append(result)
            self.db.add(VerificationCheck(
                evaluation_id=evaluation.id, organization_id=organization_id,
                name=result.name, kind=str(spec.get("kind", "")),
                passed=result.passed, reason=result.reason[:2000],
                required=result.required, critical_safety=result.critical_safety,
                evidence_id=str(spec.get("evidence_id", ""))))
        await self.db.flush()
        await self._audit(organization_id, None, "evaluation.verified", evaluation.id,
                          {"passed": sum(1 for r in results if r.passed),
                           "total": len(results)})
        return results

    # -- votes -------------------------------------------------------------
    async def record_vote(self, evaluation_id: UUID, *,
                          organization_id: UUID, source: str,
                          decision: str, score: Any, confidence: Any,
                          reason_codes: Optional[list[str]] = None,
                          weight: float = 1.0, model: str = "") -> Any:
        from openagent.db.models.evaluation import EvaluationResult
        evaluation = await self._locked(evaluation_id)
        await self._require_org(evaluation, organization_id)
        self._ensure_mutable(evaluation)
        decision_up = str(decision or "").upper()
        if decision_up not in ("PASS", "FAIL", "UNCERTAIN"):
            raise EvaluatorError(f"Invalid vote decision '{decision}'",
                                 code="INVALID_VOTE")
        vote = EvaluationResult(
            evaluation_id=evaluation.id, organization_id=organization_id,
            source=(source or "")[:128], decision=decision_up,
            score=normalize_score(score), confidence=normalize_score(confidence),
            reason_codes=list(reason_codes or [])[:20],
            weight=max(0.0, float(weight or 1.0)), model=(model or "")[:255])
        self.db.add(vote)
        await self.db.flush()
        return vote

    async def run_llm_vote(self, evaluation_id: UUID, *,
                           organization_id: UUID, provider: Any, model: str,
                           generator_model: str = "",
                           allow_self_evaluation: bool = False,
                           source: str = "llm") -> dict[str, Any]:
        """LLM evaluation via an injected provider (Model Router owned by caller)."""
        from openagent.evaluator.llm import run_llm_evaluation
        evaluation = await self._locked(evaluation_id)
        await self._require_org(evaluation, organization_id)
        self._ensure_mutable(evaluation)
        if not allow_self_evaluation:
            gen = str(getattr(evaluation, "model_version", "") or generator_model or "")
            if gen and gen.strip().lower() == model.strip().lower():
                await self._security_event(
                    organization_id, None, "evaluation.self_evaluation_abuse",
                    {"evaluation_id": str(evaluation_id), "model": model})
                raise EvaluatorError("Generator cannot evaluate itself without policy override",
                                     code="SELF_EVALUATION")
        evidence_rows = await self._evidence_rows(evaluation_id)
        criteria = (evaluation.criteria or {}).get("criteria", [])
        goal = (evaluation.criteria or {}).get("goal", {})
        parsed = await run_llm_evaluation(
            provider=provider, model=model,
            goal=goal.get("goal", "") if isinstance(goal, dict) else str(goal or ""),
            criteria=criteria,
            evidence=[{"evidence_type": r.evidence_type, "trust": r.trust,
                       "content": r.content, "source": r.source} for r in evidence_rows],
            generator_model=generator_model or str(getattr(evaluation, "model_version", "") or ""),
            allow_self_evaluation=allow_self_evaluation)
        await self.record_vote(
            evaluation_id, organization_id=organization_id, source=source,
            decision=parsed["decision"], score=parsed["score"],
            confidence=parsed["confidence"], reason_codes=parsed["reason_codes"],
            weight=1.0, model=model)
        return parsed

    # -- finalize / decide ---------------------------------------------------
    async def finalize(self, evaluation_id: UUID, *,
                       organization_id: UUID,
                       quality_threshold: float = 0.7,
                       confidence_threshold: float = 0.6,
                       disagreement_policy: str = "CONSERVATIVE_FAIL",
                       request_human_on_uncertain: bool = True) -> dict[str, Any]:
        """Combine votes + checks into a terminal decision. Terminal states are
        immutable afterwards; correction creates a NEW linked evaluation."""
        from openagent.db.models.evaluation import (
            EvaluationDisagreement,
            EvaluationResult,
            VerificationCheck,
        )
        evaluation = await self._locked(evaluation_id)
        await self._require_org(evaluation, organization_id)
        status = str(evaluation.status.value if hasattr(evaluation.status, "value")
                     else evaluation.status).upper()
        if status not in ("PENDING", "RUNNING"):
            raise EvaluatorError(f"Evaluation already terminal ({status}); "
                                 "correct via a new evaluation", code="IMMUTABLE")
        votes = (await self.db.execute(
            select(EvaluationResult).where(
                EvaluationResult.evaluation_id == evaluation_id))).scalars().all()
        checks = (await self.db.execute(
            select(VerificationCheck).where(
                VerificationCheck.evaluation_id == evaluation_id))).scalars().all()
        vote_dicts = [{"source": v.source, "decision": v.decision, "score": v.score,
                       "confidence": v.confidence, "weight": v.weight} for v in votes]
        combined = combine_consensus(vote_dicts)
        check_results = [CheckResult(name=c.name, passed=bool(c.passed), reason=c.reason,
                                     required=bool(c.required),
                                     critical_safety=bool(c.critical_safety))
                         for c in checks]
        # Deterministic votes: each required check casts a vote too.
        for check in check_results:
            vote_dicts.append({"source": f"check:{check.name}",
                               "decision": "PASS" if check.passed else "FAIL",
                               "score": 1.0 if check.passed else 0.0,
                               "confidence": 1.0, "weight": 2.0})
        if vote_dicts:
            combined = combine_consensus(vote_dicts)
        failure_class, failure_reason = self._classify(check_results)
        decision = decide(
            score=combined["score"], confidence=combined["confidence"],
            required_checks=check_results,
            quality_threshold=quality_threshold,
            confidence_threshold=confidence_threshold,
            failure_class=failure_class, failure_reason=failure_reason,
            consensus=combined["outcome"],
            disagreement_policy=disagreement_policy)
        if combined["outcome"] == ConsensusOutcome.DISAGREEMENT:
            self.db.add(EvaluationDisagreement(
                evaluation_id=evaluation.id, organization_id=organization_id,
                votes=vote_dicts, policy=disagreement_policy,
                resolution=decision.decision.value))
        evaluation.score = decision.scores.score
        evaluation.confidence = decision.scores.confidence
        evaluation.decision = decision.decision.value
        evaluation.failure_class = decision.failure_class.value
        evaluation.failure_reason = decision.failure_reason
        evaluation.uncertainty_reason = decision.uncertainty_reason
        evaluation.result = {"reason_codes": decision.scores.reason_codes,
                             "evidence_ids": decision.scores.evidence_ids,
                             "consensus": combined["outcome"].value,
                             "correction_strategy": (decision.correction_strategy.value
                                                     if decision.correction_strategy else None)}
        # Domain machine works on uppercase; DB column stores lowercase.
        from openagent.db.models.evaluation import EvaluationStatus as DBStatus
        target = decision.status  # already a domain EvaluationStatus
        if not can_transition(EvaluationStatus(status), target):
            # PENDING -> terminal directly is not in the machine: step through RUNNING.
            if status == "PENDING":
                evaluation.status = DBStatus.RUNNING
                await self.db.flush()
            status = str(evaluation.status.value if hasattr(evaluation.status, "value")
                         else evaluation.status).upper()
        if not can_transition(EvaluationStatus(status), target):
            raise EvaluatorError(f"Illegal transition {status} -> {target.value}",
                                 code="ILLEGAL_TRANSITION")
        evaluation.status = DBStatus(target.value.lower())
        evaluation.completed_at = _utcnow()
        await self.db.flush()
        approval_id: Optional[str] = None
        if decision.status == EvaluationStatus.UNCERTAIN and request_human_on_uncertain:
            approval_id = await self._request_human_review(evaluation, organization_id,
                                                           decision)
        await self._audit(organization_id, None,
                          f"evaluation.{decision.status.value.lower()}", evaluation.id,
                          {"decision": decision.decision.value,
                           "score": decision.scores.score})
        await self._event(f"evaluation.{decision.status.value.lower()}",
                          evaluation, organization_id)
        return {"evaluation_id": str(evaluation.id),
                "status": decision.status.value,
                "decision": decision.decision.value,
                "score": decision.scores.score,
                "confidence": decision.scores.confidence,
                "reason_codes": decision.scores.reason_codes,
                "failure_class": decision.failure_class.value,
                "failure_reason": decision.failure_reason,
                "uncertainty_reason": decision.uncertainty_reason,
                "correction_strategy": (decision.correction_strategy.value
                                        if decision.correction_strategy else None),
                "consensus": combined["outcome"].value,
                "approval_id": approval_id}

    async def verify(self, req: CreateEvaluation,
                     checks: list[dict[str, Any]],
                     evidence: Optional[list[EvidenceRecord]] = None,
                     **finalize_kw: Any) -> dict[str, Any]:
        """One-shot: create -> checks -> finalize. Deterministic-first."""
        evaluation = await self.create_evaluation(req, evidence)
        await self.run_checks(evaluation.id, organization_id=req.organization_id,
                              checks=checks)
        return await self.finalize(evaluation.id, organization_id=req.organization_id,
                                   quality_threshold=req.quality_threshold,
                                   confidence_threshold=req.confidence_threshold,
                                   **finalize_kw)

    async def compare(self, baseline_scores: dict[str, Any],
                      current_scores: dict[str, Any],
                      thresholds: Optional[dict[str, float]] = None) -> dict[str, Any]:
        """Regression compare (pure). Never promises LLM reproducibility."""
        thresholds = thresholds or {}
        regressions: list[str] = []
        for key, current in current_scores.items():
            if key in baseline_scores and isinstance(current, (int, float)):
                base = baseline_scores[key]
                floor = thresholds.get(key, 0.0)
                if isinstance(base, (int, float)) and current < base - floor:
                    regressions.append(f"{key}: {base} -> {current}")
        return {"regressed": bool(regressions), "regressions": regressions,
                "baseline": baseline_scores, "current": current_scores}

    async def submit_feedback(self, evaluation_id: UUID, *,
                              organization_id: UUID,
                              reviewer_id: Optional[UUID],
                              verdict: str, reason: str = "",
                              feedback: str = "") -> Any:
        """Append-only human feedback. Never rewrites history."""
        from openagent.db.models.evaluation import EvaluationFeedback
        evaluation = await self._locked(evaluation_id)
        await self._require_org(evaluation, organization_id)
        if str(verdict or "").lower() not in ("correct", "incorrect", "partially_correct"):
            raise EvaluatorError("verdict must be correct|incorrect|partially_correct",
                                 code="INVALID_VERDICT")
        row = EvaluationFeedback(
            evaluation_id=evaluation.id, organization_id=organization_id,
            reviewer_id=reviewer_id, verdict=str(verdict).lower(),
            reason=reason[:4000], feedback=feedback[:4000])
        self.db.add(row)
        await self.db.flush()
        await self._audit(organization_id, reviewer_id, "evaluation.feedback",
                          evaluation.id, {"verdict": row.verdict})
        return row

    # -- internals ---------------------------------------------------------
    async def _locked(self, evaluation_id: UUID) -> Any:
        from openagent.db.models.evaluation import Evaluation
        result = await self.db.execute(
            select(Evaluation).where(Evaluation.id == evaluation_id).with_for_update())
        evaluation = result.scalar_one_or_none()
        if evaluation is None:
            raise EvaluatorError("Evaluation not found", code="NOT_FOUND")
        return evaluation

    async def _require_org(self, evaluation: Any, organization_id: UUID) -> None:
        if evaluation.organization_id != organization_id:
            await self._security_event(organization_id, None,
                                       "evaluation.cross_tenant_attempt",
                                       {"evaluation_id": str(getattr(evaluation, "id", ""))})
            raise EvaluatorError("Cross-tenant evaluation access denied",
                                 code="CROSS_TENANT")

    def _ensure_mutable(self, evaluation: Any) -> None:
        from openagent.evaluator.types import TERMINAL_STATES
        status = str(evaluation.status.value if hasattr(evaluation.status, "value")
                     else evaluation.status).upper()
        try:
            parsed = EvaluationStatus(status)
        except ValueError:
            parsed = EvaluationStatus.RUNNING
        if parsed in TERMINAL_STATES:
            raise EvaluatorError(f"Evaluation is terminal ({status}); "
                                 "correct via a new evaluation", code="IMMUTABLE")

    async def _evidence_rows(self, evaluation_id: UUID) -> list[Any]:
        from openagent.db.models.evaluation import EvaluationEvidence
        result = await self.db.execute(
            select(EvaluationEvidence).where(
                EvaluationEvidence.evaluation_id == evaluation_id))
        rows = list(result.scalars().all())
        # Tamper check: content hash must match capture-time hash.
        for row in rows:
            try:
                record = EvidenceRecord(
                    evidence_type=EvidenceType(row.evidence_type),
                    trust=EvidenceTrust(row.trust), content=dict(row.content or {}),
                    content_hash=row.content_hash or "")
            except ValueError:
                continue
            if row.content_hash and not verify_content_hash(record):
                await self._security_event(
                    row.organization_id, None, "evidence.tamper_attempt",
                    {"evaluation_id": str(evaluation_id),
                     "evidence_id": str(row.id)})
                raise EvaluatorError("Evidence tampering detected; failing safely",
                                     code="EVIDENCE_TAMPERED")
        return rows

    def _check_target(self, spec: dict[str, Any], evidence_rows: list[Any]) -> Any:
        wanted = str(spec.get("evidence_type", "") or "").upper()
        inline = spec.get("target")
        if inline is not None:
            return inline
        for row in evidence_rows:
            if str(row.evidence_type or "").upper() == wanted:
                self._enforce_min_trust(spec, row)
                return dict(row.content or {})
        # Fall back to the most trusted record of any type.
        if evidence_rows:
            from openagent.evaluator.types import TRUST_RANK
            best = max(evidence_rows,
                       key=lambda r: TRUST_RANK.get(EvidenceTrust(r.trust), 0))
            self._enforce_min_trust(spec, best)
            return dict(best.content or {})
        return {}

    def _enforce_min_trust(self, spec: dict[str, Any], row: Any) -> None:
        """Required checks may demand minimum evidence trust (e.g. safety
        checks cannot pass on MODEL_GENERATED claims alone)."""
        from openagent.evaluator.types import TRUST_RANK
        minimum = str(spec.get("min_trust", "") or "").upper()
        if not minimum:
            return
        try:
            want = EvidenceTrust(minimum)
        except ValueError:
            raise EvaluatorError(f"Unknown min_trust '{minimum}'",
                                 code="INVALID_CHECK")
        try:
            have = EvidenceTrust(str(row.trust or "").upper())
        except ValueError:
            have = EvidenceTrust.UNVERIFIED
        if TRUST_RANK[have] < TRUST_RANK[want]:
            raise EvaluatorError(
                f"Check '{spec.get('name', spec.get('kind', ''))}' needs "
                f"{want.value} evidence, found {have.value}",
                code="INSUFFICIENT_TRUST")

    def _classify(self, checks: list[CheckResult]) -> tuple[FailureClass, str]:
        failed = [c for c in checks if not c.passed]
        if any(c.critical_safety and not c.passed for c in checks):
            names = [c.name for c in failed if c.critical_safety]
            return FailureClass.SECURITY_ERROR, f"safety checks failed: {', '.join(names)}"
        if not failed:
            return FailureClass.UNKNOWN, ""
        first = failed[0]
        name = first.name.lower()
        reason = first.reason
        if "secret" in name or "safety" in name:
            return FailureClass.SECURITY_ERROR, reason
        if "test" in name:
            return FailureClass.EXECUTION_ERROR, reason
        if "http" in name or "side_effect" in name:
            return FailureClass.TOOL_ERROR, reason
        if "schema" in name or "field" in name or "contains" in name:
            return FailureClass.REQUIREMENT_MISMATCH, reason
        if "browser" in name or "git" in name or "file" in name or "workflow" in name:
            return FailureClass.EXECUTION_ERROR, reason
        return FailureClass.QUALITY_FAILURE, reason

    async def _request_human_review(self, evaluation: Any, organization_id: UUID,
                                    decision: Any) -> Optional[str]:
        """Route UNCERTAIN through the EXISTING approval system (no second one)."""
        try:
            from openagent.approvals.engine import ApprovalEngine, CreateRequest
            approval = await ApprovalEngine(self.db).create_request(CreateRequest(
                organization_id=organization_id,
                action_type=f"evaluation.human_review:{evaluation.id}",
                action_category="WRITE",
                requested_action="evaluation.human_review",
                requested_params={"evaluation_id": str(evaluation.id),
                                  "decision": decision.decision.value,
                                  "uncertainty_reason": decision.uncertainty_reason},
                target_type="evaluation", target_id=str(evaluation.id),
                impact_summary=f"Uncertain evaluation needs human review: "
                               f"{decision.uncertainty_reason[:300]}",
                requester_type="agent",
                requester_id=str(getattr(evaluation, "agent_id", "") or "")))
            await self.db.flush()
            return str(approval.id)
        except Exception as exc:  # pragma: no cover - review hook best-effort
            logger.warning("human review hook skipped", error=str(exc))
            return None

    async def _audit(self, org_id: UUID | None, actor: UUID | None, action: str,
                     resource_id: UUID, meta: dict[str, Any]) -> None:
        try:
            from openagent.db.models.audit_log import AuditLog
            if org_id is None:
                return
            self.db.add(AuditLog(organization_id=org_id, actor_user_id=actor,
                                 action=action, resource_type="evaluation",
                                 resource_id=resource_id, metadata=dict(meta or {})))
            await self.db.flush()
        except Exception as exc:  # pragma: no cover - audit must never break evaluation
            logger.warning("evaluation audit skipped", error=str(exc))

    async def _event(self, event_type: str, evaluation: Any, org_id: UUID,
                     user_id: UUID | None = None) -> None:
        try:
            from openagent.core.events import EventService
            svc = EventService(self.db)
            await svc.publish(event_type, "evaluation", evaluation.id,
                              {"status": str(evaluation.status.value
                               if hasattr(evaluation.status, "value") else evaluation.status),
                               "decision": getattr(evaluation, "decision", None),
                               "score": getattr(evaluation, "score", None)},
                              organization_id=org_id, user_id=user_id)
        except Exception as exc:  # pragma: no cover - events are best-effort
            logger.warning("evaluation event skipped", error=str(exc))

    async def _security_event(self, org_id: UUID | None, user_id: UUID | None,
                              event_type: str, meta: dict[str, Any]) -> None:
        try:
            from openagent.db.models.security_event import SecurityEvent
            self.db.add(SecurityEvent(user_id=user_id, organization_id=org_id,
                                      event_type=event_type, metadata=dict(meta or {})))  # type: ignore[arg-type]
            await self.db.flush()
        except Exception as exc:  # pragma: no cover
            logger.warning("evaluation security event skipped", error=str(exc))
