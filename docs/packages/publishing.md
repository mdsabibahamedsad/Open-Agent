# Publishing & Sharing

## Validation pipeline

```
schema → dependencies → permissions → security → runtime compatibility →
policy → integrity → evaluation → publish
```

Findings are `{code, path, severity, message}` with `INFO / WARNING / ERROR /
BLOCKER`. `ERROR` or `BLOCKER` blocks publication. Run it anytime:

```bash
python scripts/openagent_package.py validate ./my-workforce
# or POST /packages/{id}/versions/{version}/validate
```

## Publication

1. Create the package and a manifest version (`DRAFT`).
2. Validate (results stored in `package_validation_results`; security scan in `package_security_scans`).
3. Sign official/CORE versions (HMAC for self-hosted, Ed25519 for publishers).
4. Publish (`package:manage` permission). Publication re-validates; failures abort.

## Trust

`CORE > VERIFIED > ORGANIZATION > COMMUNITY > UNTRUSTED`. Trust controls
warnings, network defaults, sandbox requirements and approval strictness —
never permissions. Imports land as `UNTRUSTED`; official packages need
verified signatures and platform-owner handling.

## Visibility & ownership

`PRIVATE / TEAM / ORGANIZATION / PUBLIC / UNLISTED`, enforced by RBAC and
tenant-scoped queries:

- Private packages never appear in other tenants' catalogs (cross-tenant reads return 404).
- Sharing a package never shares credentials, memory, conversations, files or connector instances.
- Ownership: platform / organization / team / user / community. Global packages are editable only by platform owners.
- Master-account actions (official flags, revocations, publisher verification, category management) are authenticated, authorized, audited and rate-limited — never hard-coded.

## Forking & cloning

Forking creates a new identity with provenance (`source_package_id`,
`source_version`, fork owner, timestamp). The original is never mutated.
Future upstream sync compares versions without overwriting local changes
(diff view exposes permission deltas explicitly).
