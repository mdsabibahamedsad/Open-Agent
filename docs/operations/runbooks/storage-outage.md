# Runbook: storage outage

1. Check artifact availability SLI + upload/download latency.
2. Reads degrade; execution metadata stays queryable (Postgres).
3. Fail over bucket/endpoint per provider config; verify checksums on
   recovery (mismatch → quarantine, never serve corrupt bytes).
4. Report measured impact; update backup report.
