"""Management-layer domain types for Master Prompt 14.

Extends orchestration primitives; no I/O here.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set


# ---------------------------------------------------------------------------
# Authority
# ---------------------------------------------------------------------------


class ManagerAuthority(str, enum.Enum):
    CAN_DELEGATE = "can_delegate"
    CAN_REASSIGN = "can_reassign"
    CAN_REVIEW = "can_review"
    CAN_REQUEST_REVISION = "can_request_revision"
    CAN_ESCALATE = "can_escalate"
    CAN_PAUSE_CHILD = "can_pause_child"
    CAN_CANCEL_CHILD = "can_cancel_child"
    CAN_CREATE_TEAM = "can_create_team"
    CAN_SELECT_SPECIALIST = "can_select_specialist"


class AgentScope(str, enum.Enum):
    PLATFORM = "platform"
    ORGANIZATION = "organization"
    DEPARTMENT = "department"
    TEAM = "team"
    PRIVATE = "private"


# ---------------------------------------------------------------------------
# Delegation
# ---------------------------------------------------------------------------


class DelegationPolicy(str, enum.Enum):
    EXPLICIT_ONLY = "explicit_only"
    MANAGER_SELECTED = "manager_selected"
    CAPABILITY_BASED = "capability_based"
    LOAD_AWARE = "load_aware"
    COST_AWARE = "cost_aware"
    POLICY_BASED = "policy_based"
    HYBRID = "hybrid"


class DelegationStatus(str, enum.Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


VALID_DELEGATION_TRANSITIONS: Dict[DelegationStatus, Set[DelegationStatus]] = {
    DelegationStatus.PENDING: {
        DelegationStatus.ACCEPTED,
        DelegationStatus.REJECTED,
        DelegationStatus.EXPIRED,
        DelegationStatus.CANCELLED,
    },
    DelegationStatus.ACCEPTED: {
        DelegationStatus.COMPLETED,
        DelegationStatus.CANCELLED,
    },
    DelegationStatus.REJECTED: set(),
    DelegationStatus.EXPIRED: set(),
    DelegationStatus.CANCELLED: set(),
    DelegationStatus.COMPLETED: set(),
}


def can_transition_delegation(frm: DelegationStatus, to: DelegationStatus) -> bool:
    return to in VALID_DELEGATION_TRANSITIONS.get(frm, set())


# ---------------------------------------------------------------------------
# Handoff
# ---------------------------------------------------------------------------


class HandoffMode(str, enum.Enum):
    FULL_HANDOFF = "full_handoff"
    PARTIAL_HANDOFF = "partial_handoff"
    REVIEW_HANDOFF = "review_handoff"
    ESCALATION_HANDOFF = "escalation_handoff"
    SPECIALIST_HANDOFF = "specialist_handoff"
    FAILURE_HANDOFF = "failure_handoff"


class HandoffStatus(str, enum.Enum):
    PREPARING = "preparing"
    PENDING_ACCEPTANCE = "pending_acceptance"
    ACCEPTED = "accepted"
    EXECUTING = "executing"
    COMPLETED = "completed"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


VALID_HANDOFF_TRANSITIONS: Dict[HandoffStatus, Set[HandoffStatus]] = {
    HandoffStatus.PREPARING: {HandoffStatus.PENDING_ACCEPTANCE, HandoffStatus.CANCELLED},
    HandoffStatus.PENDING_ACCEPTANCE: {
        HandoffStatus.ACCEPTED,
        HandoffStatus.REJECTED,
        HandoffStatus.EXPIRED,
        HandoffStatus.CANCELLED,
    },
    HandoffStatus.ACCEPTED: {HandoffStatus.EXECUTING, HandoffStatus.CANCELLED},
    HandoffStatus.EXECUTING: {HandoffStatus.COMPLETED, HandoffStatus.CANCELLED},
    HandoffStatus.COMPLETED: set(),
    HandoffStatus.REJECTED: set(),
    HandoffStatus.EXPIRED: set(),
    HandoffStatus.CANCELLED: set(),
}


def can_transition_handoff(frm: HandoffStatus, to: HandoffStatus) -> bool:
    return to in VALID_HANDOFF_TRANSITIONS.get(frm, set())


class ContextTransferRule(str, enum.Enum):
    PUBLIC = "public"
    TASK_ONLY = "task_only"
    TEAM_ONLY = "team_only"
    AUTHORIZED_SHARED = "authorized_shared"
    PRIVATE = "private"
    REDACTED = "redacted"


# ---------------------------------------------------------------------------
# Review
# ---------------------------------------------------------------------------


class ReviewStatus(str, enum.Enum):
    APPROVED = "approved"
    REVISION_REQUIRED = "revision_required"
    REJECTED = "rejected"
    ESCALATE = "escalate"


class QualityGateResult(str, enum.Enum):
    PASS = "pass"
    REVISION = "revision"
    FAIL = "fail"


# ---------------------------------------------------------------------------
# Escalation
# ---------------------------------------------------------------------------


class EscalationSeverity(str, enum.Enum):
    INFO = "info"
    WARNING = "warning"
    HIGH = "high"
    CRITICAL = "critical"


class EscalationStatus(str, enum.Enum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    ESCALATED = "escalated"  # moved up the chain
    CLOSED = "closed"


VALID_ESCALATION_TRANSITIONS: Dict[EscalationStatus, Set[EscalationStatus]] = {
    EscalationStatus.OPEN: {
        EscalationStatus.ACKNOWLEDGED,
        EscalationStatus.IN_PROGRESS,
        EscalationStatus.ESCALATED,
        EscalationStatus.CLOSED,
    },
    EscalationStatus.ACKNOWLEDGED: {
        EscalationStatus.IN_PROGRESS,
        EscalationStatus.ESCALATED,
        EscalationStatus.RESOLVED,
        EscalationStatus.CLOSED,
    },
    EscalationStatus.IN_PROGRESS: {
        EscalationStatus.RESOLVED,
        EscalationStatus.ESCALATED,
        EscalationStatus.CLOSED,
    },
    EscalationStatus.ESCALATED: {
        EscalationStatus.ACKNOWLEDGED,
        EscalationStatus.IN_PROGRESS,
        EscalationStatus.RESOLVED,
        EscalationStatus.CLOSED,
    },
    EscalationStatus.RESOLVED: {EscalationStatus.CLOSED},
    EscalationStatus.CLOSED: set(),
}


def can_transition_escalation(frm: EscalationStatus, to: EscalationStatus) -> bool:
    return to in VALID_ESCALATION_TRANSITIONS.get(frm, set())


# ---------------------------------------------------------------------------
# Teams
# ---------------------------------------------------------------------------


class TeamStatus(str, enum.Enum):
    CREATED = "created"
    FORMING = "forming"
    ACTIVE = "active"
    WINDING_DOWN = "winding_down"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class DynamicTeamType(str, enum.Enum):
    PERSISTENT = "persistent"
    TEMPORARY = "temporary"
    ORCHESTRATION_SCOPED = "orchestration_scoped"
    TASK_SCOPED = "task_scoped"


class TeamMembershipStatus(str, enum.Enum):
    INVITED = "invited"
    ACTIVE = "active"
    REMOVED = "removed"


VALID_TEAM_TRANSITIONS: Dict[TeamStatus, Set[TeamStatus]] = {
    TeamStatus.CREATED: {TeamStatus.FORMING, TeamStatus.CANCELLED},
    TeamStatus.FORMING: {TeamStatus.ACTIVE, TeamStatus.CANCELLED},
    TeamStatus.ACTIVE: {TeamStatus.WINDING_DOWN, TeamStatus.CANCELLED},
    TeamStatus.WINDING_DOWN: {TeamStatus.COMPLETED, TeamStatus.CANCELLED},
    TeamStatus.COMPLETED: set(),
    TeamStatus.CANCELLED: set(),
}


def can_transition_team(frm: TeamStatus, to: TeamStatus) -> bool:
    return to in VALID_TEAM_TRANSITIONS.get(frm, set())


# ---------------------------------------------------------------------------
# Manager loop
# ---------------------------------------------------------------------------


class ManagerLoopState(str, enum.Enum):
    OBSERVE = "observe"
    UNDERSTAND = "understand"
    PLAN = "plan"
    DELEGATE = "delegate"
    MONITOR = "monitor"
    REVIEW = "review"
    CORRECT = "correct"
    COMPLETE = "complete"


MANAGER_LOOP_ORDER: List[ManagerLoopState] = [
    ManagerLoopState.OBSERVE,
    ManagerLoopState.UNDERSTAND,
    ManagerLoopState.PLAN,
    ManagerLoopState.DELEGATE,
    ManagerLoopState.MONITOR,
    ManagerLoopState.REVIEW,
    ManagerLoopState.CORRECT,
    ManagerLoopState.COMPLETE,
]


# ---------------------------------------------------------------------------
# Availability / progress / collaboration
# ---------------------------------------------------------------------------


class AvailabilityState(str, enum.Enum):
    AVAILABLE = "available"
    BUSY = "busy"
    OVERLOADED = "overloaded"
    OFFLINE = "offline"
    DISABLED = "disabled"
    UNHEALTHY = "unhealthy"


class BlockedReason(str, enum.Enum):
    MISSING_INPUT = "missing_input"
    MISSING_PERMISSION = "missing_permission"
    MISSING_TOOL = "missing_tool"
    DEPENDENCY_FAILURE = "dependency_failure"
    RESOURCE_UNAVAILABLE = "resource_unavailable"
    AMBIGUOUS_REQUIREMENT = "ambiguous_requirement"
    EXTERNAL_FAILURE = "external_failure"


class CollaborationAction(str, enum.Enum):
    REQUEST_INFORMATION = "request_information"
    SHARE_RESULT = "share_result"
    REQUEST_REVIEW = "request_review"
    REQUEST_ARTIFACT = "request_artifact"
    REQUEST_ANALYSIS = "request_analysis"


class CollaborationStatus(str, enum.Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class CommitmentStatus(str, enum.Enum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    IN_PROGRESS = "in_progress"
    FULFILLED = "fulfilled"
    BREACHED = "breached"
    RELEASED = "released"


class ChannelType(str, enum.Enum):
    DIRECT = "direct"
    TEAM = "team"
    MANAGER = "manager"
    ESCALATION = "escalation"
    BROADCAST = "broadcast"


# ---------------------------------------------------------------------------
# Shared dataclasses
# ---------------------------------------------------------------------------


@dataclass
class AcceptanceCriterion:
    description: str
    verification: str = ""  # how the manager verifies it
    satisfied: Optional[bool] = None


@dataclass
class ManagerLoopBudget:
    max_decisions: int = 50
    max_replans: int = 3
    max_delegations: int = 100
    max_revisions: int = 3
    max_time_seconds: int = 3600
    max_cost: float = 10.0


@dataclass
class FailureEscalationRule:
    failures: int  # threshold
    action: str  # retry | reassign | escalate | immediate_escalate
    severity: EscalationSeverity = EscalationSeverity.WARNING


@dataclass
class EscalationPolicyConfig:
    triggers: List[str] = field(default_factory=list)
    target: str = "manager"  # manager | senior_manager | ceo | human
    timeout_seconds: int = 600
    severity: EscalationSeverity = EscalationSeverity.WARNING
    max_depth: int = 4
    human_approval_hook: bool = True


DEFAULT_FAILURE_MATRIX: List[FailureEscalationRule] = [
    FailureEscalationRule(failures=1, action="retry", severity=EscalationSeverity.INFO),
    FailureEscalationRule(failures=2, action="reassign", severity=EscalationSeverity.WARNING),
    FailureEscalationRule(failures=3, action="escalate", severity=EscalationSeverity.HIGH),
]


@dataclass
class DecisionRecordData:
    decision_type: str
    actor_agent_id: Optional[str]
    task_id: Optional[str]
    selected_action: str
    alternatives: List[str] = field(default_factory=list)
    policy_basis: str = ""
    rationale: str = ""  # concise operational rationale, never chain-of-thought


@dataclass
class PlanVersionData:
    version: int
    reason: str
    created_by: Optional[str]
    changes: List[str] = field(default_factory=list)
    parent_version: Optional[int] = None


@dataclass
class ProgressReport:
    progress: float  # informational only, 0..1
    status: str
    current_step: str = ""
    blocked: bool = False
    blocked_reason: Optional[BlockedReason] = None

    def clamped(self) -> "ProgressReport":
        self.progress = max(0.0, min(1.0, float(self.progress or 0.0)))
        return self


@dataclass
class ContextManifestData:
    included_items: List[str] = field(default_factory=list)
    excluded_items: List[str] = field(default_factory=list)
    redacted_items: List[str] = field(default_factory=list)
    source: str = ""
    target: str = ""
    policy: str = ContextTransferRule.TASK_ONLY.value


MANAGEMENT_EVENT_NAMES = [
    "MANAGER_PROFILE_CREATED",
    "CONTRACT_CREATED",
    "DELEGATION_CREATED",
    "DELEGATION_ACCEPTED",
    "DELEGATION_REJECTED",
    "DELEGATION_EXPIRED",
    "HANDOFF_PREPARED",
    "HANDOFF_ACCEPTED",
    "HANDOFF_REJECTED",
    "HANDOFF_COMPLETED",
    "REVIEW_SUBMITTED",
    "REVISION_REQUESTED",
    "ESCALATION_OPENED",
    "ESCALATION_ACKNOWLEDGED",
    "ESCALATION_RESOLVED",
    "ESCALATION_CHAINED",
    "TEAM_CREATED",
    "TEAM_ACTIVE",
    "TEAM_WINDING_DOWN",
    "TEAM_COMPLETED",
    "TEAM_DISSOLVED",
    "PLAN_VERSION_CREATED",
    "MANAGER_DECISION_RECORDED",
    "COMMITMENT_ACCEPTED",
    "WORKER_REPLACED",
    "MANAGER_RECOVERED",
]

MANAGEMENT_METRIC_NAMES = [
    "manager_decisions_total",
    "delegations_total",
    "delegations_failed",
    "handoffs_total",
    "handoffs_failed",
    "escalations_total",
    "reassignments_total",
    "revision_cycles",
    "team_creation_total",
    "agent_replacements",
]

# Message-rate defaults (communication storm protection).
DEFAULT_MAX_MESSAGES_PER_TASK = 100
DEFAULT_MAX_MESSAGES_PER_AGENT_PER_RUN = 500
DEFAULT_MAX_COLLABORATION_REQUESTS = 50
DEFAULT_MAX_HANDOFFS_PER_RUN = 100
DEFAULT_MAX_DELEGATIONS_PER_RUN = 200

# Allow-listed collaboration payload keys (agents may negotiate these only).
NEGOTIABLE_FIELDS = frozenset(
    {"availability", "accept", "estimated_effort", "capabilities", "expected_completion", "deadline"}
)

# Collaboration payload keys that must never be negotiated.
NON_NEGOTIABLE_FIELDS = frozenset({"permissions", "role", "scope", "budget_override", "credentials"})
