"""Quality-control workflow node executors (MP20).

Pure, deterministic nodes that run inside the EXISTING workflow engine
(registry -> engine -> node). No separate runtime, no LLM calls here —
LLM votes happen through the evaluations API where budgets apply.

- ``verify``        — deterministic checks over resolved inputs.
- ``evaluate``      — threshold decision over a score + checks.
- ``assert``        — hard success/failure condition.
- ``quality_gate``  — gate definition evaluated inline (built-in or literal).
- ``retry``         — bounded retry descriptor (counter lives in inputs).
- ``correct``       — correction-plan descriptor (server executes via API).
- Human review reuses the existing ``approval`` node (no duplicate system).
"""

from __future__ import annotations

from typing import Any, Dict

from openagent.evaluator.deterministic import run_check
from openagent.evaluator.gates import get_builtin_gate
from openagent.evaluator.scoring import normalize_score
from openagent.runtime.engine import resolve_expressions
from openagent.runtime.executors.base import (
    NodeExecutionContext,
    NodeExecutionResult,
    NodeExecutor,
    NodeRunStatus,
)


def _fail(message: str, code: str = "INVALID_CONFIG") -> NodeExecutionResult:
    return NodeExecutionResult(status=NodeRunStatus.FAILED, error=message,
                               error_code=code)


def _target_for(spec: Dict[str, Any], cfg: Dict[str, Any],
                context: NodeExecutionContext) -> Any:
    if "target" in spec:
        return spec.get("target")
    if "target" in cfg:
        return cfg.get("target")
    return dict(context.inputs or {})


class VerifyNodeExecutor(NodeExecutor):
    """Deterministic verification node."""

    node_type = "verify"
    default_timeout = 120
    required_capabilities = ["evaluation"]

    async def execute(self, node_config: Dict[str, Any],
                      context: NodeExecutionContext) -> NodeExecutionResult:
        try:
            cfg = resolve_expressions(node_config, context)
        except Exception as e:
            return _fail(f"Failed to resolve expressions: {e}", "EXPRESSION_ERROR")
        checks = cfg.get("checks")
        if not isinstance(checks, list) or not checks:
            return _fail("verify node requires non-empty 'checks' list")
        results = []
        for spec in checks:
            if not isinstance(spec, dict) or not spec.get("kind"):
                return _fail("each check needs a 'kind'")
            result = run_check(str(spec["kind"]), _target_for(spec, cfg, context),
                               dict(spec.get("params", {}) or {}),
                               name=str(spec.get("name", spec["kind"])),
                               required=bool(spec.get("required", True)))
            result.critical_safety = bool(spec.get("critical_safety", False))
            results.append({"name": result.name, "passed": result.passed,
                            "reason": result.reason, "required": result.required,
                            "critical_safety": result.critical_safety})
        failed = [r for r in results if r["required"] and not r["passed"]]
        safety = any(r["critical_safety"] and not r["passed"] for r in results)
        passed = not failed and not safety
        outputs = {"verified": passed,
                   "checks": results,
                   "failed_checks": [r["name"] for r in failed],
                   "safety_hit": safety}
        if passed:
            return NodeExecutionResult(status=NodeRunStatus.SUCCEEDED,
                                       outputs=outputs,
                                       metadata={"node_type": self.node_type})
        return NodeExecutionResult(
            status=NodeRunStatus.FAILED,
            outputs=outputs,
            error=f"verification failed: {', '.join(r['name'] for r in failed) or 'safety'}",
            error_code="VERIFICATION_FAILED", error_retryable=not safety,
            metadata={"node_type": self.node_type})


class EvaluateNodeExecutor(NodeExecutor):
    """Threshold quality-evaluation node (score + required checks)."""

    node_type = "evaluate"
    default_timeout = 120
    required_capabilities = ["evaluation"]

    async def execute(self, node_config: Dict[str, Any],
                      context: NodeExecutionContext) -> NodeExecutionResult:
        try:
            cfg = resolve_expressions(node_config, context)
        except Exception as e:
            return _fail(f"Failed to resolve expressions: {e}", "EXPRESSION_ERROR")
        raw_score = cfg.get("score", context.inputs.get("score", 0))
        try:
            score = normalize_score(raw_score)
        except Exception:
            return _fail("'score' must be numeric (0..1 or 0..100)")
        threshold = float(cfg.get("quality_threshold", 0.7))
        checks = []
        for spec in cfg.get("checks", []) or []:
            if not isinstance(spec, dict) or not spec.get("kind"):
                return _fail("each check needs a 'kind'")
            result = run_check(str(spec["kind"]), _target_for(spec, cfg, context),
                               dict(spec.get("params", {}) or {}),
                               name=str(spec.get("name", spec["kind"])),
                               required=bool(spec.get("required", True)))
            checks.append({"name": result.name, "passed": result.passed,
                           "reason": result.reason})
        failed = [c for c in checks if not c["passed"]]
        passed = score >= threshold and not failed
        outputs = {"decision": "PASS" if passed else "FAIL", "score": score,
                   "threshold": threshold, "checks": checks}
        if passed:
            return NodeExecutionResult(status=NodeRunStatus.SUCCEEDED,
                                       outputs=outputs,
                                       metadata={"node_type": self.node_type})
        return NodeExecutionResult(
            status=NodeRunStatus.FAILED, outputs=outputs,
            error=f"score {score} < {threshold}" if score < threshold
            else f"checks failed: {', '.join(c['name'] for c in failed)}",
            error_code="EVALUATION_FAILED", error_retryable=True,
            metadata={"node_type": self.node_type})


