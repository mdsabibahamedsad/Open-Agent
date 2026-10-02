"""Self-correction engine (MP20).

Execution -> Evaluation -> Failure Analysis -> Correction Plan ->
Approval/Policy Check if needed -> Retry -> Re-evaluate.

Bounds: every loop carries a CorrectionBudget; loop signatures stop repeats;
correction can never bypass RBAC/approval/sandbox/network/MCP policy, expose
secrets, or override human rejection. A failed action grants no new privilege.
"""

from __future__ import annotations

import hashlib
from typing import Any, Awaitable, Callable, Optional
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.approvals.hashing import canonical_json, redact_params
from openagent.evaluator.engine import EvaluatorEngine
from openagent.evaluator.types import CorrectionBudget, CorrectionStrategy, FailureClass

logger = structlog.get_logger("openagent.evaluator.correction")

# Strategies that need a human approval before the retry executes.
APPROVAL_STRATEGIES = frozenset({
    CorrectionStrategy.REQUEST_HUMAN,
    CorrectionStrategy.ASK_ANOTHER_AGENT,
})

# Strategies forbidden from weakening the platform posture.
FORBIDDEN_STRATEGIES = frozenset({
    # There is intentionally no DISABLE_POLICY / BYPASS_APPROVAL / WIDEN_SANDBOX
    # strategy. This set documents the refusal surface for policy checks.
})


class CorrectionError(Exception):
    def __init__(self, message: str, code: str = "CORRECTION_ERROR"):
        super().__init__(message)
        self.code = code


def failure_signature(*, failure_class: str, reason: str,
                      target_hash: str = "", strategy: str = "") -> str:
    """Stable loop-detection signature (reason truncated: same root, any wording)."""
    blob = canonical_json({"class": failure_class,
                           "reason": (reason or "")[:200],
                           "target": target_hash, "strategy": strategy})
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def classify_exception(exc: BaseException) -> FailureClass:
    name = type(exc).__name__.lower()
    text = f"{name} {exc}".lower()
    if any(w in text for w in ("timeout", "temporar", "rate limit", "429", "503", "econn")):
        return FailureClass.TRANSIENT
    if any(w in text for w in ("auth", "unauthorized", "401", "403", "forbidden", "token")):
        return FailureClass.AUTH_ERROR
    if any(w in text for w in ("network", "dns", "connection", "socket")):
        return FailureClass.NETWORK_ERROR
    if any(w in text for w in ("valid", "schema", "constraint", "assert")):
        return FailureClass.VALIDATION_ERROR
    if any(w in text for w in ("policy", "denied", "guardrail")):
        return FailureClass.POLICY_ERROR
    if any(w in text for w in ("secret", "secur", "inject", "exfiltrat")):
        return FailureClass.SECURITY_ERROR
    if any(w in text for w in ("tool", "provider", "mcp")):
        return FailureClass.TOOL_ERROR
    if any(w in text for w in ("model", "llm", "generation", "context length", "tokens")):
        return FailureClass.MODEL_ERROR
    return FailureClass.UNKNOWN


def default_strategy_for(failure_class: FailureClass) -> CorrectionStrategy:
    from openagent.evaluator.scoring import _strategy_for
    return _strategy_for(failure_class)


def check_budget(budget: CorrectionBudget, usage: dict[str, Any]) -> Optional[str]:
    """Return an exhaustion reason, or None if budget remains."""
    pairs = (("max_attempts", "attempts"), ("max_correction_cycles", "correction_cycles"),
             ("max_tokens", "tokens"), ("max_cost", "cost"),
             ("max_time_seconds", "time_seconds"),
             ("max_tool_calls", "tool_calls"),
             ("max_browser_actions", "browser_actions"),
             ("max_sandbox_executions", "sandbox_executions"))
    for limit_key, use_key in pairs:
        if float(usage.get(use_key, 0) or 0) >= float(getattr(budget, limit_key)):
            return f"budget exhausted: {use_key} >= {limit_key}"
    return None


