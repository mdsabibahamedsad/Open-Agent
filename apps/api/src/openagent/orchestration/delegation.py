"""Delegation and handoff primitives with authorization-aware validation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from openagent.orchestration.security import sanitize_dict
from openagent.orchestration.types import ContextScope, RiskLevel


@dataclass
class DelegationRequest:
    parent_agent_id: str
    target_agent_id: str
    task_id: str
    depth: int
    max_depth: int
    parent_risk: RiskLevel = RiskLevel.LOW
    child_risk: RiskLevel = RiskLevel.LOW
    organization_match: bool = True
    target_available: bool = True
    budget_ok: bool = True


@dataclass
class DelegationDecision:
    allowed: bool
    reasons: List[str]


def evaluate_delegation(req: DelegationRequest) -> DelegationDecision:
    reasons: List[str] = []
    if not req.organization_match:
        return DelegationDecision(False, ["cross-organization delegation denied"])
    if req.parent_agent_id == req.target_agent_id:
        return DelegationDecision(False, ["self-delegation denied"])
    if not req.target_available:
        return DelegationDecision(False, ["target agent unavailable"])
    if not req.budget_ok:
        return DelegationDecision(False, ["insufficient budget for delegation"])
    if req.depth + 1 > req.max_depth:
        return DelegationDecision(
            False, [f"max delegation depth {req.max_depth} would be exceeded"]
        )
    from openagent.orchestration.types import RISK_ORDER

    if RISK_ORDER[req.child_risk] < RISK_ORDER[req.parent_risk]:
        return DelegationDecision(False, ["child risk must not be lower than parent risk"])
    reasons.append("delegation authorized")
    return DelegationDecision(True, reasons)


@dataclass
class HandoffPackage:
    task_id: str
    objective: str
    completed_work: Dict[str, Any]
    artifacts: List[Dict[str, Any]]
    relevant_context: Dict[str, Any]
    constraints: List[str]
    warnings: List[str]
    expected_next_action: str


AUTHORIZED_SCOPES = {
    ContextScope.TASK,
    ContextScope.TEAM,
    ContextScope.ORCHESTRATION,
    ContextScope.PUBLIC_RESULT,
}


def build_handoff(
    *,
    task_id: str,
    objective: str,
    completed_work: Dict[str, Any],
    artifacts: Optional[List[Dict[str, Any]]] = None,
    relevant_context: Optional[Dict[str, Any]] = None,
    constraints: Optional[List[str]] = None,
    warnings: Optional[List[str]] = None,
    expected_next_action: str = "",
    allowed_scopes: frozenset[ContextScope] = frozenset(AUTHORIZED_SCOPES),
) -> HandoffPackage:
    """Build a structured handoff. PRIVATE context is never transferred."""
    context = sanitize_dict(dict(relevant_context or {}))
    if ContextScope.PRIVATE in allowed_scopes:
        raise ValueError("PRIVATE scope must never be transferred in a handoff")
    # Only explicitly authorized scopes flow; private keys are already redacted.
    return HandoffPackage(
        task_id=task_id,
        objective=objective,
        completed_work=sanitize_dict(dict(completed_work or {})),
        artifacts=list(artifacts or []),
        relevant_context=context,
        constraints=list(constraints or []),
        warnings=list(warnings or []),
        expected_next_action=expected_next_action,
    )