class AssertNodeExecutor(NodeExecutor):
    """Hard assert node: all conditions must hold or the branch fails."""

    node_type = "assert"
    default_timeout = 60
    required_capabilities = ["evaluation"]

    async def execute(self, node_config: Dict[str, Any],
                      context: NodeExecutionContext) -> NodeExecutionResult:
        try:
            cfg = resolve_expressions(node_config, context)
        except Exception as e:
            return _fail(f"Failed to resolve expressions: {e}", "EXPRESSION_ERROR")
        conditions = cfg.get("conditions")
        if not isinstance(conditions, list) or not conditions:
            return _fail("assert node requires non-empty 'conditions' list")
        failures = []
        for cond in conditions:
            if not isinstance(cond, dict) or not cond.get("kind"):
                return _fail("each condition needs a 'kind'")
            result = run_check(str(cond["kind"]), _target_for(cond, cfg, context),
                               dict(cond.get("params", {}) or {}),
                               name=str(cond.get("name", cond["kind"])),
                               required=True)
            if not result.passed:
                failures.append(f"{result.name}: {result.reason}")
        if failures:
            return NodeExecutionResult(
                status=NodeRunStatus.FAILED,
                outputs={"asserted": False, "failures": failures},
                error=f"assertion failed: {'; '.join(failures[:3])}",
                error_code="ASSERTION_FAILED", error_retryable=False,
                metadata={"node_type": self.node_type})
        return NodeExecutionResult(status=NodeRunStatus.SUCCEEDED,
                                   outputs={"asserted": True, "failures": []},
                                   metadata={"node_type": self.node_type})


class QualityGateNodeExecutor(NodeExecutor):
    """Inline quality-gate node (built-in gate or literal definition)."""

    node_type = "quality_gate"
    default_timeout = 120
    required_capabilities = ["evaluation"]

    async def execute(self, node_config: Dict[str, Any],
                      context: NodeExecutionContext) -> NodeExecutionResult:
        try:
            cfg = resolve_expressions(node_config, context)
        except Exception as e:
            return _fail(f"Failed to resolve expressions: {e}", "EXPRESSION_ERROR")
        gate = None
        if cfg.get("gate"):
            gate = get_builtin_gate(str(cfg["gate"]))
            if gate is None:
                return _fail(f"unknown built-in gate '{cfg['gate']}'")
        elif isinstance(cfg.get("definition"), dict):
            gate = cfg["definition"]
        else:
            return _fail("quality_gate node requires 'gate' or 'definition'")
        targets = dict(cfg.get("check_targets", {}) or {})
        results = []
        for spec in gate.get("required_checks", []) or []:
            name = str(spec.get("name", spec.get("kind", "check")))
            target = targets.get(name, spec.get("target"))
            result = run_check(str(spec.get("kind", "")), target,
                               dict(spec.get("params", {}) or {}),
                               name=name, required=bool(spec.get("required", True)))
            result.critical_safety = bool(spec.get("critical_safety", False))
            results.append(result)
        failed = [r for r in results if r.required and not r.passed]
        safety = any(r.critical_safety and not r.passed for r in results)
        score = normalize_score(cfg.get("score", context.inputs.get("score", 1.0)))
        thresholds = gate.get("thresholds", {}) or {}
        passed = (not failed and not safety
                  and score >= float(thresholds.get("min_score", 0.0)))
        behavior = str(gate.get("failure_behavior", "FAIL"))
        outputs = {"gate": gate.get("name"), "passed": passed,
                   "score": score, "failure_behavior": behavior,
                   "approval_required": bool(gate.get("approval_required")),
                   "checks": [{"name": r.name, "passed": r.passed,
                               "reason": r.reason} for r in results]}
        # Approval-gated definitions park for human review even when checks
        # pass (the durable API path verifies the actual MP19 approval).
        if gate.get("approval_required") and not cfg.get("approval_id"):
            return NodeExecutionResult(status=NodeRunStatus.WAITING, outputs=outputs,
                                       metadata={"node_type": self.node_type,
                                                 "reason": "gate requires human approval"})
        if passed:
            return NodeExecutionResult(status=NodeRunStatus.SUCCEEDED,
                                       outputs=outputs,
                                       metadata={"node_type": self.node_type})
        if behavior == "REQUEST_HUMAN" or gate.get("approval_required"):
            return NodeExecutionResult(status=NodeRunStatus.WAITING, outputs=outputs,
                                       metadata={"node_type": self.node_type,
                                                 "reason": "gate requires human review"})
        return NodeExecutionResult(
            status=NodeRunStatus.FAILED, outputs=outputs,
            error=f"quality gate '{gate.get('name')}' failed",
            error_code="QUALITY_GATE_FAILED",
            error_retryable=behavior in ("RETRY", "CORRECT"),
            metadata={"node_type": self.node_type})


