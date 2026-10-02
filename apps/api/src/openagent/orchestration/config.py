"""Organization-level orchestration settings and feature flags."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict

from openagent.orchestration.types import Budget

FEATURE_FLAGS = [
    "multi_agent_orchestration",
    "agent_delegation",
    "agent_handoff",
    "parallel_agents",
    "agent_reassignment",
    "orchestration_workspace",
]


@dataclass
class OrchestrationOrgSettings:
    max_agents_per_run: int = 50
    max_tasks_per_run: int = 200
    max_delegation_depth: int = 5
    max_parallel_agents: int = 10
    default_timeout_seconds: int = 600
    default_budget: Budget = field(default_factory=Budget)
    allow_agent_delegation: bool = True
    allow_cross_team_delegation: bool = False
    require_approval_for_high_risk: bool = True
    flags: Dict[str, bool] = field(
        default_factory=lambda: {name: True for name in FEATURE_FLAGS}
    )

    def is_enabled(self, flag: str) -> bool:
        return bool(self.flags.get(flag, False))

    @classmethod
    def from_organization_settings(cls, settings: Dict[str, Any] | None) -> "OrchestrationOrgSettings":
        settings = settings or {}
        orch = settings.get("orchestration", {}) if isinstance(settings, dict) else {}
        base = cls()
        for key in (
            "max_agents_per_run",
            "max_tasks_per_run",
            "max_delegation_depth",
            "max_parallel_agents",
            "default_timeout_seconds",
            "allow_agent_delegation",
            "allow_cross_team_delegation",
            "require_approval_for_high_risk",
        ):
            if key in orch:
                try:
                    setattr(base, key, orch[key])
                except Exception:
                    pass
        flags = orch.get("feature_flags", {})
        if isinstance(flags, dict):
            for name in FEATURE_FLAGS:
                if name in flags:
                    base.flags[name] = bool(flags[name])
        budget = orch.get("default_budget", {})
        if isinstance(budget, dict) and budget:
            for key in (
                "max_total_steps",
                "max_total_tokens",
                "max_total_cost",
                "max_execution_time_seconds",
                "max_tasks",
                "max_agents",
                "max_delegation_depth",
                "max_tool_calls",
                "max_parallel_tasks",
            ):
                if key in budget:
                    try:
                        setattr(base.default_budget, key, budget[key])
                    except Exception:
                        pass
        return base
