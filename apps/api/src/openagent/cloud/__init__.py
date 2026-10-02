"""OpenAgent Cloud Runtime (Master Prompt 25).

Control plane vs execution plane separation:

* Control plane: auth, orgs, config, billing/entitlements, execution
  requests, scheduling, routing, worker registration/health, quotas,
  usage, audit. Lives in the API process + PostgreSQL.
* Execution plane: workflow/agent/tool/browser/code/sandbox execution,
  background workers, artifacts, streams. Lives in worker processes,
  sandboxes, object storage, queues.

The open-source core stays usable with the cloud layer disabled
(``OPENAGENT_CLOUD_ENABLED=false`` / runtime mode ``self_hosted``).
"""

from openagent.cloud.types import (
    RuntimeMode,
    ExecutionState,
    WorkerState,
    RegionStatus,
    ExecutionPriority,
    ExecutionClass,
    QueueName,
    IncidentMode,
    DataResidency,
    ArtifactState,
    is_valid_execution_transition,
    TERMINAL_EXECUTION_STATES,
)

__all__ = [
    "RuntimeMode",
    "ExecutionState",
    "WorkerState",
    "RegionStatus",
    "ExecutionPriority",
    "ExecutionClass",
    "QueueName",
    "IncidentMode",
    "DataResidency",
    "ArtifactState",
    "is_valid_execution_transition",
    "TERMINAL_EXECUTION_STATES",
]
