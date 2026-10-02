# Workload Identity

Workers, sandboxes, browsers, code runs, scheduled tasks, and
connector executions authenticate as workloads: kind + org + execution
+ region/pool + scopes, short TTL, prompt revocation. The
CredentialBroker issues single-use scoped leases (subset of the
workload grant, org-bound), audits every issue/use/revoke, and kills
all leases on workload revocation. Containers never embed long-lived
secrets.
