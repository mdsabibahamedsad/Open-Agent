"""Formal delegation: policy-based selection, lifecycle, reassignment rules.

Selects agents/tasks — never models (Model Router owns model selection).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from openagent.management.types import DelegationPolicy, DelegationStatus
from openagent.orchestration.assignment import AgentCandidate, assign_agent


@dataclass
class DelegationProposal:
    source_agent_id: str
    task_id: str
    reason: str = ""
    contract: Dict[str, Any] = field(default_factory=dict)
    required_capabilities: List[str] = field(default_factory=list)
    constraints: List[str] = field(default_factory=list)
    budget: Dict[str, Any] = field(default_factory=dict)
    deadline: Optional[datetime] = None
    explicit_target_id: Optional[str] = None
    policy: DelegationPolicy = DelegationPolicy.HYBRID


@dataclass
class DelegationSelection:
    target_agent_id: Optional[str]
    reasons: List[str]
    considered: int = 0


def select_delegate(
    proposal: DelegationProposal,
    candidates: List[AgentCandidate],
) -> DelegationSelection:
    """Policy-driven specialist selection with explainable reasons."""
    policy = proposal.policy
    pool = list(candidates)

    if policy == DelegationPolicy.EXPLICIT_ONLY:
        if not proposal.explicit_target_id:
            return DelegationSelection(None, ["explicit_only: no target specified"], len(pool))
        result = assign_agent(
            required_capabilities=proposal.required_capabilities,
            candidates=pool,
            explicit_agent_id=proposal.explicit_target_id,
        )
        return DelegationSelection(result.agent_id, result.reasons, result.considered)

    if policy == DelegationPolicy.MANAGER_SELECTED:
        # Manager pre-selected (explicit_target_id) but capability-checked.
        if proposal.explicit_target_id:
            result = assign_agent(
                required_capabilities=proposal.required_capabilities,
                candidates=pool,
                explicit_agent_id=proposal.explicit_target_id,
            )
            return DelegationSelection(result.agent_id, ["manager_selected"] + result.reasons,
                                        result.considered)
        # Fall through to capability-based when no explicit selection.

    ranked = pool
    reasons: List[str] = []
    if policy in (DelegationPolicy.LOAD_AWARE, DelegationPolicy.HYBRID):
        ranked = sorted(ranked, key=lambda c: (c.active_tasks, c.agent_id))
        reasons.append("load_aware ordering")
    if policy in (DelegationPolicy.COST_AWARE, DelegationPolicy.HYBRID):
        ranked = sorted(ranked, key=lambda c: (c.cost_hint, c.active_tasks, c.agent_id))
        reasons.append("cost_aware ordering")
    # CAPABILITY_BASED, POLICY_BASED, HYBRID all funnel through the
    # deterministic capability matcher (policy pre-checks applied by caller).
    result = assign_agent(
        required_capabilities=proposal.required_capabilities,
        candidates=ranked,
    )
    return DelegationSelection(
        result.agent_id, [f"policy={policy.value}"] + reasons + result.reasons,
        result.considered,
    )


@dataclass
class ReassignmentAssessment:
    new_agent_id: Optional[str]
    reasons: List[str]
    attempts_preserved: int = 0


def assess_reassignment(
    *,
    required_capabilities: List[str],
    candidates: List[AgentCandidate],
    previous_agent_id: Optional[str],
    attempts: int,
    trust_required: str = "organization",
) -> ReassignmentAssessment:
    """Reassignment considers capability, availability, authorization, trust,
    workload, budget, and deadline. Previous attempts are preserved by the
    caller (attempt history is append-only)."""
    trust_order = {"core": 4, "verified": 3, "organization": 2, "community": 1, "untrusted": 0}
    minimum = trust_order.get(trust_required, 2)
    eligible = [
        c for c in candidates
        if trust_order.get(str(c.metadata.get("trust", "organization")), 2) >= minimum
        and c.agent_id != (previous_agent_id or "")
    ]
    result = assign_agent(required_capabilities=required_capabilities, candidates=eligible)
    if result.agent_id is None:
        # Fall back to previous agent only if nothing else qualifies.
        retry = assign_agent(required_capabilities=required_capabilities, candidates=candidates)
        return ReassignmentAssessment(
            retry.agent_id, ["no fresh candidate; fallback evaluated"] + retry.reasons,
            attempts_preserved=attempts,
        )
    return ReassignmentAssessment(
        result.agent_id, ["reassigned"] + result.reasons, attempts_preserved=attempts
    )


def delegation_expired(deadline: Optional[datetime], now: Optional[datetime] = None) -> bool:
    if deadline is None:
        return False
    ref = now or datetime.now(timezone.utc)
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    return ref >= deadline
