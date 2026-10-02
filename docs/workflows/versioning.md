# Versioning

Versions are immutable snapshots (`v1`, `v2`, …) on `workflow_versions`.
The `workflows` row holds lifecycle status; the newest version row holds the
editable draft.

## Rules

- **Create** → status `draft`, version `v1`.
- **PATCH with a changed definition** → new draft version `vN+1`. The
  published version is never mutated.
- **Publish** (`POST …/publish`) → strict server validation (422 otherwise),
  latest version marked `published`, workflow `active`.
- **Unpublish** → `active` → `draft`.
- **Archive** → via PATCH (`draft|active → archived`); archived is read-only.
- **Restore** (`POST …/restore {version}`) → copies the snapshot into a
  **new** draft version. History is append-only; audit records
  `workflow.restored` with `restored_from`.
- **Delete** → soft delete; versions and executions preserved.

## Concurrency (§50)

`PATCH` accepts `expected_updated_at`. On mismatch the server answers 409
`STALE_UPDATE` with `current_updated_at`; the builder opens a dialog:
*Reload server version* (drops the local draft) or *Keep local draft*
(autosave preserved, next save overwrites deliberately). No realtime
collaboration — the version number + timestamp are the conflict signal.

## Offline & recovery (§51)

`navigator.onLine` drives the save-status pill. While offline, saves are
refused with a warning toast and edits accumulate in the debounced
`localStorage` draft; reconnecting re-enables Save, which sends the full
definition (idempotent per version snapshot, never auto-overwriting newer
server state thanks to `expected_updated_at`).

## Audit (§52)

Best-effort `audit_logs` rows (never definitions/secrets):
`workflow.created|updated|version_created|restored|imported|exported|
published|unpublished|deleted` (+ duplicate via `created` with
`duplicated_from`). Audit failures never break the primary operation.