class RetryNodeExecutor(NodeExecutor):
    """Bounded retry descriptor: counter lives in inputs, never infinite."""

    node_type = "retry"
    default_timeout = 60
    required_capabilities = ["evaluation"]

    async def execute(self, node_config: Dict[str, Any],
                      context: NodeExecutionContext) -> NodeExecutionResult:
        try:
            cfg = resolve_expressions(node_config, context)
        except Exception as e:
            return _fail(f"Failed to resolve expressions: {e}", "EXPRESSION_ERROR")
        max_attempts = int(cfg.get("max_attempts", 3))
        if not 1 <= max_attempts <= 10:
            return _fail("'max_attempts' must be 1..10")
        attempt = 0
        try:
            attempt = int(cfg.get("attempt", context.inputs.get("attempt", 0)))
        except (TypeError, ValueError):
            attempt = 0
        attempt += 1
        if attempt > max_attempts:
            return NodeExecutionResult(
                status=NodeRunStatus.FAILED,
                outputs={"attempt": attempt, "max_attempts": max_attempts,
                         "exhausted": True},
                error=f"retry budget exhausted ({max_attempts} attempts)",
                error_code="RETRY_EXHAUSTED", error_retryable=False,
                metadata={"node_type": self.node_type})
        backoff = str(cfg.get("backoff", "exponential"))
        delay = min(300, (2 ** (attempt - 1)) * 5) if backoff == "exponential" else 5
        return NodeExecutionResult(
            status=NodeRunStatus.SUCCEEDED,
            outputs={"attempt": attempt, "max_attempts": max_attempts,
                     "exhausted": False, "backoff_seconds": delay},
            metadata={"node_type": self.node_type})


class CorrectNodeExecutor(NodeExecutor):
    """Correction-plan descriptor: the API/server executes bounded correction."""

    node_type = "correct"
    default_timeout = 60
    required_capabilities = ["evaluation"]

    async def execute(self, node_config: Dict[str, Any],
                      context: NodeExecutionContext) -> NodeExecutionResult:
        try:
            cfg = resolve_expressions(node_config, context)
        except Exception as e:
            return _fail(f"Failed to resolve expressions: {e}", "EXPRESSION_ERROR")
        strategy = str(cfg.get("strategy", "RETRY_SAME")).upper()
        from openagent.evaluator.types import CorrectionStrategy
        try:
            parsed = CorrectionStrategy(strategy)
        except ValueError:
            return _fail(f"unknown correction strategy '{strategy}'")
        failure_class = str(cfg.get("failure_class", "UNKNOWN")).upper()
        from openagent.evaluator.types import FailureClass
        try:
            FailureClass(failure_class)
        except ValueError:
            return _fail(f"unknown failure class '{failure_class}'")
        max_cycles = int(cfg.get("max_correction_cycles", 3))
        if not 1 <= max_cycles <= 10:
            return _fail("'max_correction_cycles' must be 1..10")
        cycle = 0
        try:
            cycle = int(cfg.get("cycle", context.inputs.get("cycle", 0)))
        except (TypeError, ValueError):
            cycle = 0
        cycle += 1
        if cycle > max_cycles:
            return NodeExecutionResult(
                status=NodeRunStatus.FAILED,
                outputs={"cycle": cycle, "strategy": parsed.value,
                         "loop_stopped": True},
                error="correction budget exhausted; escalate",
                error_code="CORRECTION_EXHAUSTED", error_retryable=False,
                metadata={"node_type": self.node_type})
        return NodeExecutionResult(
            status=NodeRunStatus.SUCCEEDED,
            outputs={"cycle": cycle, "max_correction_cycles": max_cycles,
                     "strategy": parsed.value, "failure_class": failure_class,
                     "changes": cfg.get("changes", {}),
                     "root_cause": cfg.get("root_cause", {})},
            metadata={"node_type": self.node_type})
