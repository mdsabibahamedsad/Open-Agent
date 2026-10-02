# Metrics

Canonical names in `METRIC_CATALOG` (API, workflow, agents, workers,
queues, storage, rate limits). Values come from real collectors
(existing `MetricsCollector`, commerce usage, queue/worker state) —
never fabricated. `Telemetry` facade is failure-safe (no-op when the
backend is down). Rate-limit status exposes limit/used/remaining/reset
for API, execution, webhooks, artifacts.
