# Workers

Lifecycle: `REGISTERING → STARTING → READY ⇄ BUSY → DRAINING → OFFLINE`
(`UNHEALTHY` on heartbeat expiry). Registration advertises worker id,
service identity, region, pool, capabilities, resources, version,
labels, tenant restrictions. Heartbeats (`WORKER_HEARTBEAT_SECONDS`,
TTL `WORKER_HEARTBEAT_TTL_SECONDS`) refresh liveness; expiry marks the
worker `UNHEALTHY` and its work becomes recoverable via lease/claim
expiry. Claims mint **single-execution scoped credentials** (lease id +
expiry); workers never see platform secrets or other tenants' data.
`DRAINING` stops new claims; active work finishes or requeues.
`apps/worker/src/worker/cloud_worker.py` implements this against the
service-authenticated internal API (`/internal/workers/*`).
