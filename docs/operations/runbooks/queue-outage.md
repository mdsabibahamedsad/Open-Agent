# Runbook: queue outage

1. Check `queue.depth` + `oldest_age` per queue (`/operations` + cloud
   queues). Backpressure rejects new work with 429 — expected.
2. Inspect workers: heartbeats stale? Sweep marks UNHEALTHY; claims
   expire back to pending automatically.
3. Redis down: restart/fail over per provider docs; depth recovers from
   execution/attempt state (no in-memory-only state to lose).
4. DLQ spike: inspect reasons before bulk requeue.
