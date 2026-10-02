# Runbook: region outage

1. Mark region DEGRADED/DRAINING (audited, step-up, op-locked so two
   admins can't race).
2. Placement engine fails over within residency policy — verify no
   residency violations in placements.
3. Private-region tenants: no automatic failover outside their region;
   queue + notify instead.
4. Recover: drain → verify health → ACTIVE; reconcile pools.
