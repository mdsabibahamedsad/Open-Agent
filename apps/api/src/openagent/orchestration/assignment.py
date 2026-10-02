"""Deterministic, explainable agent assignment.

Order of consideration (first match wins, reasons recorded):
1. explicit assignment (task.assigned_agent_id)
2. capability match (all required capabilities present)
3. availability / health
4. workload (fewest active tasks)
5. cost (cheapest advertised cost hint)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class AgentCandidate:
    agent_id: str
    capabilities: List[str] = field(default_factory=list)
    active_tasks: int = 0
    healthy: bool = True
    cost_hint: float = 0.0
    allowed: bool = True  # authorization / policy pre-check result
    model_available: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AssignmentResult:
    agent_id: str | None
    reasons: List[str] = field(default_factory=list)
    considered: int = 0


def _normalize(cap: str) -> str:
    return cap.strip().lower()


def capability_match(required: List[str], offered: List[str]) -> tuple[bool, List[str]]:
    offered_set = {_normalize(c) for c in offered}
    missing = [c for c in required if _normalize(c) not in offered_set]
    return (not missing, missing)


def assign_agent(
    *,
    required_capabilities: List[str],
    candidates: List[AgentCandidate],
    explicit_agent_id: Optional[str] = None,
) -> AssignmentResult:
    if explicit_agent_id:
        for c in candidates:
            if c.agent_id == explicit_agent_id:
                if not c.allowed:
                    return AssignmentResult(
                        None, [f"explicit agent {explicit_agent_id} denied by policy"], len(candidates)
                    )
                if not c.healthy:
                    return AssignmentResult(
                        None, [f"explicit agent {explicit_agent_id} unhealthy"], len(candidates)
                    )
                ok, missing = capability_match(required_capabilities, c.capabilities)
                if not ok:
                    return AssignmentResult(
                        None,
                        [f"explicit agent {explicit_agent_id} missing capabilities: {','.join(missing)}"],
                        len(candidates),
                    )
                return AssignmentResult(c.agent_id, ["explicit assignment"], len(candidates))
        return AssignmentResult(
            None, [f"explicit agent {explicit_agent_id} not found"], len(candidates)
        )

    eligible: List[tuple[AgentCandidate, List[str]]] = []
    for c in candidates:
        if not c.allowed:
            continue
        if not c.healthy:
            continue
        if not c.model_available:
            continue
        ok, missing = capability_match(required_capabilities, c.capabilities)
        if not ok:
            continue
        eligible.append((c, [f"capability match ({len(required_capabilities)} required)"]))

    if not eligible:
        return AssignmentResult(None, ["no eligible agent: capability/availability/policy"], len(candidates))

    # Deterministic sort: workload, then cost, then agent_id for stability.
    eligible.sort(key=lambda item: (item[0].active_tasks, item[0].cost_hint, item[0].agent_id))
    winner, reasons = eligible[0]
    reasons = reasons + [
        f"workload={winner.active_tasks}",
        f"cost_hint={winner.cost_hint}",
    ]
    return AssignmentResult(winner.agent_id, reasons, len(candidates))
