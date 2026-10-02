# Registries & Mirrors

`marketplace_registries` configures where packages come from: OFFICIAL,
COMMUNITY, PRIVATE, GIT, SELF_HOSTED, ENTERPRISE. Each registry carries a
trust level, visibility, verification policy and signature policy
(`require_signed`, blocked statuses).

## Trust rules

- No registry is trusted implicitly (`IMPLICITLY_TRUSTED_REGISTRIES` is
  empty by design).
- Fetching requires: registry enabled + marketplace opt-in + signature
  policy satisfied for the artifact.
- Trust levels gate installation warnings through the existing MP22 trust
  policy; they never grant permissions.
- The default `local` registry (SELF_HOSTED, ORGANIZATION trust) backs
  offline deployments: import, browse, install, update, export with no
  network.

## Mirrors and offline

`mirror_of` chains resolve for display (cycle-safe) and let an enterprise
mirror front the public registry. Mirroring configuration is data, not a
transfer engine — background synchronization ships in MP24. Offline
marketplaces are first-class: `LOCAL_CATALOG` marketplace types plus the
local registry cover air-gapped use.
