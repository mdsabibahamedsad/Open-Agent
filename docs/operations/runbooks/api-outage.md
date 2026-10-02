# Runbook: API outage

1. Confirm: `openagent_ops.py health` + `/operations/health` — which
   components report UNAVAILABLE vs UNKNOWN.
2. Check deployments: recent ACTIVE deploy to `api`? Prepare rollback
   pre-check (`/master/control/rollback`) — do NOT auto-roll back.
3. Inspect alerts/incidents; open an incident (SEVERITY per impact).
4. Mitigate: drain traffic via maintenance window; scale API replicas.
5. Verify DB/Redis dependency health separately from liveness.
6. Resolve with timeline entries; attach postmortem ref.
