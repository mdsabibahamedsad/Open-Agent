"""Reusable manager decision loop: OBSERVE → … → COMPLETE.

Controlled state transitions only — no unrestricted recursive model calls.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from openagent.management.types import ManagerLoopBudget, ManagerLoopState, MANAGER_LOOP_ORDER


@dataclass
class LoopObservation:
    active_tasks: int = 0
    blocked_tasks: int = 0
    failed_tasks: int = 0
    pending_delegations: int = 0
    open_escalations: int = 0
    budget_consumed_fraction: float = 0.0
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ManagerLoopState_:
    state: ManagerLoopState = ManagerLoopState.OBSERVE
    decisions: int = 0
    replans: int = 0
    delegations: int = 0
    revisions: int = 0
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    history: List[str] = field(default_factory=list)


@dataclass
class LoopStep:
    next_state: ManagerLoopState
    action: str
    reason: str


class ManagerDecisionLoop:
    """Deterministic loop driver. The LLM (via Agent Runtime) proposes the
    *content* of each step; this machine owns the *transitions*."""

    def __init__(self, budget: Optional[ManagerLoopBudget] = None):
        self.budget = budget or ManagerLoopBudget()

    def initial(self) -> ManagerLoopState_:
        return ManagerLoopState_()

    def step(self, loop: ManagerLoopState_, observation: LoopObservation) -> LoopStep:
        """Advance one controlled step based on structured observation."""
        self._check_budget(loop, observation)
        idx = MANAGER_LOOP_ORDER.index(loop.state)
        current = loop.state

        if current == ManagerLoopState.OBSERVE:
            return LoopStep(ManagerLoopState.UNDERSTAND, "summarize", "observation collected")
        if current == ManagerLoopState.UNDERSTAND:
            if observation.blocked_tasks > 0 or observation.failed_tasks > 0:
                return LoopStep(ManagerLoopState.CORRECT, "triage", "blocked/failed work present")
            return LoopStep(ManagerLoopState.PLAN, "plan", "no blockers; proceed to plan")
        if current == ManagerLoopState.PLAN:
            return LoopStep(ManagerLoopState.DELEGATE, "delegate", "plan ready")
        if current == ManagerLoopState.DELEGATE:
            return LoopStep(ManagerLoopState.MONITOR, "monitor", "delegations issued")
        if current == ManagerLoopState.MONITOR:
            if observation.blocked_tasks > 0 or observation.open_escalations > 0:
                return LoopStep(ManagerLoopState.CORRECT, "correct", "attention needed")
            if observation.active_tasks == 0 and observation.pending_delegations == 0:
                return LoopStep(ManagerLoopState.REVIEW, "review", "work settled")
            return LoopStep(ManagerLoopState.MONITOR, "wait", "work in flight")
        if current == ManagerLoopState.REVIEW:
            if observation.failed_tasks > 0:
                return LoopStep(ManagerLoopState.CORRECT, "revise", "failures need correction")
            return LoopStep(ManagerLoopState.COMPLETE, "complete", "review passed")
        if current == ManagerLoopState.CORRECT:
            return LoopStep(ManagerLoopState.MONITOR, "re_monitor", "corrections applied")
        return LoopStep(ManagerLoopState.COMPLETE, "complete", "terminal")

    def apply(self, loop: ManagerLoopState_, step: LoopStep, *, kind: str = "decision") -> ManagerLoopState_:
        """Record a transition. `kind`: decision | replan | delegation | revision."""
        loop.history.append(f"{loop.state.value}->{step.next_state.value}:{step.action}")
        loop.state = step.next_state
        loop.decisions += 1
        if kind == "replan":
            loop.replans += 1
        elif kind == "delegation":
            loop.delegations += 1
        elif kind == "revision":
            loop.revisions += 1
        return loop

    def _check_budget(self, loop: ManagerLoopState_, observation: LoopObservation) -> None:
        elapsed = (datetime.now(timezone.utc) - loop.started_at).total_seconds()
        if loop.decisions >= self.budget.max_decisions:
            raise LoopBudgetExceeded("max decisions exceeded")
        if loop.replans > self.budget.max_replans:
            raise LoopBudgetExceeded("max replans exceeded")
        if loop.delegations > self.budget.max_delegations:
            raise LoopBudgetExceeded("max delegations exceeded")
        if loop.revisions > self.budget.max_revisions:
            raise LoopBudgetExceeded("max revisions exceeded")
        if elapsed > self.budget.max_time_seconds:
            raise LoopBudgetExceeded("max time exceeded")
        if observation.budget_consumed_fraction >= 1.0:
            raise LoopBudgetExceeded("cost budget exhausted")
        _ = elapsed


class LoopBudgetExceeded(Exception):
    pass


REPLAN_TRIGGERS = frozenset(
    {
        "task_failure",
        "new_information",
        "resource_unavailable",
        "deadline_change",
        "requirement_change",
        "repeated_revision",
        "dependency_failure",
    }
)


def should_replan(trigger: str, *, replans_used: int, max_replans: int) -> bool:
    return trigger in REPLAN_TRIGGERS and replans_used < max_replans
