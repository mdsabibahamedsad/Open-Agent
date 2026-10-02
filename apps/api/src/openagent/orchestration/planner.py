"""Orchestration planner abstraction.

Rule-based planner ships in this phase (deterministic decomposition).
LLM-backed planning reuses the Agent Runtime via ``plan_with_agent`` hook;
model output is always validated with validator.validate_plan and never
executed blindly.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from openagent.orchestration.types import (
    AggregationStrategy,
    DependencyPolicy,
    PlannedTask,
    TaskPlan,
    TaskPriority,
)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")


class OrchestrationPlanner(ABC):
    @abstractmethod
    async def create_plan(
        self,
        objective: str,
        context: Optional[Dict[str, Any]] = None,
        constraints: Optional[Dict[str, Any]] = None,
    ) -> TaskPlan:
        ...


class RuleBasedPlanner(OrchestrationPlanner):
    """Deterministic planner: splits objective into research/plan/build/verify
    stages with explicit dependencies. Safe default when no LLM is configured."""

    async def create_plan(
        self,
        objective: str,
        context: Optional[Dict[str, Any]] = None,
        constraints: Optional[Dict[str, Any]] = None,
    ) -> TaskPlan:
        context = context or {}
        constraints = constraints or {}
        hints = _extract_hints(objective)
        tasks: List[PlannedTask] = []
        # Roots can run in parallel.
        for i, hint in enumerate(hints[:4]):
            tasks.append(
                PlannedTask(
                    task_id=f"research_{i + 1}",
                    title=f"Research: {hint}",
                    description=f"Gather evidence for '{hint}' in service of: {objective}",
                    instructions="Produce evidence-backed findings with sources. No secrets in output.",
                    required_capabilities=["research.web"],
                    priority=TaskPriority.HIGH,
                    input={"objective": objective, "focus": hint},
                )
            )
        roots = [t.task_id for t in tasks] or ["research_1"]
        if not tasks:
            tasks.append(
                PlannedTask(
                    task_id="research_1",
                    title="Research requirements",
                    description=objective,
                    required_capabilities=["research.web"],
                    priority=TaskPriority.HIGH,
                )
            )
            roots = ["research_1"]
        tasks.append(
            PlannedTask(
                task_id="specification",
                title="Draft specification",
                description=f"Consolidate research into a spec for: {objective}",
                dependencies=list(roots),
                dependency_policy=DependencyPolicy.ALL_SUCCESS,
                required_capabilities=["content.writing"],
                aggregation_strategy=AggregationStrategy.SUMMARIZE,
                input={"objective": objective},
            )
        )
        tasks.append(
            PlannedTask(
                task_id="implementation",
                title="Implement",
                description=f"Implement the specification for: {objective}",
                dependencies=["specification"],
                required_capabilities=["coding.python"],
                input={"objective": objective},
            )
        )
        tasks.append(
            PlannedTask(
                task_id="review",
                title="Review and finalize",
                description="Validate implementation against the specification.",
                dependencies=["implementation"],
                required_capabilities=["testing.automation"],
                aggregation_strategy=AggregationStrategy.VALIDATE,
            )
        )
        for key in ("risk_level", "requires_approval", "max_tasks"):
            if key in constraints:
                pass  # constraints enforced by validator/service, not planner text
        _ = context
        return TaskPlan(objective=objective, tasks=tasks, metadata={"planner": "rule-based"})


def _extract_hints(objective: str) -> List[str]:
    parts = [p.strip(" -•\t") for p in _SENTENCE_SPLIT.split(objective) if p.strip()]
    if not parts:
        return ["requirements"]
    hints = parts[:4]
    # Keep hints short for task titles.
    return [h[:80] for h in hints]


async def plan_with_agent(
    planner_agent_call: Any,
    objective: str,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Hook for LLM-backed planning through the existing Agent Runtime.

    ``planner_agent_call`` is an async callable ``(prompt) -> dict`` wired by
    the service layer to AgentLoop/Model Router. Raw output is returned as
    data; callers must pass it through ``parse_plan_dict`` + validator.
    """
    prompt = (
        "Decompose the following objective into a structured task plan. "
        "Return JSON with tasks: [{task_id,title,description,dependencies,"
        "required_capabilities,priority}]. "
        f"Objective: {objective} Context: {(context or {})}"
    )
    result = await planner_agent_call(prompt)
    if isinstance(result, dict):
        return result
    return {"raw": result}


def parse_plan_dict(raw: Dict[str, Any], objective: str = "") -> TaskPlan:
    tasks: List[PlannedTask] = []
    for item in raw.get("tasks", []) or []:
        try:
            tasks.append(
                PlannedTask(
                    task_id=str(item.get("task_id", "")),
                    title=str(item.get("title", "")),
                    description=str(item.get("description", "")),
                    dependencies=list(item.get("dependencies", []) or []),
                    required_capabilities=list(item.get("required_capabilities", []) or []),
                )
            )
        except Exception:
            continue
    return TaskPlan(
        objective=str(raw.get("objective", objective)),
        tasks=tasks,
        metadata={"planner": "agent-assisted"},
    )
