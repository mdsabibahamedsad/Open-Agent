# Sandbox — Operations (Lifecycle, Quotas, GC, Config)

## Lifecycle

`CREATING → CREATED → STARTING → READY ⇄ RUNNING → STOPPING → STOPPED →
DESTROYING → DESTROYED`, with `WAITING` (approval), `FAILED`, `EXPIRED`.
Request → validate → authorize → create → configure → start → execute →
collect → stop → cleanup. Executions:
`QUEUED → RUNNING → SUCCEEDED/FAILED/TIMED_OUT/CANCELLED/KILLED/
RESOURCE_LIMIT/POLICY_DENIED/SANDBOX_ERROR`, plus `WAITING` (parked for
approval, surfaced as `WAITING_FOR_APPROVAL`).

## Cancellation & leases

Cancel: cooperative task cancel → graceful stop → kill → provider hygiene
(container restarted on cancel-mid-run). Leases (`owner`, `task_id`,
`expires_at`, heartbeat): default one-task-one-sandbox; sharing needs an
explicit lease or it is denied.

## Concurrency & quotas

Per-org sandbox count + concurrent executions; per-user/per-agent
concurrency; CPU/memory/disk quotas. Backpressure surfaces as
`POLICY_DENIED` (quota) — integrate with the Redis worker queues for
scheduling, priority, retry, dead-letter (existing infra, no new queue
for sandbox admission).

## Garbage collection (`sweep`)

Expired sandboxes (stop+destroy), stale leases, expired artifacts
(storage delete), old completed executions past retention. Run on
`SANDBOX_CLEANUP_INTERVAL`; respects `SANDBOX_ARTIFACT_RETENTION`.

## Configuration (`SANDBOX_*`)

`PROVIDER | DEFAULT_PROFILE | DEFAULT_TIMEOUT | MAX_TIMEOUT |
MAX_MEMORY | MAX_CPU | MAX_DISK | MAX_PIDS | NETWORK_MODE | IMAGE |
IMAGE_DIGEST | IMAGE_TRUST | CLEANUP_INTERVAL | ARTIFACT_RETENTION |
ALLOW_LOCAL_FALLBACK | EGRESS_PROXY` (+ workspace/artifact roots,
quotas). Invalid values fail closed; see `.env.example`.

## Failure recovery

Container crash, worker crash, daemon restart, network failure, timeout,
OOM, disk pressure, API restart: state persists in Postgres; orphans are
reaped; executions never resume mid-stream — they are re-created from
the persisted request. Document daemon/mount assumptions per deploy.