class SelfCorrectionEngine:
    def __init__(self, db: AsyncSession,
                 evaluator: Optional[EvaluatorEngine] = None):
        self.db = db
        self.evaluator = evaluator or EvaluatorEngine(db)

    async def build_plan(self, evaluation_id: UUID, *,
                         organization_id: UUID,
                         strategy: Optional[str] = None,
                         changes: Optional[dict[str, Any]] = None,
                         root_cause: Optional[dict[str, Any]] = None,
                         risk_level: str = "LOW") -> Any:
        """Analyze a terminal FAILED evaluation into a correction plan.

        Structured root-cause shape: SYMPTOM/CAUSE/EVIDENCE/CORRECTION/EXPECTED.
        Unknown causes stay unknown (no false certainty).
        """
        from openagent.db.models.evaluation import CorrectionPlan
        evaluation = await self.evaluator._locked(evaluation_id)
        await self.evaluator._require_org(evaluation, organization_id)
        status = str(evaluation.status.value if hasattr(evaluation.status, "value")
                     else evaluation.status).upper()
        if status not in ("FAILED", "UNCERTAIN", "ERROR"):
            raise CorrectionError(f"Nothing to correct (status {status})",
                                  code="NOTHING_TO_CORRECT")
        failure_class = str(getattr(evaluation, "failure_class", "") or "UNKNOWN")
        try:
            failure_enum = FailureClass(failure_class)
        except ValueError:
            failure_enum = FailureClass.UNKNOWN
        chosen = CorrectionStrategy(str(strategy or "").upper()) \
            if strategy else default_strategy_for(failure_enum)
        if chosen.name in FORBIDDEN_STRATEGIES:
            raise CorrectionError(f"Strategy {chosen.value} is forbidden",
                                  code="FORBIDDEN_STRATEGY")
        cause = dict(root_cause or {})
        cause.setdefault("symptom", getattr(evaluation, "failure_reason", "") or "")
        cause.setdefault("cause", "unknown" if failure_enum == FailureClass.UNKNOWN else "")
        cause.setdefault("evidence", [])
        cause.setdefault("correction", chosen.value)
        cause.setdefault("expected_result", "")
        plan = CorrectionPlan(
            evaluation_id=evaluation.id, organization_id=organization_id,
            attempt_number=int(getattr(evaluation, "attempt_number", 0) or 0) + 1,
            failure_class=failure_enum.value, root_cause=redact_params(cause),
            proposed_strategy=chosen.value,
            changes=redact_params(dict(changes or {})),
            risk_level=(risk_level or "LOW").upper(),
            approval_required=chosen in APPROVAL_STRATEGIES,
            status="proposed", result={})
        self.db.add(plan)
        await self.db.flush()
        await self.evaluator._audit(organization_id, None, "correction.planned",
                                    plan.id, {"strategy": chosen.value,
                                              "failure_class": failure_enum.value})
        return plan

    async def execute_attempt(
        self, plan_id: UUID, *, organization_id: UUID,
        action: dict[str, Any],
        budget: Optional[CorrectionBudget] = None,
        usage: Optional[dict[str, Any]] = None,
        run: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]],
    ) -> dict[str, Any]:
        """Run one bounded correction attempt via caller callback.

        `run` performs the retry (tool call, replan, ...) and returns
        {"outcome": {...}, "usage": {...}, "failure": str|None,
        "failure_class": str|None, "target_hash": str}. The engine records the
        attempt, detects loops, and reports whether to continue.
        """
        from openagent.db.models.evaluation import CorrectionAttempt, CorrectionPlan
        budget = budget or CorrectionBudget()
        usage = usage or {}
        result = await self.db.execute(
            select(CorrectionPlan).where(CorrectionPlan.id == plan_id).with_for_update())
        plan = result.scalar_one_or_none()
        if plan is None:
            raise CorrectionError("Correction plan not found", code="NOT_FOUND")
        if plan.organization_id != organization_id:
            await self.evaluator._security_event(
                organization_id, None, "evaluation.cross_tenant_attempt",
                {"plan_id": str(plan_id)})
            raise CorrectionError("Cross-tenant correction access denied",
                                  code="CROSS_TENANT")
        if str(plan.status) != "proposed":
            raise CorrectionError(f"Plan is {plan.status}, not proposed",
                                  code="INVALID_STATE")
        exhausted = check_budget(budget, usage)
        if exhausted:
            plan.status = "budget_exhausted"
            plan.result = {"reason": exhausted}
            await self.db.flush()
            return {"verdict": "STOP", "reason": exhausted}
        if plan.approval_required and not action.get("approval_id"):
            return {"verdict": "REQUEST_HUMAN", "plan_id": str(plan.id),
                    "reason": "strategy requires human approval before retry"}
        signature = failure_signature(
            failure_class=str(plan.failure_class),
            reason=str((plan.root_cause or {}).get("symptom", "")),
            target_hash=str(action.get("target_hash", "")),
            strategy=str(plan.proposed_strategy))
        prior = (await self.db.execute(
            select(CorrectionAttempt).where(
                CorrectionAttempt.plan_id == plan.id,
                CorrectionAttempt.failure_signature == signature))).scalars().all()
        if len(prior) >= 2:
            plan.status = "loop_stopped"
            plan.result = {"reason": "same failure repeated; loop detected"}
            await self.db.flush()
            await self.evaluator._security_event(
                organization_id, None, "correction.loop_abuse",
                {"plan_id": str(plan.id), "signature": signature})
            logger.warning("correction loop detected; stopping",
                           plan_id=str(plan.id))
            return {"verdict": "STOP", "reason": "correction loop detected"}
        attempt_no = len((await self.db.execute(
            select(CorrectionAttempt).where(
                CorrectionAttempt.plan_id == plan.id))).scalars().all()) + 1
        plan.status = "running"
        await self.db.flush()
        try:
            ran = await run(redact_params(dict(action)))
        except Exception as exc:
            ran = {"outcome": {}, "usage": {},
                   "failure": str(exc)[:1000],
                   "failure_class": classify_exception(exc).value}
        attempt = CorrectionAttempt(
            plan_id=plan.id, evaluation_id=plan.evaluation_id,
            organization_id=organization_id, attempt_number=attempt_no,
            action=redact_params(dict(action)),
            outcome=redact_params(dict(ran.get("outcome", {}) or {})),
            status="succeeded" if not ran.get("failure") else "failed",
            failure_signature=signature if ran.get("failure") else "")
        self.db.add(attempt)
        if ran.get("failure"):
            plan.status = "proposed"  # retryable unless loop/budget stops it
            plan.result = {"last_failure": str(ran.get("failure"))[:1000]}
        else:
            plan.status = "succeeded"
            plan.result = {"outcome": redact_params(dict(ran.get("outcome", {}) or {}))}
        await self.db.flush()
        merged_usage = dict(usage)
        for key, value in (ran.get("usage", {}) or {}).items():
            try:
                merged_usage[key] = float(merged_usage.get(key, 0) or 0) + float(value or 0)
            except (TypeError, ValueError):
                pass
        return {"verdict": "RETRY" if ran.get("failure") else "DONE",
                "plan_id": str(plan.id), "attempt_id": str(attempt.id),
                "failure": ran.get("failure"),
                "failure_class": ran.get("failure_class"),
                "usage": merged_usage}

    async def re_evaluate(self, plan_id: UUID, *,
                          organization_id: UUID,
                          evaluation_id: UUID) -> dict[str, Any]:
        """Link a fresh evaluation to the plan (history stays immutable)."""
        from openagent.db.models.evaluation import CorrectionPlan
        result = await self.db.execute(
            select(CorrectionPlan).where(CorrectionPlan.id == plan_id))
        plan = result.scalar_one_or_none()
        if plan is None or plan.organization_id != organization_id:
            raise CorrectionError("Correction plan not found", code="NOT_FOUND")
        plan.result = {**(plan.result or {}), "re_evaluation_id": str(evaluation_id)}
        await self.db.flush()
        return {"plan_id": str(plan.id), "re_evaluation_id": str(evaluation_id)}
