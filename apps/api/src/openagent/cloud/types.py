"""MP25: canonical cloud runtime vocabulary.

Provider-neutral enums + the canonical execution lifecycle state machine.
Pure python (no DB/Redis) so it is unit-testable and reusable by workers.
"""

from __future__ import annotations


class RuntimeMode:
    SELF_HOSTED = "self_hosted"
    CLOUD = "cloud"
    HYBRID = "hybrid"


class ExecutionState:
    SUBMITTED = "SUBMITTED"
    QUEUED = "QUEUED"
    SCHEDULED = "SCHEDULED"
    DISPATCHING = "DISPATCHING"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    PAUSED = "PAUSED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMED_OUT = "TIMED_OUT"
    RETRYING = "RETRYING"
    EXPIRED = "EXPIRED"

    ALL = (
        "SUBMITTED", "QUEUED", "SCHEDULED", "DISPATCHING", "STARTING",
        "RUNNING", "WAITING", "PAUSED", "SUCCEEDED", "FAILED",
        "CANCELLED", "TIMED_OUT", "RETRYING", "EXPIRED",
    )


TERMINAL_EXECUTION_STATES = frozenset({
    ExecutionState.SUCCEEDED,
    ExecutionState.FAILED,
    ExecutionState.CANCELLED,
    ExecutionState.TIMED_OUT,
    ExecutionState.EXPIRED,
})

# Validated state transitions. Workers may only move executions along
# these edges; anything else is rejected safely.
_EXECUTION_TRANSITIONS: dict[str, frozenset[str]] = {
    ExecutionState.SUBMITTED: frozenset({
        ExecutionState.QUEUED, ExecutionState.SCHEDULED,
        ExecutionState.CANCELLED, ExecutionState.EXPIRED,
    }),
    ExecutionState.QUEUED: frozenset({
        ExecutionState.DISPATCHING, ExecutionState.SCHEDULED,
        ExecutionState.CANCELLED, ExecutionState.EXPIRED,
    }),
    ExecutionState.SCHEDULED: frozenset({
        ExecutionState.QUEUED, ExecutionState.CANCELLED, ExecutionState.EXPIRED,
    }),
    ExecutionState.DISPATCHING: frozenset({
        ExecutionState.STARTING, ExecutionState.QUEUED,
        ExecutionState.CANCELLED, ExecutionState.EXPIRED,
    }),
    ExecutionState.STARTING: frozenset({
        ExecutionState.RUNNING, ExecutionState.FAILED,
        ExecutionState.CANCELLED, ExecutionState.TIMED_OUT, ExecutionState.EXPIRED,
    }),
    ExecutionState.RUNNING: frozenset({
        ExecutionState.WAITING, ExecutionState.PAUSED, ExecutionState.SUCCEEDED,
        ExecutionState.FAILED, ExecutionState.CANCELLED, ExecutionState.TIMED_OUT,
        ExecutionState.RETRYING,
    }),
    ExecutionState.WAITING: frozenset({
        ExecutionState.RUNNING, ExecutionState.CANCELLED,
        ExecutionState.TIMED_OUT, ExecutionState.EXPIRED,
    }),
    ExecutionState.PAUSED: frozenset({
        ExecutionState.RUNNING, ExecutionState.CANCELLED, ExecutionState.EXPIRED,
    }),
    ExecutionState.RETRYING: frozenset({
        ExecutionState.QUEUED, ExecutionState.FAILED, ExecutionState.CANCELLED,
        ExecutionState.EXPIRED,
    }),
    ExecutionState.SUCCEEDED: frozenset(),
    ExecutionState.FAILED: frozenset({ExecutionState.RETRYING}),
    ExecutionState.CANCELLED: frozenset(),
    ExecutionState.TIMED_OUT: frozenset({ExecutionState.RETRYING}),
    ExecutionState.EXPIRED: frozenset(),
}


def is_valid_execution_transition(from_state: str, to_state: str) -> bool:
    """Validate an execution state transition (fail-safe on unknown states)."""
    if from_state not in _EXECUTION_TRANSITIONS:
        return False
    if to_state not in ExecutionState.ALL:
        return False
    if from_state == to_state:
        return True  # idempotent re-delivery is fine
    return to_state in _EXECUTION_TRANSITIONS[from_state]


def valid_execution_targets(from_state: str) -> frozenset[str]:
    return _EXECUTION_TRANSITIONS.get(from_state, frozenset())


class WorkerState:
    REGISTERING = "REGISTERING"
    STARTING = "STARTING"
    READY = "READY"
    BUSY = "BUSY"
    DRAINING = "DRAINING"
    UNHEALTHY = "UNHEALTHY"
    OFFLINE = "OFFLINE"
    TERMINATED = "TERMINATED"

    ALL = ("REGISTERING", "STARTING", "READY", "BUSY", "DRAINING",
           "UNHEALTHY", "OFFLINE", "TERMINATED")


