"""Runtime integration helpers (MP20).

Thin glue between the EvaluatorEngine and existing runtimes. Helpers build
evidence and evaluations from runtime artifacts; they never execute business
actions, never grant authorization, and never weaken security policy.
"""

from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.evaluator.engine import CreateEvaluation, EvaluatorEngine
from openagent.evaluator.evidence import EvidenceCollector
from openagent.evaluator.types import EvidenceType

logger = structlog.get_logger("openagent.evaluator.integrations")


def _collector(organization_id: UUID, execution_id: str = "",
               agent_id: str = "") -> EvidenceCollector:
    return EvidenceCollector(organization_id=str(organization_id),
                             execution_id=execution_id, agent_id=agent_id)


async def evaluate_agent_run(db: AsyncSession, *, organization_id: UUID,
                             agent_id: Optional[UUID] = None,
                             agent_run_id: Optional[UUID] = None,
                             output: Any = None,
                             tool_results: Optional[list[dict[str, Any]]] = None,
                             criteria: Any = None, goal: str = "",
                             evaluation_type: str = "GOAL_COMPLETION",
                             quality_threshold: float = 0.7,
                             checks: Optional[list[dict[str, Any]]] = None,
                             ) -> dict[str, Any]:
    """Completion verification for an agent run. The agent's output is
    MODEL_GENERATED evidence; tool results are TOOL_VERIFIED."""
    engine = EvaluatorEngine(db)
    collector = _collector(organization_id, str(agent_run_id or ""),
                           str(agent_id or ""))
    collector.add(EvidenceType.AGENT_OUTPUT, {"output": output},
                  source="agent_run", source_type="AGENT_OUTPUT",
                  source_id=str(agent_run_id or ""))
    for result in tool_results or []:
        collector.add(EvidenceType.TOOL_RESULT, result,
                      source=str(result.get("tool", "tool")),
                      source_type="TOOL",
                      source_id=str(result.get("tool_call_id", "")),
                      tool_id=str(result.get("tool", "")))
    evaluation = await engine.create_evaluation(CreateEvaluation(
        organization_id=organization_id, evaluation_type=evaluation_type,
        agent_id=agent_id, agent_run_id=agent_run_id,
        criteria=criteria, goal=goal, output_ref=output,
        quality_threshold=quality_threshold), collector.records())
    if checks:
        await engine.run_checks(evaluation.id, organization_id=organization_id,
                                checks=checks)
    return await engine.finalize(
        evaluation.id, organization_id=organization_id,
        quality_threshold=quality_threshold)


async def verify_tool_call(db: AsyncSession, *, organization_id: UUID,
                           tool_name: str, result: dict[str, Any],
                           expected: Optional[dict[str, Any]] = None,
                           independently_verified: bool = False,
                           agent_id: Optional[UUID] = None,
                           agent_run_id: Optional[UUID] = None,
                           ) -> dict[str, Any]:
    """Tool verification: provider response + independent side-effect check."""
    engine = EvaluatorEngine(db)
    collector = _collector(organization_id, "", str(agent_id or ""))
    collector.add(EvidenceType.TOOL_RESULT, result, source=tool_name,
                  source_type="TOOL", tool_id=tool_name)
    evaluation = await engine.create_evaluation(CreateEvaluation(
        organization_id=organization_id, evaluation_type="TOOL_RESULT",
        agent_id=agent_id, agent_run_id=agent_run_id,
        goal=f"Verify tool '{tool_name}' side effect",
        output_ref=result), collector.records())
    await engine.run_checks(evaluation.id, organization_id=organization_id, checks=[
        {"kind": "side_effect", "name": "side_effect",
         "target": {"provider_success": bool(result.get("success", result.get("ok", True))),
                    "provider_id": str(result.get("message_id", result.get("id", ""))),
                    "independently_verified": independently_verified},
         "params": {}, "required": True}])
    if expected:
        await engine.run_checks(evaluation.id, organization_id=organization_id, checks=[
            {"kind": "output_contains", "name": "expected_markers",
             "target": result, "params": {"contains": list(expected.get("contains", []))},
             "required": True}])
    return await engine.finalize(evaluation.id, organization_id=organization_id)


async def verify_mcp_result(db: AsyncSession, *, organization_id: UUID,
                            server: str, tool: str, result: dict[str, Any],
                            independent_state: Optional[dict[str, Any]] = None,
                            **kwargs: Any) -> dict[str, Any]:
    """MCP verification uses Tool Runtime evidence; server claims alone never
    prove external state — independent_state is required to pass."""
    merged = await verify_tool_call(
        db, organization_id=organization_id,
        tool_name=f"mcp.{server}.{tool}", result=result,
        independently_verified=independent_state is not None, **kwargs)
    return merged


