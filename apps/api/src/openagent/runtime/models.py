"""Core execution models and state machines."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set
from uuid import UUID


class WorkflowRunStatus(str, enum.Enum):
    """Workflow execution lifecycle states."""
    QUEUED = "queued"
    RUNNING = "running"
    WAITING = "waiting"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class NodeRunStatus(str, enum.Enum):
    """Node execution lifecycle states."""
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    WAITING = "waiting"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class TriggerType(str, enum.Enum):
    """Workflow trigger types."""
    MANUAL = "manual"
    SCHEDULED = "scheduled"
    WEBHOOK = "webhook"
    API = "api"
    EVENT = "event"


# State transition rules
VALID_WORKFLOW_TRANSITIONS: Dict[WorkflowRunStatus, Set[WorkflowRunStatus]] = {
    WorkflowRunStatus.QUEUED: {WorkflowRunStatus.RUNNING, WorkflowRunStatus.CANCELLED},
    WorkflowRunStatus.RUNNING: {
        WorkflowRunStatus.WAITING,
        WorkflowRunStatus.COMPLETED,
        WorkflowRunStatus.FAILED,
        WorkflowRunStatus.CANCELLED,
        WorkflowRunStatus.TIMED_OUT,
        WorkflowRunStatus.PAUSED,
    },
    WorkflowRunStatus.WAITING: {WorkflowRunStatus.RUNNING, WorkflowRunStatus.CANCELLED},
    WorkflowRunStatus.PAUSED: {WorkflowRunStatus.RUNNING, WorkflowRunStatus.CANCELLED},
    WorkflowRunStatus.COMPLETED: set(),
    WorkflowRunStatus.FAILED: set(),
    WorkflowRunStatus.CANCELLED: set(),
    WorkflowRunStatus.TIMED_OUT: set(),
}

VALID_NODE_TRANSITIONS: Dict[NodeRunStatus, Set[NodeRunStatus]] = {
    NodeRunStatus.PENDING: {NodeRunStatus.READY, NodeRunStatus.CANCELLED, NodeRunStatus.SKIPPED},
    NodeRunStatus.READY: {NodeRunStatus.RUNNING, NodeRunStatus.CANCELLED, NodeRunStatus.SKIPPED},
    NodeRunStatus.RUNNING: {NodeRunStatus.WAITING, NodeRunStatus.SUCCEEDED, NodeRunStatus.FAILED, NodeRunStatus.CANCELLED, NodeRunStatus.TIMED_OUT},
    WorkflowRunStatus.WAITING: {WorkflowRunStatus.RUNNING, WorkflowRunStatus.CANCELLED},  # Note: using WorkflowRunStatus key here, will fix
    NodeRunStatus.WAITING: {NodeRunStatus.RUNNING, NodeRunStatus.CANCELLED},
    NodeRunStatus.SUCCEEDED: set(),
    NodeRunStatus.FAILED: set(),
    NodeRunStatus.SKIPPED: set(),
    NodeRunStatus.CANCELLED: set(),
    NodeRunStatus.TIMED_OUT: set(),
}

# Fix the WAITING key
VALID_NODE_TRANSITIONS[NodeRunStatus.WAITING] = {NodeRunStatus.RUNNING, NodeRunStatus.CANCELLED}


def can_transition_workflow(from_status: WorkflowRunStatus, to_status: WorkflowRunStatus) -> bool:
    """Check if a workflow status transition is valid."""
    return to_status in VALID_WORKFLOW_TRANSITIONS.get(from_status, set())


def can_transition_node(from_status: NodeRunStatus, to_status: NodeRunStatus) -> bool:
    """Check if a node status transition is valid."""
    return to_status in VALID_NODE_TRANSITIONS.get(from_status, set())


@dataclass
class NodeResult:
    """Result of a node execution."""
    node_id: str
    status: NodeRunStatus
    outputs: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    error_code: Optional[str] = None
    error_retryable: bool = False
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    attempt: int = 1
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionContext:
    """Runtime context passed to node executors."""
    execution_id: str
    workflow_id: str
    workflow_version_id: str
    organization_id: str
    triggered_by: Optional[str] = None
    variables: Dict[str, Any] = field(default_factory=dict)
    node_results: Dict[str, NodeResult] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    cancelled: bool = False
    timeout_at: Optional[datetime] = None


@dataclass
class NodeExecutionPlan:
    """Planned node execution with dependencies."""
    node_id: str
    node_type: str
    name: str
    config: Dict[str, Any]
    depends_on: List[str] = field(default_factory=list)  # node_ids this depends on
    position: Optional[Dict[str, int]] = None
    retry_policy: Optional[Dict[str, Any]] = None
    timeout_seconds: Optional[int] = None
    approval_required: bool = False
    is_disabled: bool = False
    is_terminal: bool = False  # node that can end a branch without outgoing edges


@dataclass
class ExecutionPlan:
    """Complete execution plan for a workflow run."""
    execution_id: str
    workflow_id: str
    workflow_version_id: str
    trigger: Dict[str, Any]
    nodes: List[NodeExecutionPlan] = field(default_factory=list)
    edges: List[Dict[str, Any]] = field(default_factory=list)
    variables: List[Dict[str, Any]] = field(default_factory=list)
    settings: Dict[str, Any] = field(default_factory=dict)
    max_concurrency: int = 1
    timeout_seconds: Optional[int] = None

    # Computed fields (populated by planner)
    execution_order: List[List[str]] = field(default_factory=list)  # topological levels
    node_map: Dict[str, NodeExecutionPlan] = field(default_factory=dict)
    trigger_ids: List[str] = field(default_factory=list)
    terminal_node_ids: Set[str] = field(default_factory=set)
    fan_in_node_ids: Set[str] = field(default_factory=set)
    disabled_node_ids: Set[str] = field(default_factory=set)


@dataclass
class ExecutionLease:
    """Worker lease for an execution."""
    execution_id: str
    worker_id: str
    acquired_at: datetime
    expires_at: datetime
    heartbeat_at: datetime


@dataclass
class ExecutionEvent:
    """Event emitted during execution for observability."""
    execution_id: str
    event_type: str
    node_id: Optional[str] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    payload: Dict[str, Any] = field(default_factory=dict)
    sequence: int = 0


# Import timezone for datetime
from datetime import timezone