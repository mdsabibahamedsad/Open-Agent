"""Multi-agent orchestration domain types.

Central enums, constants, and transition tables. No I/O here.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set


# ---------------------------------------------------------------------------
# Limits (overridable per-organization via orchestration.config)
# ---------------------------------------------------------------------------

DEFAULT_MAX_TASKS_PER_RUN = 200
DEFAULT_MAX_AGENTS_PER_RUN = 50
DEFAULT_MAX_DELEGATION_DEPTH = 5
DEFAULT_MAX_PARALLEL_TASKS = 10
DEFAULT_MAX_GRAPH_DEPTH = 12
DEFAULT_TASK_TIMEOUT_SECONDS = 600
DEFAULT_RUN_TIMEOUT_SECONDS = 3600
DEFAULT_MAX_MESSAGE_BYTES = 256 * 1024
DEFAULT_MAX_ARTIFACT_BYTES = 50 * 1024 * 1024
DEFAULT_MAX_OUTPUT_BYTES = 256 * 1024

# Sensitive-key patterns stripped from payloads / context passed between agents.
SECRET_KEY_HINTS = (
    "api_key",
    "apikey",
    "secret",
    "password",
    "passwd",
    "token",
    "credential",
    "private_key",
    "client_secret",
    "access_token",
    "refresh_token",
    "authorization",
    "cookie",
    "session",
)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class OrchestrationStatus(str, enum.Enum):
    CREATED = "created"
    PLANNING = "planning"
    READY = "ready"
    RUNNING = "running"
    WAITING = "waiting"
    PAUSED = "paused"
    SUCCEEDED = "succeeded"
    PARTIALLY_SUCCEEDED = "partially_succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class OrchTaskStatus(str, enum.Enum):
    CREATED = "created"
    READY = "ready"
    ASSIGNED = "assigned"
    RUNNING = "running"
    WAITING = "waiting"
    PAUSED = "paused"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class OrchAgentStatus(str, enum.Enum):
    CREATED = "created"
    READY = "ready"
    STARTING = "starting"
    RUNNING = "running"
    WAITING = "waiting"
    PAUSED = "paused"
    HANDOFF = "handoff"
    COMPLETING = "completing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    TERMINATED = "terminated"


class RelationshipType(str, enum.Enum):
    MANAGES = "manages"
    REPORTS_TO = "reports_to"
    COLLABORATES_WITH = "collaborates_with"
    CAN_DELEGATE_TO = "can_delegate_to"
    CAN_REVIEW = "can_review"
    SPECIALIZES_IN = "specializes_in"


class AgentMessageType(str, enum.Enum):
    TASK_ASSIGNED = "task_assigned"
    TASK_ACCEPTED = "task_accepted"
    TASK_STARTED = "task_started"
    TASK_PROGRESS = "task_progress"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    DELEGATION_REQUEST = "delegation_request"
    DELEGATION_ACCEPTED = "delegation_accepted"
    HANDOFF_REQUEST = "handoff_request"
    HANDOFF_COMPLETED = "handoff_completed"
    RESULT_SUBMITTED = "result_submitted"
    ESCALATION = "escalation"
    STATUS_UPDATE = "status_update"


class DependencyPolicy(str, enum.Enum):
    ALL_SUCCESS = "all_success"
    ANY_SUCCESS = "any_success"
    ALLOW_PARTIAL = "allow_partial"
    IGNORE_FAILURE = "ignore_failure"


class RetryStrategy(str, enum.Enum):
    NONE = "none"
    FIXED = "fixed"
    EXPONENTIAL_BACKOFF = "exponential_backoff"
    REASSIGN = "reassign"
    REPLAN = "replan"


class RiskLevel(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ContextScope(str, enum.Enum):
    PRIVATE = "private"
    TASK = "task"
    TEAM = "team"
    ORCHESTRATION = "orchestration"
    PUBLIC_RESULT = "public_result"


class AggregationStrategy(str, enum.Enum):
    MERGE = "merge"
    SUMMARIZE = "summarize"
    SELECT = "select"
    VALIDATE = "validate"
    RECONCILE = "reconcile"


class AgentTrustLevel(str, enum.Enum):
    CORE = "core"
    VERIFIED = "verified"
    ORGANIZATION = "organization"
    COMMUNITY = "community"
    UNTRUSTED = "untrusted"


class TaskPriority(str, enum.Enum):
    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


RISK_ORDER: Dict[RiskLevel, int] = {
    RiskLevel.LOW: 0,
    RiskLevel.MEDIUM: 1,
    RiskLevel.HIGH: 2,
    RiskLevel.CRITICAL: 3,
}

PRIORITY_ORDER: Dict[TaskPriority, int] = {
    TaskPriority.CRITICAL: 0,
    TaskPriority.HIGH: 1,
    TaskPriority.NORMAL: 2,
    TaskPriority.LOW: 3,
}


# ---------------------------------------------------------------------------
# Transitions
# ---------------------------------------------------------------------------

VALID_RUN_TRANSITIONS: Dict[OrchestrationStatus, Set[OrchestrationStatus]] = {
    OrchestrationStatus.CREATED: {
        OrchestrationStatus.PLANNING,
        OrchestrationStatus.READY,
        OrchestrationStatus.CANCELLED,
    },
    OrchestrationStatus.PLANNING: {
        OrchestrationStatus.READY,
        OrchestrationStatus.FAILED,
        OrchestrationStatus.CANCELLED,
        OrchestrationStatus.TIMED_OUT,
    },
    OrchestrationStatus.READY: {
        OrchestrationStatus.RUNNING,
        OrchestrationStatus.CANCELLED,
        OrchestrationStatus.PAUSED,
    },
    OrchestrationStatus.RUNNING: {
        OrchestrationStatus.WAITING,
        OrchestrationStatus.PAUSED,
        OrchestrationStatus.SUCCEEDED,
        OrchestrationStatus.PARTIALLY_SUCCEEDED,
        OrchestrationStatus.FAILED,
        OrchestrationStatus.CANCELLED,
        OrchestrationStatus.TIMED_OUT,
    },
    OrchestrationStatus.WAITING: {
        OrchestrationStatus.RUNNING,
        OrchestrationStatus.PAUSED,
        OrchestrationStatus.CANCELLED,
        OrchestrationStatus.TIMED_OUT,
        OrchestrationStatus.FAILED,
    },
    OrchestrationStatus.PAUSED: {
        OrchestrationStatus.RUNNING,
        OrchestrationStatus.CANCELLED,
        OrchestrationStatus.TIMED_OUT,
    },
    OrchestrationStatus.SUCCEEDED: set(),
    OrchestrationStatus.PARTIALLY_SUCCEEDED: set(),
    OrchestrationStatus.FAILED: set(),
    OrchestrationStatus.CANCELLED: set(),
    OrchestrationStatus.TIMED_OUT: set(),
}

VALID_TASK_TRANSITIONS: Dict[OrchTaskStatus, Set[OrchTaskStatus]] = {
    OrchTaskStatus.CREATED: {OrchTaskStatus.READY, OrchTaskStatus.CANCELLED},
    OrchTaskStatus.READY: {
        OrchTaskStatus.ASSIGNED,
        OrchTaskStatus.SKIPPED,
        OrchTaskStatus.CANCELLED,
    },
    OrchTaskStatus.ASSIGNED: {
        OrchTaskStatus.RUNNING,
        OrchTaskStatus.CANCELLED,
        OrchTaskStatus.READY,
    },
    OrchTaskStatus.RUNNING: {
        OrchTaskStatus.WAITING,
        OrchTaskStatus.SUCCEEDED,
        OrchTaskStatus.FAILED,
        OrchTaskStatus.TIMED_OUT,
        OrchTaskStatus.CANCELLED,
        OrchTaskStatus.PAUSED,
    },
    OrchTaskStatus.WAITING: {
        OrchTaskStatus.RUNNING,
        OrchTaskStatus.FAILED,
        OrchTaskStatus.CANCELLED,
        OrchTaskStatus.TIMED_OUT,
    },
    OrchTaskStatus.PAUSED: {OrchTaskStatus.RUNNING, OrchTaskStatus.CANCELLED},
    OrchTaskStatus.SUCCEEDED: set(),
    OrchTaskStatus.FAILED: set(),
    OrchTaskStatus.SKIPPED: set(),
    OrchTaskStatus.CANCELLED: set(),
    OrchTaskStatus.TIMED_OUT: set(),
}

VALID_ORCH_AGENT_TRANSITIONS: Dict[OrchAgentStatus, Set[OrchAgentStatus]] = {
    OrchAgentStatus.CREATED: {OrchAgentStatus.READY, OrchAgentStatus.TERMINATED},
    OrchAgentStatus.READY: {
        OrchAgentStatus.STARTING,
        OrchAgentStatus.CANCELLED,
        OrchAgentStatus.TERMINATED,
    },
    OrchAgentStatus.STARTING: {
        OrchAgentStatus.RUNNING,
        OrchAgentStatus.FAILED,
        OrchAgentStatus.CANCELLED,
    },
    OrchAgentStatus.RUNNING: {
        OrchAgentStatus.WAITING,
        OrchAgentStatus.HANDOFF,
        OrchAgentStatus.COMPLETING,
        OrchAgentStatus.FAILED,
        OrchAgentStatus.TIMED_OUT,
        OrchAgentStatus.CANCELLED,
        OrchAgentStatus.PAUSED,
    },
    OrchAgentStatus.WAITING: {OrchAgentStatus.RUNNING, OrchAgentStatus.CANCELLED, OrchAgentStatus.TIMED_OUT},
    OrchAgentStatus.PAUSED: {OrchAgentStatus.RUNNING, OrchAgentStatus.CANCELLED},
    OrchAgentStatus.HANDOFF: {OrchAgentStatus.RUNNING, OrchAgentStatus.COMPLETING, OrchAgentStatus.FAILED},
    OrchAgentStatus.COMPLETING: {OrchAgentStatus.SUCCEEDED, OrchAgentStatus.FAILED},
    OrchAgentStatus.SUCCEEDED: set(),
    OrchAgentStatus.FAILED: set(),
    OrchAgentStatus.CANCELLED: set(),
    OrchAgentStatus.TIMED_OUT: set(),
    OrchAgentStatus.TERMINATED: set(),
}


def can_transition_run(frm: OrchestrationStatus, to: OrchestrationStatus) -> bool:
    return to in VALID_RUN_TRANSITIONS.get(frm, set())


def can_transition_task(frm: OrchTaskStatus, to: OrchTaskStatus) -> bool:
    return to in VALID_TASK_TRANSITIONS.get(frm, set())


def can_transition_orch_agent(frm: OrchAgentStatus, to: OrchAgentStatus) -> bool:
    return to in VALID_ORCH_AGENT_TRANSITIONS.get(frm, set())


# ---------------------------------------------------------------------------
# Dataclasses (pure domain, no DB)
# ---------------------------------------------------------------------------


@dataclass
class Budget:
    max_total_steps: int = 1000
    max_total_tokens: int = 500_000
    max_total_cost: float = 10.0
    max_execution_time_seconds: int = DEFAULT_RUN_TIMEOUT_SECONDS
    max_tasks: int = DEFAULT_MAX_TASKS_PER_RUN
    max_agents: int = DEFAULT_MAX_AGENTS_PER_RUN
    max_delegation_depth: int = DEFAULT_MAX_DELEGATION_DEPTH
    max_tool_calls: int = 500
    max_parallel_tasks: int = DEFAULT_MAX_PARALLEL_TASKS


@dataclass
class BudgetLedger:
    allocated_tokens: int = 0
    consumed_tokens: int = 0
    allocated_cost: float = 0.0
    consumed_cost: float = 0.0
    allocated_tool_calls: int = 0
    consumed_tool_calls: int = 0
    allocated_steps: int = 0
    consumed_steps: int = 0

    @property
    def remaining_tokens(self) -> int:
        return max(0, self.allocated_tokens - self.consumed_tokens)

    @property
    def remaining_cost(self) -> float:
        return max(0.0, self.allocated_cost - self.consumed_cost)


@dataclass
class PlannedTask:
    task_id: str
    title: str
    description: str = ""
    instructions: str = ""
    parent_task_id: Optional[str] = None
    dependencies: List[str] = field(default_factory=list)
    required_capabilities: List[str] = field(default_factory=list)
    priority: TaskPriority = TaskPriority.NORMAL
    dependency_policy: DependencyPolicy = DependencyPolicy.ALL_SUCCESS
    risk_level: RiskLevel = RiskLevel.LOW
    required_permissions: List[str] = field(default_factory=list)
    requires_approval: bool = False
    assigned_agent_id: Optional[str] = None
    timeout_seconds: int = DEFAULT_TASK_TIMEOUT_SECONDS
    max_retries: int = 1
    retry_strategy: RetryStrategy = RetryStrategy.FIXED
    aggregation_strategy: Optional[AggregationStrategy] = None
    input: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskPlan:
    objective: str
    tasks: List[PlannedTask] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Built-in extensible role catalog (examples, not exclusive)
# ---------------------------------------------------------------------------

BUILTIN_ROLE_NAMES = [
    "ceo",
    "manager",
    "planner",
    "researcher",
    "developer",
    "coder",
    "designer",
    "browser_agent",
    "data_analyst",
    "marketing_agent",
    "sales_agent",
    "operations_agent",
    "qa_agent",
    "security_agent",
    "writer",
    "reviewer",
    "specialist",
    "worker",
    "custom",
]

ORCHESTRATION_EVENT_NAMES = [
    "ORCHESTRATION_CREATED",
    "PLAN_CREATED",
    "PLAN_REJECTED",
    "TASK_CREATED",
    "TASK_READY",
    "TASK_ASSIGNED",
    "TASK_STARTED",
    "TASK_PROGRESS",
    "TASK_COMPLETED",
    "TASK_FAILED",
    "TASK_REASSIGNED",
    "AGENT_STARTED",
    "AGENT_WAITING",
    "AGENT_COMPLETED",
    "AGENT_FAILED",
    "DELEGATION_CREATED",
    "HANDOFF_STARTED",
    "HANDOFF_COMPLETED",
    "BUDGET_WARNING",
    "BUDGET_EXCEEDED",
    "ORCHESTRATION_PAUSED",
    "ORCHESTRATION_RESUMED",
    "ORCHESTRATION_CANCELLED",
    "ORCHESTRATION_COMPLETED",
]
