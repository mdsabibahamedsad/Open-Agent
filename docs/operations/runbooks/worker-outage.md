# Runbook: worker outage

1. List workers: UNHEALTHY/OFFLINE counts, per pool/region.
2. Heartbeat expiry auto-recovers claims — verify requeue, don't
   double-submit.
3. Drain affected pool, shift placement via residency-safe failover.
4. Restart worker deployments (rolling; PDB protects API).
5. If crash-looping on a payload class, engage kill switch for the
   execution class while investigating — scoped and reversible.
