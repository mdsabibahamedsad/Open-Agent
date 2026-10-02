# Runbook: sandbox outage

1. Check sandbox count/utilization/crash rate + security violations.
2. Disable risky execution profiles (controlled, audited) while
   keeping safe profiles running.
3. Executions fail safe to FAILED (retryable only if retryable);
   never silently drop.
4. Verify image pins before re-enabling; record WASM/container cause.
