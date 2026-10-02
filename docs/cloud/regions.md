# Regions

Regions are data (`cloud_regions`), never hard-coded provider names:
id/slug, name, status (`ACTIVE/DEGRADED/DRAINING/MAINTENANCE/OFFLINE`),
capabilities, residency tags, cost weight, capacity. Placement scores
capability, residency, quota, queue pressure, cost, availability and org
policy. `DataResidencyPolicy` (`ANY_REGION`, `EU_ONLY`, `US_ONLY`,
`APAC_ONLY`, `ORG_SELECTED`, `PRIVATE_REGION`) is always honored —
failover never violates it.
