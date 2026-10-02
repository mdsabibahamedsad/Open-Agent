# Runbook: database outage

1. Confirm dependency health (never use as liveness gate).
2. Open incident; set status page to degraded/partial_outage.
3. Reads: fail over to replica per provider docs. Writes: pause new
   executions (incident mode), preserve existing work — never silently
   cancel.
4. Restore from latest verified backup only; verify integrity first.
5. Reconcile scheduler leases + queue claims after recovery (expired
   claims requeue automatically).
6. Record measured RPO/RTO in backup report.