async def verify_browser_action(db: AsyncSession, *, organization_id: UUID,
                                observed: dict[str, Any],
                                expectations: Optional[dict[str, Any]] = None,
                                agent_run_id: Optional[UUID] = None,
                                ) -> dict[str, Any]:
    """'Button clicked' != 'operation succeeded': verify URL/DOM/success."""
    engine = EvaluatorEngine(db)
    collector = _collector(organization_id, "", "")
    collector.add(EvidenceType.BROWSER_STATE, observed, source="browser",
                  source_type="TOOL", source_id=str(observed.get("url", "")))
    if observed.get("dom"):
        collector.add(EvidenceType.DOM_STATE, {"dom": observed["dom"]},
                      source="browser", source_type="TOOL")
    evaluation = await engine.create_evaluation(CreateEvaluation(
        organization_id=organization_id, evaluation_type="BROWSER_RESULT",
        agent_run_id=agent_run_id,
        goal="Verify browser action achieved expected state",
        output_ref=observed), collector.records())
    await engine.run_checks(evaluation.id, organization_id=organization_id, checks=[
        {"kind": "browser_state", "name": "page_ok", "target": observed,
         "params": dict(expectations or {"forbid_challenge": True}),
         "required": True}])
    return await engine.finalize(evaluation.id, organization_id=organization_id)


async def verify_code_change(db: AsyncSession, *, organization_id: UUID,
                             test_summary: Optional[dict[str, Any]] = None,
                             secret_findings: Optional[list] = None,
                             git_state: Optional[dict[str, Any]] = None,
                             diff_files: Optional[list[str]] = None,
                             agent_run_id: Optional[UUID] = None,
                             ) -> dict[str, Any]:
    """Code pipeline: tests + secret scan + git state. No self-declared success."""
    engine = EvaluatorEngine(db)
    collector = _collector(organization_id, "", "")
    if test_summary is not None:
        collector.add(EvidenceType.TEST_RESULT, test_summary,
                      source="sandbox_runner", source_type="SYSTEM")
    collector.add(EvidenceType.GIT_STATE,
                  {"git": git_state or {}, "diff_files": diff_files or []},
                  source="git", source_type="SYSTEM")
    evaluation = await engine.create_evaluation(CreateEvaluation(
        organization_id=organization_id, evaluation_type="CODE_QUALITY",
        agent_run_id=agent_run_id,
        goal="Verify code change builds, passes tests, and is clean",
        output_ref={"diff_files": diff_files or []}), collector.records())
    checks = [{"kind": "secret_scan", "name": "no_secrets",
               "target": {"findings": secret_findings or []},
               "params": {}, "required": True, "critical_safety": True}]
    if test_summary is not None:
        checks.append({"kind": "test_summary", "name": "tests",
                       "target": test_summary, "params": {}, "required": True})
    if git_state:
        checks.append({"kind": "git_state", "name": "git",
                       "target": git_state, "params": {"require_commit": True},
                       "required": False})
    await engine.run_checks(evaluation.id, organization_id=organization_id, checks=checks)
    return await engine.finalize(evaluation.id, organization_id=organization_id,
                                 quality_threshold=0.8)


async def verify_workflow_execution(db: AsyncSession, *, organization_id: UUID,
                                    workflow_id: Optional[UUID] = None,
                                    workflow_execution_id: Optional[UUID] = None,
                                    node_states: Optional[dict[str, str]] = None,
                                    required_nodes: Optional[list[str]] = None,
                                    forbid_failed: bool = True,
                                    ) -> dict[str, Any]:
    engine = EvaluatorEngine(db)
    collector = _collector(organization_id, str(workflow_execution_id or ""))
    collector.add(EvidenceType.WORKFLOW_EVENT,
                  {"nodes": node_states or {}, "required": required_nodes or []},
                  source="workflow_engine", source_type="SYSTEM")
    evaluation = await engine.create_evaluation(CreateEvaluation(
        organization_id=organization_id, evaluation_type="WORKFLOW_RESULT",
        workflow_id=workflow_id, workflow_execution_id=workflow_execution_id,
        goal="Verify workflow required nodes succeeded",
        output_ref=node_states or {}), collector.records())
    await engine.run_checks(evaluation.id, organization_id=organization_id, checks=[
        {"kind": "workflow_nodes", "name": "nodes_ok",
         "target": node_states or {},
         "params": {"required_nodes": required_nodes or [],
                    "forbid_failed": forbid_failed},
         "required": True}])
    return await engine.finalize(evaluation.id, organization_id=organization_id)


def supervisor_review_packet(*, worker_result: dict[str, Any],
                             verification: dict[str, Any],
                             worker_agent_id: str = "") -> dict[str, Any]:
    """Manager accept/reject/reassign packet. Never blindly trusts workers."""
    decision = verification.get("decision", "FAIL")
    return {"worker_agent_id": worker_agent_id,
            "worker_claim": worker_result.get("status", "unknown"),
            "verification_decision": decision,
            "score": verification.get("score", 0.0),
            "recommendation": ("accept" if decision == "PASS"
                               else "reassign" if decision in ("FAIL",) and
                               verification.get("correction_strategy") not in ("STOP",)
                               else "escalate" if decision == "UNCERTAIN"
                               else "reject"),
            "reasons": verification.get("reason_codes", []),
            "failure": verification.get("failure_reason", "")}


