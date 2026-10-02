# OpenAgent Cloud Runtime Architecture (Master Prompt 25)

## 1. Existing runtime (what was already there)

* **API**: FastAPI (`apps/api`), versioned `/api/v1`, session + RBAC +
  service accounts, audit logs, rate limiting, request correlation.
* **Workflow execution**: `openagent.runtime` engine + `workflow_executions`
  tables; background `apps/worker` with Redis `JobQueue` (priority zset,
  scheduled set, processing hash, DLQ list), retry/backoff, `ExecutionWorker`.
* **Core services reused**: `core/storage.py` (local/S3 backends),
  `core/scheduler.py` (scheduled jobs), `core/idempotency.py`
  (idempotency keys), `core/concurrency.py`, `core/resilience.py`,
  `core/metrics.py`, sandbox profiles/providers, connector SSRF guard.
* **Billing (MP24)**: provider-neutral billing/payout/tax providers,
  entitlement engine, `usage_meters/records/summaries`, quotas —
  **reused, never duplicated**.
* **Infra**: Postgres 15 + Redis 7 via Docker Compose; frontend Next.js.

## 2. Proposed cloud architecture

```text
User → Cloud API → Control Plane (authz, entitlements, quotas,
     placement, dispatcher) → Queue → Worker Fleet → Sandbox →
     Object Storage → Result + Usage → Commerce billing
```

Self-hosted keeps working with the cloud layer disabled
(`OPENAGENT_CLOUD_ENABLED=false`): `LocalRuntimeProvider` /
`DockerRuntimeProvider` serve execution locally.

## 3. Service boundaries

| Plane | Owns | Never owns |
|---|---|---|
| Control (API + Postgres) | auth, orgs, config, billing, requests, scheduling, routing, worker registry/health, quotas, usage, audit | untrusted code execution |
| Execution (workers, sandboxes, queues, storage) | workflow/agent/tool/browser/code runs, artifacts, streams | master credentials, other tenants' data |

Workers receive **single-execution scoped credentials** (lease-bound).
Control-plane credentials never leave the API process.

## 4. Worker lifecycle

`REGISTERING → STARTING → READY ⇄ BUSY → DRAINING → OFFLINE`
(`UNHEALTHY` on heartbeat expiry, `TERMINATED` end-state). Registration
carries id/region/pool/capabilities/resources/version/labels. Heartbeats
refresh liveness; expiry recovers outstanding work via lease expiry +
visibility-timeout requeue. Draining stops new claims and finishes safe
work (deployment-safe replacement).

## 5. Queue topology

Logical queues (`workflow.default/priority`, `agent.default/priority`,
`browser`, `code`, `sandbox`, `scheduled`, `webhook`, `long-running`,
`high-memory`, `high-cpu`) route by **policy** (`route_queue`), not by
tenant choice. Providers: Redis baseline (pending list + inflight hash +
DLQ), in-memory fake for tests, Postgres where appropriate; Kafka/SQS/
NATS adapters fit the same `QueueProvider` interface.

## 6. Storage architecture

DB keeps metadata + small results; object storage keeps large
outputs/artifacts/logs (`{"type":"artifact","artifact_id":"…"}` refs).
Categories isolate security boundaries; uploads validate
checksum/size/MIME/extension + malware-scan hook + quarantine; downloads
use signed expiring tokens with per-org binding and download limits.
Providers: filesystem (dev), fake (tests), S3-compatible (MinIO/R2/AWS).

## 7. Scaling architecture

`decide_autoscale` consumes queue depth/age, utilization, CPU/memory,
plan limits, region capacity → desired worker count, clamped by
min/max, cooldown, scale steps, tenant quotas, regional + global caps,
cost protection. No unlimited scale-up path exists.

## 8. Failure recovery

Crash (worker/process/machine/network/queue/sandbox/DB/storage/API)
→ lease/visibility expiry → requeue → resume/restart. State transitions
are allow-list validated; worker ownership is checked; retries only for
retryable errors; destructive actions need idempotency keys; DLQ
retains debuggable metadata with inspect/retry/cancel/delete.

## 9. Region architecture

Regions are data (`cloud_regions`): id/slug/status/capabilities/
residency tags/cost/capacity. Statuses: ACTIVE/DEGRADED/DRAINING/
MAINTENANCE/OFFLINE. Placement scores capability, residency, quota,
queue pressure, latency/cost, availability, org policy. Failover never
violates residency/security/credential policy. Scheduler tick lease +
schedule dedup keys make multi-replica scheduling safe.

## 10. Security boundaries

Tenant isolation enforced at API, scheduler, queue (org-scoped claims),
worker (scoped creds), sandbox, storage (org-prefixed keys), artifacts
(signed org-bound URLs), logs/metrics (redacted), results. Network
policies default `NO_NETWORK`; SSRF guards reuse the connector guard.
Secrets never enter prompts/context/outputs/logs/metrics/events/
artifacts. Incident modes (NORMAL/DEGRADED/MAINTENANCE/EMERGENCY)
stop new work without silently cancelling existing work.
