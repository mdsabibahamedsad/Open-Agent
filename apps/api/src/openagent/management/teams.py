"""Dynamic team formation: charters, membership, capacity, dissolution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from openagent.management.types import DynamicTeamType, TeamStatus
from openagent.orchestration.assignment import AgentCandidate


@dataclass
class TeamCharter:
    objective: str
    scope: str = ""
    responsibilities: Dict[str, List[str]] = field(default_factory=dict)  # role -> duties
    communication_rules: List[str] = field(default_factory=list)
    completion_criteria: List[str] = field(default_factory=list)
    deadline: Optional[str] = None
    budget: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TeamMemberSpec:
    agent_id: str
    role: str
    responsibilities: List[str] = field(default_factory=list)
    permissions: List[str] = field(default_factory=list)  # required (not granted)
    task_scope: List[str] = field(default_factory=list)  # task ids


@dataclass
class TeamFormationRequest:
    objective: str
    required_roles: Dict[str, List[str]]  # role -> required capabilities
    team_type: DynamicTeamType = DynamicTeamType.TEMPORARY
    max_size: int = 12
    charter: Optional[TeamCharter] = None
    budget: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FormedTeam:
    members: List[TeamMemberSpec]
    uncovered_roles: List[str]
    reasons: List[str]


def form_team(
    request: TeamFormationRequest,
    candidates_by_capability: Dict[str, List[AgentCandidate]],
    *,
    max_size: Optional[int] = None,
) -> FormedTeam:
    """Greedy capability cover: one best agent per role, no agent twice
    unless the team is too small to cover roles uniquely."""
    limit = max_size or request.max_size
    members: List[TeamMemberSpec] = []
    uncovered: List[str] = []
    reasons: List[str] = []
    used: set[str] = set()

    for role, capabilities in request.required_roles.items():
        pool = candidates_by_capability.get(role, [])
        fresh = [c for c in pool if c.agent_id not in used]
        ordered = sorted(fresh or pool, key=lambda c: (c.active_tasks, c.cost_hint, c.agent_id))
        eligible = [
            c for c in ordered
            if c.allowed and c.healthy and c.model_available
            and all(_has(c.capabilities, need) for need in capabilities)
        ]
        if not eligible:
            uncovered.append(role)
            reasons.append(f"role {role}: no eligible agent")
            continue
        if len(members) >= limit:
            uncovered.append(role)
            reasons.append(f"role {role}: team size limit {limit}")
            continue
        winner = eligible[0]
        used.add(winner.agent_id)
        members.append(
            TeamMemberSpec(
                agent_id=winner.agent_id,
                role=role,
                responsibilities=[f"cover {role}: {', '.join(capabilities)}"],
                task_scope=[],
            )
        )
        reasons.append(f"role {role}: selected {winner.agent_id} (load={winner.active_tasks})")
    return FormedTeam(members=members, uncovered_roles=uncovered, reasons=reasons)


def _has(offered: List[str], need: str) -> bool:
    return need.strip().lower() in {c.strip().lower() for c in offered}


def split_budget(parent_total: float, shares: List[float]) -> List[float]:
    """Allocate parent budget across children. Children can never exceed the
    parent allocation: shares are normalized when they oversubscribe."""
    if not shares:
        return []
    total = sum(max(0.0, s) for s in shares)
    if total <= 0:
        equal = round(parent_total / len(shares), 6)
        return [equal] * len(shares)
    if total <= parent_total:
        return [round(s, 6) for s in shares]
    return [round(parent_total * s / total, 6) for s in shares]


def validate_dissolution(status: TeamStatus, pending_tasks: int) -> List[str]:
    errors: List[str] = []
    if status != TeamStatus.WINDING_DOWN:
        errors.append("team must be WINDING_DOWN before completion")
    if pending_tasks > 0:
        errors.append(f"{pending_tasks} tasks still pending; collect artifacts first")
    return errors