_WORKER_TRANSITIONS: dict[str, frozenset[str]] = {
    WorkerState.REGISTERING: frozenset({WorkerState.STARTING, WorkerState.OFFLINE}),
    WorkerState.STARTING: frozenset({WorkerState.READY, WorkerState.UNHEALTHY, WorkerState.OFFLINE}),
    WorkerState.READY: frozenset({WorkerState.BUSY, WorkerState.DRAINING,
                                  WorkerState.UNHEALTHY, WorkerState.OFFLINE}),
    WorkerState.BUSY: frozenset({WorkerState.READY, WorkerState.DRAINING,
                                 WorkerState.UNHEALTHY, WorkerState.OFFLINE}),
    WorkerState.DRAINING: frozenset({WorkerState.OFFLINE, WorkerState.READY}),
    WorkerState.UNHEALTHY: frozenset({WorkerState.READY, WorkerState.DRAINING,
                                      WorkerState.OFFLINE, WorkerState.TERMINATED}),
    WorkerState.OFFLINE: frozenset({WorkerState.REGISTERING, WorkerState.TERMINATED}),
    WorkerState.TERMINATED: frozenset(),
}


def is_valid_worker_transition(from_state: str, to_state: str) -> bool:
    if from_state not in _WORKER_TRANSITIONS:
        return False
    if to_state not in WorkerState.ALL:
        return False
    if from_state == to_state:
        return True
    return to_state in _WORKER_TRANSITIONS[from_state]


class RegionStatus:
    ACTIVE = "ACTIVE"
    DEGRADED = "DEGRADED"
    DRAINING = "DRAINING"
    MAINTENANCE = "MAINTENANCE"
    OFFLINE = "OFFLINE"

    ALL = ("ACTIVE", "DEGRADED", "DRAINING", "MAINTENANCE", "OFFLINE")


class ExecutionPriority:
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

    ALL = ("LOW", "NORMAL", "HIGH", "CRITICAL")
    RANK = {"LOW": 0, "NORMAL": 1, "HIGH": 2, "CRITICAL": 3}


class ExecutionClass:
    WORKFLOW = "workflow"
    AGENT = "agent"
    BROWSER = "browser"
    CODE = "code"
    SANDBOX = "sandbox"
    SCHEDULED = "scheduled"
    WEBHOOK = "webhook"
    LONG_RUNNING = "long_running"

    ALL = ("workflow", "agent", "browser", "code", "sandbox",
           "scheduled", "webhook", "long_running")


class QueueName:
    WORKFLOW_DEFAULT = "workflow.default"
    WORKFLOW_PRIORITY = "workflow.priority"
    AGENT_DEFAULT = "agent.default"
    AGENT_PRIORITY = "agent.priority"
    BROWSER = "browser"
    CODE = "code"
    SANDBOX = "sandbox"
    SCHEDULED = "scheduled"
    WEBHOOK = "webhook"
    LONG_RUNNING = "long-running"
    HIGH_MEMORY = "high-memory"
    HIGH_CPU = "high-cpu"

    ALL = ("workflow.default", "workflow.priority", "agent.default",
           "agent.priority", "browser", "code", "sandbox", "scheduled",
           "webhook", "long-running", "high-memory", "high-cpu")


class IncidentMode:
    NORMAL = "NORMAL"
    DEGRADED = "DEGRADED"
    MAINTENANCE = "MAINTENANCE"
    EMERGENCY = "EMERGENCY"

    ALL = ("NORMAL", "DEGRADED", "MAINTENANCE", "EMERGENCY")


class DataResidency:
    ANY_REGION = "ANY_REGION"
    EU_ONLY = "EU_ONLY"
    US_ONLY = "US_ONLY"
    APAC_ONLY = "APAC_ONLY"
    ORG_SELECTED = "ORG_SELECTED"
    PRIVATE_REGION = "PRIVATE_REGION"

    ALL = ("ANY_REGION", "EU_ONLY", "US_ONLY", "APAC_ONLY",
           "ORG_SELECTED", "PRIVATE_REGION")


class ArtifactState:
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    DELETED = "DELETED"
    QUARANTINED = "QUARANTINED"

    ALL = ("ACTIVE", "EXPIRED", "DELETED", "QUARANTINED")


class CloudFeature:
    """Feature-flag names for the cloud runtime (single canonical list)."""

    CLOUD_RUNTIME = "cloud_runtime"
    DISTRIBUTED_WORKERS = "distributed_workers"
    MULTI_REGION = "multi_region"
    AUTOSCALING = "autoscaling"
    OBJECT_STORAGE = "object_storage"
    CLOUD_SCHEDULER = "cloud_scheduler"
    CLOUD_ARTIFACTS = "cloud_artifacts"

    ALL = ("cloud_runtime", "distributed_workers", "multi_region",
           "autoscaling", "object_storage", "cloud_scheduler", "cloud_artifacts")
