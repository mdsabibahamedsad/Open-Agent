# Runbook: model provider outage

1. Check provider health/latency/error-rate in Model Router ops view.
2. Authorized operators: disable the provider (audited kill path) —
   routing policy shifts load without Agent Runtime code changes.
3. Watch queue latency SLI; scale workers if retries pile up.
4. Re-enable after error budget recovers; record in incident timeline.
