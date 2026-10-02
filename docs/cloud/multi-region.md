# Multi-region

Each region may host API gateway, scheduler, queue, workers, sandbox
runtime, object storage, cache and observability. The control plane
stays global for identity/billing/policy; execution places regionally.
Failover: primary unavailable → placement engine → secondary region —
without violating residency, security, tenant, credential or execution
limits. `FEATURE_MULTI_REGION` gates multi-region behavior; single
region (`local-1`) is the default.
