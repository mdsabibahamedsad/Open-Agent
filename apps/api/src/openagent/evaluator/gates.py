"""Reusable quality gates (MP20).

A gate bundles required deterministic checks + score thresholds + failure
behavior + optional approval requirement. Production Deployment Gate ships as
a built-in definition; org gates live in DB (versioned by row version).
"""

from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.evaluator.deterministic import run_check
from openagent.evaluator.scoring import normalize_score
from openagent.evaluator.types import CheckResult

logger = structlog.get_logger("openagent.evaluator.gates")

BUILTIN_GATES: dict[str, dict[str, Any]] = {
    "code_build_gate": {
        "name": "Code Build Gate",
        "required_checks": [
            {"kind": "test_summary", "name": "build_tests",
             "required": True, "target": {"passed": 1, "failed": 0}},
            {"kind": "secret_scan", "name": "no_secrets", "required": True,
             "critical_safety": True, "target": {"findings": []}},
        ],
        "thresholds": {"min_score": 0.8},
        "failure_behavior": "FAIL",
    },
    "security_gate": {
        "name": "Security Gate",
        "required_checks": [
            {"kind": "secret_scan", "name": "no_secrets", "required": True,
             "critical_safety": True, "target": {"findings": []}},
        ],
        "thresholds": {"min_score": 1.0},
        "failure_behavior": "STOP",
    },
    "research_quality_gate": {
        "name": "Research Quality Gate",
        "required_checks": [
            {"kind": "output_contains", "name": "has_citations",
             "required": True, "target": "", "params": {"contains": []}},
        ],
        "thresholds": {"min_score": 0.7, "min_confidence": 0.6},
        "failure_behavior": "CORRECT",
    },
    "workflow_success_gate": {
        "name": "Workflow Success Gate",
        "required_checks": [
            {"kind": "workflow_nodes", "name": "nodes_ok", "required": True,
             "target": {}, "params": {"required_nodes": []}},
        ],
        "thresholds": {"min_score": 0.7},
        "failure_behavior": "RETRY",
    },
    "browser_completion_gate": {
        "name": "Browser Completion Gate",
        "required_checks": [
            {"kind": "browser_state", "name": "page_ok", "required": True,
             "target": {}, "params": {"forbid_challenge": True}},
        ],
        "thresholds": {"min_score": 0.75},
        "failure_behavior": "CORRECT",
    },
    "data_validation_gate": {
        "name": "Data Validation Gate",
        "required_checks": [
            {"kind": "json_schema", "name": "schema_ok", "required": True,
             "target": {}, "params": {"schema": {"type": "object"}}},
        ],
        "thresholds": {"min_score": 0.9},
        "failure_behavior": "FAIL",
    },
    "production_deployment_gate": {
        "name": "Production Deployment Gate",
        "required_checks": [
            {"kind": "test_summary", "name": "build_tests",
             "required": True, "target": {"passed": 1, "failed": 0}},
            {"kind": "secret_scan", "name": "no_secrets", "required": True,
             "critical_safety": True, "target": {"findings": []}},
        ],
        "thresholds": {"min_score": 0.9, "min_confidence": 0.7},
        "failure_behavior": "STOP",
        "approval_required": True,
        "requires": ["build passes", "tests pass", "security scan passes",
                     "no critical issues", "deployment approval exists"],
    },
}


def get_builtin_gate(name: str) -> Optional[dict[str, Any]]:
    return BUILTIN_GATES.get((name or "").lower())


def list_builtin_gates() -> list[str]:
    return sorted(BUILTIN_GATES)


async def evaluate_gate(*, db: AsyncSession, organization_id: UUID,  # noqa: ARG001
                        gate: dict[str, Any],
                        check_targets: Optional[dict[str, Any]] = None,
                        score: float = 1.0, confidence: float = 1.0) -> dict[str, Any]:
    """Evaluate a gate definition against provided targets + scores.

    check_targets maps check name -> observed state. All required conditions
    must pass; approval_required gates additionally need an approval_id whose
    existence/scope the caller verifies via MP19 (passed as approval_id).
    """
    check_targets = check_targets or {}
    results: list[CheckResult] = []
    for spec in gate.get("required_checks", []) or []:
        name = str(spec.get("name", spec.get("kind", "check")))
        target = check_targets.get(name, spec.get("target"))
        results.append(run_check(str(spec.get("kind", "")), target,
                                 dict(spec.get("params", {}) or {}),
                                 name=name,
                                 required=bool(spec.get("required", True))))
        results[-1].critical_safety = bool(spec.get("critical_safety", False))
    thresholds = gate.get("thresholds", {}) or {}
    min_score = float(thresholds.get("min_score", 0.0))
    min_conf = float(thresholds.get("min_confidence", 0.0))
    failed = [r for r in results if r.required and not r.passed]
    safety_hit = any(r.critical_safety and not r.passed for r in results)
    passed = (not failed and not safety_hit
              and normalize_score(score) >= min_score
              and normalize_score(confidence) >= min_conf)
    approval_needed = bool(gate.get("approval_required"))
    return {"passed": passed and not approval_needed,
            "passed_checks": passed,
            "approval_required": approval_needed,
            "approval_missing": approval_needed,  # caller resolves via MP19
            "failed_checks": [r.name for r in failed],
            "safety_hit": safety_hit,
            "failure_behavior": gate.get("failure_behavior", "FAIL"),
            "checks": [{"name": r.name, "passed": r.passed, "reason": r.reason}
                       for r in results]}


async def load_org_gates(db: AsyncSession,
                         organization_id: UUID) -> list[dict[str, Any]]:
    try:
        from openagent.db.models.evaluation import QualityGate
        result = await db.execute(
            select(QualityGate).where(
                QualityGate.organization_id == organization_id,
                QualityGate.is_active.is_(True)))
        return [{"id": str(g.id), "name": g.name,
                 "required_checks": list(g.required_checks or []),
                 "thresholds": dict(g.thresholds or {}),
                 "failure_behavior": g.failure_behavior,
                 "approval_required": bool(g.approval_required),
                 "version": g.version} for g in result.scalars().all()]
    except Exception as exc:  # pragma: no cover - gates optional pre-migration
        logger.warning("quality gate load skipped", error=str(exc))
        return []
