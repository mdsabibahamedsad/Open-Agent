"""Plan validation: reject invalid orchestration plans before execution."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Set

from openagent.orchestration.task_graph import TaskNode, find_cycle, graph_depth
from openagent.orchestration.types import (
    DEFAULT_MAX_GRAPH_DEPTH,
    DEFAULT_MAX_TASKS_PER_RUN,
    RISK_ORDER,
    RiskLevel,
    TaskPlan,
)

TASK_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_\-]{0,127}$")

# Verbs that always require explicit human approval / high-risk handling.
DANGEROUS_HINTS = (
    "delete production",
    "drop database",
    "drop table",
    "rm -rf",
    "format disk",
    "disable auth",
    "exfiltrate",
    "send password",
)


@dataclass
class PlanValidationError:
    code: str
    message: str
    task_id: str | None = None


@dataclass
class PlanValidationResult:
    valid: bool
    errors: List[PlanValidationError] = field(default_factory=list)


def validate_plan(
    plan: TaskPlan,
    *,
    max_tasks: int = DEFAULT_MAX_TASKS_PER_RUN,
    max_depth: int = DEFAULT_MAX_GRAPH_DEPTH,
    max_delegation_depth: int = 5,
    known_agent_ids: Set[str] | None = None,
) -> PlanValidationResult:
    errors: List[PlanValidationError] = []

    if not plan.objective or not plan.objective.strip():
        errors.append(PlanValidationError("EMPTY_OBJECTIVE", "objective must not be empty"))

    if not plan.tasks:
        errors.append(PlanValidationError("EMPTY_PLAN", "plan must contain at least one task"))
        return PlanValidationResult(valid=False, errors=errors)

    if len(plan.tasks) > max_tasks:
        errors.append(
            PlanValidationError(
                "TOO_MANY_TASKS",
                f"plan has {len(plan.tasks)} tasks, limit is {max_tasks}",
            )
        )

    seen: Set[str] = set()
    nodes: Dict[str, TaskNode] = {}
    for t in plan.tasks:
        if not t.task_id or not TASK_ID_RE.match(t.task_id):
            errors.append(
                PlanValidationError("INVALID_TASK_ID", f"invalid task id: {t.task_id!r}", t.task_id)
            )
            continue
        if t.task_id in seen:
            errors.append(
                PlanValidationError("DUPLICATE_TASK_ID", f"duplicate task id: {t.task_id}", t.task_id)
            )
            continue
        seen.add(t.task_id)
        if not t.title or not t.title.strip():
            errors.append(
                PlanValidationError("EMPTY_TITLE", "task title must not be empty", t.task_id)
            )
        nodes[t.task_id] = TaskNode(
            task_id=t.task_id,
            dependencies=list(t.dependencies or []),
            dependency_policy=t.dependency_policy,
        )

    # Dependency references
    for t in plan.tasks:
        if t.task_id not in nodes:
            continue
        if t.parent_task_id and t.parent_task_id not in nodes and t.parent_task_id != t.task_id:
            # parent must exist unless it is the implicit root
            pass  # parents may be implicit; depth check below covers runaway nesting
        for dep in t.dependencies or []:
            if dep == t.task_id:
                errors.append(
                    PlanValidationError(
                        "SELF_DEPENDENCY", f"task depends on itself: {t.task_id}", t.task_id
                    )
                )
            elif dep not in nodes:
                errors.append(
                    PlanValidationError(
                        "UNKNOWN_DEPENDENCY",
                        f"task {t.task_id} depends on unknown task {dep}",
                        t.task_id,
                    )
                )

    # Cycles
    if nodes:
        cycle = find_cycle(nodes)
        if cycle:
            errors.append(
                PlanValidationError("CYCLE_DETECTED", f"dependency cycle: {' -> '.join(cycle)}")
            )
        else:
            try:
                depth = graph_depth(nodes)
                if depth > max_depth:
                    errors.append(
                        PlanValidationError(
                            "GRAPH_TOO_DEEP", f"graph depth {depth} exceeds limit {max_depth}"
                        )
                    )
            except ValueError:
                pass  # already reported as cycle

    # Agent references
    if known_agent_ids is not None:
        for t in plan.tasks:
            if t.assigned_agent_id and t.assigned_agent_id not in known_agent_ids:
                errors.append(
                    PlanValidationError(
                        "UNKNOWN_AGENT",
                        f"task {t.task_id} references unknown agent {t.assigned_agent_id}",
                        t.task_id,
                    )
                )

    # Risk propagation: child must not silently lower parent's risk level.
    by_id = {t.task_id: t for t in plan.tasks}
    for t in plan.tasks:
        if t.parent_task_id and t.parent_task_id in by_id:
            parent = by_id[t.parent_task_id]
            try:
                if RISK_ORDER[t.risk_level] < RISK_ORDER[parent.risk_level]:
                    errors.append(
                        PlanValidationError(
                            "RISK_DOWNGRADE",
                            f"task {t.task_id} risk {t.risk_level.value} is lower than "
                            f"parent {parent.task_id} risk {parent.risk_level.value}",
                            t.task_id,
                        )
                    )
            except KeyError:
                errors.append(
                    PlanValidationError("INVALID_RISK", f"invalid risk level on {t.task_id}", t.task_id)
                )

    # Dangerous actions must require approval
    for t in plan.tasks:
        blob = f"{t.title} {t.description} {t.instructions}".lower()
        if any(h in blob for h in DANGEROUS_HINTS) and not t.requires_approval:
            errors.append(
                PlanValidationError(
                    "DANGEROUS_ACTION",
                    f"task {t.task_id} looks dangerous and must set requires_approval=true",
                    t.task_id,
                )
            )
        if t.requires_approval and t.risk_level == RiskLevel.LOW:
            errors.append(
                PlanValidationError(
                    "APPROVAL_RISK_MISMATCH",
                    f"task {t.task_id} requires approval but risk is LOW; use MEDIUM or higher",
                    t.task_id,
                )
            )

    # Delegation depth via parent chain
    for t in plan.tasks:
        depth = _parent_chain_depth(t.task_id, by_id)
        if depth > max_delegation_depth:
            errors.append(
                PlanValidationError(
                    "DELEGATION_TOO_DEEP",
                    f"task {t.task_id} exceeds max delegation depth {max_delegation_depth}",
                    t.task_id,
                )
            )

    # Budgets / timeouts sanity
    for t in plan.tasks:
        if t.timeout_seconds <= 0 or t.timeout_seconds > 24 * 3600:
            errors.append(
                PlanValidationError(
                    "INVALID_TIMEOUT",
                    f"task {t.task_id} has invalid timeout {t.timeout_seconds}",
                    t.task_id,
                )
            )
        if t.max_retries < 0 or t.max_retries > 10:
            errors.append(
                PlanValidationError(
                    "INVALID_RETRIES",
                    f"task {t.task_id} has invalid max_retries {t.max_retries}",
                    t.task_id,
                )
            )

    return PlanValidationResult(valid=not errors, errors=errors)


def _parent_chain_depth(task_id: str, by_id: Dict[str, Any]) -> int:
    depth = 1
    seen = {task_id}
    current = by_id.get(task_id)
    parent = getattr(current, "parent_task_id", None) if current else None
    while parent:
        if parent in seen:
            return 999  # cycle in parent chain
        seen.add(parent)
        depth += 1
        current = by_id.get(parent)
        parent = getattr(current, "parent_task_id", None) if current else None
        if depth > 100:
            return depth
    return depth
