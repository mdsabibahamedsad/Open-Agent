# Control plane

`openagent/control/` + `api/v1/operations|platform|enterprise` + 16 new
tables (migration `025`). Never executes work: it governs tenancy,
config, policy, regions, pools, quotas, entitlements, usage, audit,
health, incidents, flags, and operations. Organization admins see org
scope (`/operations`, `/enterprise`); platform-only controls live under
`/master/control` (Master Account + step-up + op locks + audit).
