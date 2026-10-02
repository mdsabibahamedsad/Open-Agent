"""Escalation system: policies, chains, severity, human hook.

Full human approval ships in MP19; this module exposes the integration
interface (ApprovalRequiredError / ApprovalRequestHook / ApprovalPolicy).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from openagent.management.types import (
    EscalationPolicyConfig,
    EscalationSeverity,
    FailureEscalationRule,
)

ESCALATION_TRIGGERS = frozenset(
    {
        "blocked",
        "permission_denied",
        "budget_exceeded",
        "deadline_risk",
        "repeated_failure",
        "high_risk_action",
        "ambiguous_requirement",
        "conflicting_outputs",
        "missing_capability",
    }
)


@dataclass
class EscalationRequest:
    source_agent_id: Optional[str]
    task_id: Optional[str]
    reason: str
    trigger: str  # one of ESCALATION_TRIGGERS
    severity: EscalationSeverity = EscalationSeverity.WARNING
    recommended_action: str = ""
    context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EscalationRouting:
    target: str  # manager | senior_manager | ceo | human
    level: int  # 0-based depth in chain
    severity: EscalationSeverity
    human_required: bool = False


def validate_escalation(request: EscalationRequest) -> List[str]:
    errors: List[str] = []
    if request.trigger not in ESCALATION_TRIGGERS:
        errors.append(f"unknown trigger: {request.trigger}")
    if not request.reason.strip():
        errors.append("reason must not be empty")
    return errors


def route_escalation(
    request: EscalationRequest,
    policy: EscalationPolicyConfig,
    *,
    current_level: int = 0,
    chain: Optional[List[str]] = None,
) -> EscalationRouting:
    """Resolve the next hop in the escalation chain."""
    chain = chain or ["manager", "senior_manager", "ceo", "human"]
    level = min(current_level, len(chain) - 1)
    target = chain[level]
    if policy.target in chain:
        target = policy.target
        level = chain.index(policy.target)
    if level >= policy.max_depth:
        target = "human"
        level = len(chain) - 1
    human_required = target == "human" or (
        request.severity == EscalationSeverity.CRITICAL and policy.human_approval_hook
    )
    return EscalationRouting(
        target=target, level=level, severity=request.severity, human_required=human_required
    )


def apply_failure_matrix(
    failures: int,
    matrix: List[FailureEscalationRule],
    *,
    policy_violation: bool = False,
) -> str:
    """Configurable failure → action mapping. Critical policy violations
    escalate immediately."""
    if policy_violation:
        return "immediate_escalate"
    action = "retry"
    for rule in sorted(matrix, key=lambda r: r.failures):
        if failures >= rule.failures:
            action = rule.action
    return action


# ---------------------------------------------------------------------------
# MP19 boundary: human approval hook
# ---------------------------------------------------------------------------


class ApprovalRequiredError(Exception):
    """Raised when execution needs human approval to proceed."""

    def __init__(self, message: str, *, approval_id: Optional[str] = None,
                 severity: EscalationSeverity = EscalationSeverity.HIGH):
        super().__init__(message)
        self.approval_id = approval_id
        self.severity = severity


@dataclass
class ApprovalPolicy:
    triggers: List[str] = field(default_factory=list)
    timeout_seconds: int = 3600
    auto_expire_action: str = "escalate"  # escalate | reject | pause
    required_role: str = "admin"


class ApprovalRequestHook(ABC):
    """MP19 boundary: implemented by the Human Approval System."""

    @abstractmethod
    async def request_approval(
        self, *, organization_id: str, title: str, payload: Dict[str, Any],
        policy: ApprovalPolicy,
    ) -> str:
        """Create an approval request; returns approval id."""
        ...

    @abstractmethod
    async def check_approval(self, *, approval_id: str) -> str:
        """Return approval status: pending | approved | rejected | expired."""
        ...