def build_handoff_context(*, task: str, requirements: Optional[list[str]] = None,
                          constraints: Optional[list[str]] = None,
                          current_state: Optional[dict[str, Any]] = None,
                          evidence: Optional[list[dict[str, Any]]] = None,
                          known_failures: Optional[list[str]] = None,
                          evaluation_results: Optional[list[dict[str, Any]]] = None,
                          remaining_work: Optional[list[str]] = None) -> dict[str, Any]:
    """Handoff without hidden chain-of-thought: task, evidence, failures, evals."""
    from openagent.approvals.hashing import redact_params
    return {"task": task, "requirements": list(requirements or []),
            "constraints": list(constraints or []),
            "current_state": redact_params(dict(current_state or {})),
            "evidence": redact_params(list(evidence or [])),
            "known_failures": list(known_failures or []),
            "evaluation_results": list(evaluation_results or []),
            "remaining_work": list(remaining_work or [])}


def memory_learning_payload(*, kind: str, content: dict[str, Any],
                            evaluation_id: str = "") -> dict[str, Any]:
    """Redacted, evaluation-linked memory payload. Current evidence always
    takes precedence over this at read time (memory != proof)."""
    from openagent.approvals.hashing import redact_params
    allowed = {"successful_strategy", "known_failure_pattern",
               "validated_preference", "workflow_learning"}
    if kind not in allowed:
        raise ValueError(f"Unknown memory learning kind '{kind}'")
    return {"kind": kind, "content": redact_params(dict(content)),
            "evaluation_id": evaluation_id,
            "precedence": "current_evidence_wins"}


class EvaluatorReviewProvider:
    """MP20 plug-in for the management ReviewProvider boundary.

    Maps evaluator decisions onto manager review statuses without changing
    manager semantics: PASS->APPROVED, FAIL->REVISION_REQUIRED (bounded
    revision loop), UNCERTAIN->ESCALATE, safety STOP->REJECTED.
    """

    def __init__(self, db: AsyncSession, organization_id: UUID,
                 quality_threshold: float = 0.7):
        self.db = db
        self.organization_id = organization_id
        self.quality_threshold = quality_threshold

    async def review(self, *, output: dict[str, Any],
                     criteria: list[Any],
                     context: Optional[dict[str, Any]] = None):
        from openagent.management.review import CriterionResult, ReviewResult
        from openagent.management.types import ReviewStatus
        context = context or {}
        checks = []
        for criterion in criteria:
            verification = getattr(criterion, "verification", "") or ""
            description = getattr(criterion, "description", str(criterion))
            if verification.startswith("output_contains:"):
                checks.append({"kind": "output_contains",
                               "name": description[:200],
                               "target": output,
                               "params": {"contains": [verification.split(":", 1)[1].strip()]},
                               "required": True})
            elif verification.startswith("field_present:"):
                needle = verification.split(":", 1)[1].strip()
                checks.append({"kind": "json_schema",
                               "name": description[:200],
                               "target": output,
                               "params": {"schema": {"type": "object",
                                                    "required": [needle]}},
                               "required": True})
        outcome = await evaluate_agent_run(
            self.db, organization_id=self.organization_id,
            output=output, criteria=[{"name": getattr(c, "description", str(c)),
                                      "description": getattr(c, "description", ""),
                                      "method": "output_contains"}
                                     for c in criteria],
            goal=str(context.get("goal", "")),
            quality_threshold=self.quality_threshold,
            checks=checks,
            agent_id=context.get("agent_id"),
            agent_run_id=context.get("agent_run_id"))
        decision = outcome.get("decision", "FAIL")
        if decision == "PASS":
            status = ReviewStatus.APPROVED
        elif decision == "UNCERTAIN" or outcome.get("status") == "UNCERTAIN":
            status = ReviewStatus.ESCALATE
        elif outcome.get("correction_strategy") == "STOP":
            status = ReviewStatus.REJECTED
        else:
            status = ReviewStatus.REVISION_REQUIRED
        return ReviewResult(
            status=status,
            criteria_results=[CriterionResult(
                description=c, satisfied=(decision == "PASS"),
                evidence="evaluator") for c in outcome.get("reason_codes", [])],
            issues=[outcome.get("failure_reason", "")] if outcome.get("failure_reason") else [],
            required_changes=[],
            evidence=outcome.get("reason_codes", []),
            reviewer_agent_id="evaluator",
            revision_number=int(context.get("revision_number", 0)))
