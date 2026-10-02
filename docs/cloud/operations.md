# Operations

Health aggregates api/database/queue/workers/scheduler/object_storage/
sandbox/browser/model_providers/connectors into
`HEALTHY/DEGRADED/UNAVAILABLE/UNKNOWN` (Master Account console).
Incident modes: `NORMAL` (accept), `DEGRADED` (reduced capacity),
`MAINTENANCE`/`EMERGENCY` (no new executions; existing work preserved).
Maintenance drains regions/workers/queues/storage gracefully. GC sweeps
expired leases/artifacts, dead workers, stale locks, old events/logs,
orphaned sandboxes/storage (idempotent; detect → quarantine → cleanup).
Orphan detection classifies execution-without-worker,
artifact-without-execution, sandbox-without-task, worker-without-
heartbeat, queue-message-without-execution — never deletes on sight.
