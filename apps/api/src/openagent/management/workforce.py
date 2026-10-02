"""Availability, capacity, deadlines, organization scope."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from openagent.management.types import AgentScope, AvailabilityState


@dataclass
class AgentCapacity:
    max_concurrent_tasks: int = 5
    max_concurrent_runs: int = 2
    max_daily_cost: float = 50.0
    max_token_budget: int = 500_000
    # Current load (tracked by service).
    active_tasks: int = 0
    active_runs: int = 0
    daily_cost_used: float = 0.0
    tokens_used: int = 0


@dataclass
class ManagerCapacity:
    max_direct_reports: int = 10
    max_active_tasks: int = 30
    max_delegations: int = 100
    max_replans: int = 3
    max_team_size: int = 12
    active_tasks: int = 0
    direct_reports: int = 0


def availability_from_load(capacity: AgentCapacity) -> AvailabilityState:
    if capacity.active_tasks >= capacity.max_concurrent_tasks:
        return AvailabilityState.OVERLOADED
    if capacity.active_tasks > 0:
        return AvailabilityState.BUSY
    return AvailabilityState.AVAILABLE


def can_accept(capacity: AgentCapacity, *, estimated_cost: float = 0.0,
               estimated_tokens: int = 0) -> tuple[bool, str]:
    if capacity.active_tasks >= capacity.max_concurrent_tasks:
        return False, "max concurrent tasks reached"
    if capacity.daily_cost_used + estimated_cost > capacity.max_daily_cost:
        return False, "daily cost budget exceeded"
    if capacity.tokens_used + estimated_tokens > capacity.max_token_budget:
        return False, "token budget exceeded"
    return True, "capacity available"


def check_manager_capacity(capacity: ManagerCapacity) -> List[str]:
    violations: List[str] = []
    if capacity.direct_reports > capacity.max_direct_reports:
        violations.append("too many direct reports")
    if capacity.active_tasks > capacity.max_active_tasks:
        violations.append("too many active tasks")
    return violations


def allocate_deadlines(parent_deadline: datetime, weights: List[float]) -> List[datetime]:
    """Children share the parent window; none may extend the root deadline.
    Weights split the *remaining* time proportionally from now."""
    now = datetime.now(timezone.utc)
    if parent_deadline.tzinfo is None:
        parent_deadline = parent_deadline.replace(tzinfo=timezone.utc)
    remaining = max(0.0, (parent_deadline - now).total_seconds())
    total = sum(max(0.0, w) for w in weights) or 1.0
    deadlines: List[datetime] = []
    cursor = now
    for i, weight in enumerate(weights):
        share = remaining * max(0.0, weight) / total
        end = cursor + timedelta(seconds=share)
        if i == len(weights) - 1:
            end = parent_deadline
        deadlines.append(end)
        cursor = end
    return deadlines


@dataclass
class Department:
    id: str
    name: str
    organization_id: str
    metadata: Dict[str, str] = field(default_factory=dict)


BUILTIN_DEPARTMENTS = [
    "engineering", "marketing", "research", "operations",
    "sales", "finance", "support", "security",
]


@dataclass
class AgentPlacement:
    agent_id: str
    scope: AgentScope = AgentScope.ORGANIZATION
    department_id: Optional[str] = None
    team_id: Optional[str] = None


def placement_covers_scope(placement: AgentPlacement, scope: AgentScope) -> bool:
    order = {
        AgentScope.PLATFORM: 4,
        AgentScope.ORGANIZATION: 3,
        AgentScope.DEPARTMENT: 2,
        AgentScope.TEAM: 1,
        AgentScope.PRIVATE: 0,
    }
    return order.get(placement.scope, 0) >= order.get(scope, 0)
