"""Approval & guardrail shared types (MP19).

Pure, dependency-light. DB enums live in db/models/approval.py and mirror these.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional
from uuid import UUID


class RiskLevel(str, enum.Enum):
    NONE = "NONE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

    def score_floor(self) -> int:
        return {"NONE": 0, "LOW": 1, "MEDIUM": 40, "HIGH": 70, "CRITICAL": 90}[self.value]

    @classmethod
    def from_score(cls, score: int) -> "RiskLevel":
        if score >= 90:
            return cls.CRITICAL
        if score >= 70:
            return cls.HIGH
        if score >= 40:
            return cls.MEDIUM
        if score >= 1:
            return cls.LOW
        return cls.NONE


class PolicyDecision(str, enum.Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"
    REQUIRE_MULTI_APPROVAL = "REQUIRE_MULTI_APPROVAL"
    REQUIRE_ESCALATION = "REQUIRE_ESCALATION"


class ApprovalState(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    EXECUTING = "EXECUTING"
    EXECUTED = "EXECUTED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    INVALIDATED = "INVALIDATED"


class ApprovalKind(str, enum.Enum):
    SINGLE = "SINGLE"
    MULTI = "MULTI"
    SEQUENTIAL = "SEQUENTIAL"
    MANAGER = "MANAGER"
    ORGANIZATION = "ORGANIZATION"
    PLATFORM = "PLATFORM"
    EMERGENCY = "EMERGENCY"


class HumanBlockReason(str, enum.Enum):
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    CAPTCHA = "CAPTCHA"
    MISSING_INFORMATION = "MISSING_INFORMATION"
    AMBIGUOUS_ACTION = "AMBIGUOUS_ACTION"
    SECURITY_REVIEW = "SECURITY_REVIEW"
    MANUAL_TAKEOVER = "MANUAL_TAKEOVER"


# Strict state machine. Any transition not listed is rejected server-side.
ALLOWED_TRANSITIONS: dict[ApprovalState, frozenset[ApprovalState]] = {
    ApprovalState.PENDING: frozenset(
        {ApprovalState.APPROVED, ApprovalState.REJECTED, ApprovalState.EXPIRED,
         ApprovalState.CANCELLED, ApprovalState.INVALIDATED}
    ),
    ApprovalState.APPROVED: frozenset(
        {ApprovalState.EXECUTING, ApprovalState.CANCELLED, ApprovalState.EXPIRED,
         ApprovalState.INVALIDATED}
    ),
    ApprovalState.EXECUTING: frozenset(
        {ApprovalState.EXECUTED, ApprovalState.EXECUTION_FAILED, ApprovalState.INVALIDATED}
    ),
    ApprovalState.REJECTED: frozenset(),
    ApprovalState.EXPIRED: frozenset(),
    ApprovalState.CANCELLED: frozenset(),
    ApprovalState.EXECUTED: frozenset(),
    ApprovalState.EXECUTION_FAILED: frozenset(),
    ApprovalState.INVALIDATED: frozenset(),
}


def can_transition(frm: ApprovalState, to: ApprovalState) -> bool:
    return to in ALLOWED_TRANSITIONS.get(frm, frozenset())


@dataclass
class RiskAssessment:
    risk_level: RiskLevel
    risk_score: int
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"risk_level": self.risk_level.value, "risk_score": self.risk_score,
                "reasons": list(self.reasons)}


@dataclass
class PolicyEvaluation:
    decision: PolicyDecision
    risk_level: RiskLevel
    approval_kind: ApprovalKind = ApprovalKind.SINGLE
    required_role: Optional[str] = None
    required_approvals: int = 1
    reasons: list[str] = field(default_factory=list)
    policy_version: str = "platform-v1"

    def to_dict(self) -> dict[str, Any]:
        return {"decision": self.decision.value, "risk_level": self.risk_level.value,
                "approval_type": self.approval_kind.value,
                "required_role": self.required_role,
                "required_approvals": self.required_approvals,
                "reasons": list(self.reasons), "policy_version": self.policy_version}


@dataclass
class ActionContext:
    """Normalized input for policy + risk evaluation. Never carries secrets."""

    action_type: str
    action_category: str = "WRITE"
    target_type: str = ""
    target_id: str = ""
    target_reference: str = ""
    environment: str = "development"  # development | staging | production
    params_summary: dict[str, Any] = field(default_factory=dict)
    data_sensitivity: str = "internal"  # public | internal | confidential | restricted
    external_side_effect: bool = False
    financial_impact: bool = False
    destructive: bool = False
    credential_usage: bool = False
    network_access: bool = False
    privilege_level: str = "standard"  # standard | elevated | admin | platform
    tenant_scope: str = "own"  # own | team | organization | cross_tenant | platform
    reversibility: str = "reversible"  # reversible | reversible_with_effort | irreversible
    affected_resources: int = 1
    agent_trust: str = "ORGANIZATION"
    tool_trust: str = "ORGANIZATION"
    mcp_trust: str = "ORGANIZATION"
    sandbox_profile: str = "ISOLATED"
    tool_name: str = ""
    mcp_server: str = ""
    agent_id: str = ""
    organization_id: str = ""
    untrusted_origin: bool = False  # unknown tool / unverified caller: deny-by-default


@dataclass
class GuardResult:
    decision: PolicyDecision
    risk: RiskAssessment
    evaluation: PolicyEvaluation
    approval_required: bool
    approval_id: Optional[UUID] = None

    def agent_payload(self) -> dict[str, Any]:
        """Safe structured payload for model context (no policies, no secrets)."""
        if not self.approval_required:
            return {"status": "ALLOWED"}
        return {"status": "WAITING_FOR_APPROVAL",
                "approval_id": str(self.approval_id) if self.approval_id else None,
                "message": "Human approval required",
                "risk_level": self.risk.risk_level.value}


@dataclass
class ApprovalEnvelope:
    """Narrowly-scoped authorization envelope bound to a single approval."""

    action_type: str
    action_category: str
    target_type: str
    target_id: str
    params_hash: str
    resource_scope: str = "single"
    environment: str = "development"
    max_uses: int = 1
    expires_at: Optional[datetime] = None
