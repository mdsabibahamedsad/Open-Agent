# Installation, Updates & Rollback

## Preview (no writes)

`POST /packages/{id}/versions/{version}/install-preview` returns everything
the wizard shows:

- resources to create, resolved dependencies (+failures/warnings)
- required credentials, connectors, tools, skills, models, permissions
- security warnings + risk, policy conflicts
- schema-generated configuration fields + validation errors
- `can_install` gate and estimated changes, plus the resource graph

## Install

`REQUESTED → RESOLVING → VALIDATING → [AWAITING_CONFIGURATION] →
INSTALLING → VERIFYING → INSTALLED` (or `FAILED`).

- Integrity, compatibility, permissions, organization policy, credentials,
  connectors, tools, models and skills are checked before anything is created.
- Resources materialize as real tenant rows (agents, workflows, skills,
  presets; bundles/prompts/teams persist as auditable graph nodes).
- Idempotency keys + unique constraints prevent double installation;
  verification counts created nodes before marking `INSTALLED`.

## Update

`plan → compare → dependency check → security check → migration plan →
approval → apply → verify`:

1. `POST /installations/{id}/update-plan {to_version}` — diff, breaking-change
   detection, permission deltas, affected dependents (impact analysis).
2. `POST /installations/{id}/update` — applies after the plan is approved;
   previous snapshots are retained.

Active production workflows are never silently broken: permission changes
are always surfaced, breaking updates flagged.

## Rollback

`POST /installations/{id}/rollback` restores the previous valid version from
retained snapshots (new version rows pointing at prior payloads; originals
untouched). If an update crashes midway, the installation stays on the last
verified state — never half-installed.

## Uninstall

`DELETE /installations/{id}` marks `UNINSTALLED` and soft-deletes only the
rows this installation created (matched by install provenance).

## Background processing

Long-running work (validation, security scans, installs, updates,
rollbacks, export builds) can run on the existing worker infrastructure via
`apps/worker/src/worker/packages_worker.py` (`packages` queue, job types
`package.validate|security_scan|install|update|rollback|export_build`).
Handlers call the same services as the API; installs stay idempotent and
transactional. On startup the worker repairs interrupted installations
(`package.recover`): transitional states become retriable `FAILED` (never
half-installed), mid-rollback markers return to the last good version.
