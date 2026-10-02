# Import / Export

## Envelope (§28)

```json
{
  "format": "openagent-workflow",
  "schemaVersion": "1.0",
  "exported_at": "2026-09-26T10:00:00+00:00",
  "workflow": {
    "name": "Support triage",
    "slug": "support-triage",
    "description": "…",
    "tags": ["support"],
    "definition": { "schema_version": "1.0", "triggers": [ … ] }
  }
}
```

- Export (`GET …/export?version=v3`, or the toolbar button) builds this
  envelope. It is safe by construction: definitions may only contain
  `credential_id` / `{{...}}` references — `SECRET_VALUE` blocks publish of
  anything else, so exports cannot leak secrets.
- Import accepts the envelope **or** a raw definition (backward compatible).
- `POST …/import` performs the same checks server-side and creates a draft.

## Import pipeline (both client and server)

1. **Size cap** — 1 MiB (`MAX_IMPORT_BYTES`); larger files rejected outright.
2. **Parse** — JSON errors reported with position, never thrown to the UI.
3. **Envelope detect** — `format: "openagent-workflow"` unwraps `workflow`;
   anything else is treated as a raw definition.
4. **Migration gate** — unknown `schemaVersion` rejected with the supported
   set (`migrateDefinitionSchema` / `migrate_definition` are the future
   1.1/2.0 hook).
5. **Shape check** — zod (`schema.ts`) with JSON-path error messages.
6. **Sanitize** — ids kept (namespaced per workflow, collisions impossible);
   nothing is executed; sensitive-marked fields are dropped on
   **copy/paste** (clipboard hygiene), references preserved on import.
7. **Graph validation** — runs in the editor (and at publish); imports land
   as drafts for review, never auto-published.

## Security notes (§41–42)

- Imported files are untrusted input: capped, schema-checked, version-gated.
- No `eval`/`new Function` anywhere in the authoring layer; expressions are
  strings until MP08.
- No `dangerouslySetInnerHTML`; node names/config render as text (SVG
  `<text>`), so malicious strings cannot inject markup.
- Prototype pollution: configs are plain JSON round-tripped through
  `JSON.parse`; the validator only reads known keys and never merges
  `__proto__` specially (assignment targets are fixed fields).
- IDOR: every workflow endpoint re-scopes by `organization_id` + membership;
  cross-org ids return 404, never data.
- Error messages echo ids/codes only — config values (potential secrets)
  are never included.
