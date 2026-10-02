# Cloud security

Threat model + mitigations:

1. Unauthenticated execution → session/RBAC + service-token worker API.
2. Unauthorized execution → org-context + permission checks per call.
3. Cross-tenant access → org checks at API/scheduler/queue/worker/
   sandbox/storage/artifact/log/result layers (tested).
4. Unrestricted worker credentials → single-execution scoped creds,
   short-lived, revocable, rotated; master secrets never leave API.
5. Secrets in logs → redaction in event/stream paths; secret refs only.
6. Secrets in model context → credential-handle passing (sandbox
   patterns reused).
7. Unrestricted worker network → `NO_NETWORK` default, allowlist egress;
   SSRF guard reuses `openagent.connectors.netsec` (no duplicate logic).
8. Unbounded queue growth → max-depth reject + backpressure.
9. Unlimited autoscaling → ceilings + cooldown + quotas.
10. Duplicate execution → idempotency keys + schedule dedup + validated
    transitions + ownership checks.
11. Worker impersonation → `X-Worker-ID` vs bearer binding (tested).
12. Unauthorized artifacts → org checks + signed expiring tokens (tested).
13. Unsafe failover → residency-gated placement (tested).
14. Cloud dependency for self-hosted → feature-gated, disabled by
    default (tested).
15. Host execution outside sandbox → sandbox-bound worker execution.
16. Billing duplication → commerce reuse only (staged usage events).
17. Execution outside entitlement → commercial gate at dispatch.
18. Memory-only infra state → Postgres-backed regions/workers/leases/
    queues/artifacts/events + Redis visibility deadlines.
