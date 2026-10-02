"""Budget accounting: allocation, consumption, and limit enforcement."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict

from openagent.orchestration.types import Budget


@dataclass
class BudgetState:
    limits: Budget = field(default_factory=Budget)
    consumed_tokens: int = 0
    consumed_cost: float = 0.0
    consumed_tool_calls: int = 0
    consumed_steps: int = 0
    consumed_tasks: int = 0
    consumed_agents: int = 0

    def check_fits(
        self,
        *,
        tokens: int = 0,
        cost: float = 0.0,
        tool_calls: int = 0,
        steps: int = 0,
        tasks: int = 0,
        agents: int = 0,
    ) -> tuple[bool, str | None]:
        if self.consumed_tokens + tokens > self.limits.max_total_tokens:
            return False, "token budget exceeded"
        if self.consumed_cost + cost > self.limits.max_total_cost:
            return False, "cost budget exceeded"
        if self.consumed_tool_calls + tool_calls > self.limits.max_tool_calls:
            return False, "tool-call budget exceeded"
        if self.consumed_steps + steps > self.limits.max_total_steps:
            return False, "step budget exceeded"
        if self.consumed_tasks + tasks > self.limits.max_tasks:
            return False, "task budget exceeded"
        if self.consumed_agents + agents > self.limits.max_agents:
            return False, "agent budget exceeded"
        return True, None

    def consume(
        self,
        *,
        tokens: int = 0,
        cost: float = 0.0,
        tool_calls: int = 0,
        steps: int = 0,
        tasks: int = 0,
        agents: int = 0,
    ) -> None:
        ok, reason = self.check_fits(
            tokens=tokens,
            cost=cost,
            tool_calls=tool_calls,
            steps=steps,
            tasks=tasks,
            agents=agents,
        )
        if not ok:
            raise BudgetExceeded(reason or "budget exceeded")
        self.consumed_tokens += tokens
        self.consumed_cost += cost
        self.consumed_tool_calls += tool_calls
        self.consumed_steps += steps
        self.consumed_tasks += tasks
        self.consumed_agents += agents

    def child_budget(self, fraction: float = 1.0) -> "Budget":
        """Derive a bounded child budget. Never exceeds parent remaining."""
        fraction = min(1.0, max(0.0, fraction))
        remaining_tokens = max(0, self.limits.max_total_tokens - self.consumed_tokens)
        remaining_cost = max(0.0, self.limits.max_total_cost - self.consumed_cost)
        remaining_tools = max(0, self.limits.max_tool_calls - self.consumed_tool_calls)
        remaining_steps = max(0, self.limits.max_total_steps - self.consumed_steps)
        return Budget(
            max_total_steps=int(remaining_steps * fraction),
            max_total_tokens=int(remaining_tokens * fraction),
            max_total_cost=round(remaining_cost * fraction, 6),
            max_execution_time_seconds=self.limits.max_execution_time_seconds,
            max_tasks=max(1, int(self.limits.max_tasks * fraction)),
            max_agents=max(1, int(self.limits.max_agents * fraction)),
            max_delegation_depth=self.limits.max_delegation_depth,
            max_tool_calls=int(remaining_tools * fraction),
            max_parallel_tasks=self.limits.max_parallel_tasks,
        )

    def warning_triggered(self, threshold: float = 0.8) -> bool:
        if self.limits.max_total_tokens and self.consumed_tokens >= self.limits.max_total_tokens * threshold:
            return True
        if self.limits.max_total_cost and self.consumed_cost >= self.limits.max_total_cost * threshold:
            return True
        return False

    def to_dict(self) -> Dict[str, object]:
        return {
            "limits": {
                "max_total_steps": self.limits.max_total_steps,
                "max_total_tokens": self.limits.max_total_tokens,
                "max_total_cost": self.limits.max_total_cost,
                "max_execution_time_seconds": self.limits.max_execution_time_seconds,
                "max_tasks": self.limits.max_tasks,
                "max_agents": self.limits.max_agents,
                "max_delegation_depth": self.limits.max_delegation_depth,
                "max_tool_calls": self.limits.max_tool_calls,
                "max_parallel_tasks": self.limits.max_parallel_tasks,
            },
            "consumed": {
                "tokens": self.consumed_tokens,
                "cost": self.consumed_cost,
                "tool_calls": self.consumed_tool_calls,
                "steps": self.consumed_steps,
                "tasks": self.consumed_tasks,
                "agents": self.consumed_agents,
            },
            "remaining": {
                "tokens": max(0, self.limits.max_total_tokens - self.consumed_tokens),
                "cost": round(max(0.0, self.limits.max_total_cost - self.consumed_cost), 6),
                "tool_calls": max(0, self.limits.max_tool_calls - self.consumed_tool_calls),
                "steps": max(0, self.limits.max_total_steps - self.consumed_steps),
            },
        }


class BudgetExceeded(Exception):
    pass
