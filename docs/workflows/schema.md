# Workflow Schema (contract v1)

Single source of truth: backend `openagent.services.workflow_definition`
and frontend `features/workflows/` (`types.ts`, `schema.ts`, `validate.ts`,
`expressions.ts`). Both implement identical rules; the backend is
authoritative at publish time.

## Document

```json
{
  "schema_version": "1.0",
  "triggers": [
    { "id": "trg_1", "type": "manual|webhook|schedule|event",
      "name": "Run manually", "config": {}, "position": { "x": 80, "y": 80 } }
  ],
  "nodes": [
    { "id": "n_1",
      "type": "agent|prompt|condition|switch|merge|loop|set|transform|filter|map|variable|approval|webhook|tool|delay|subworkflow",
      "type_version": 1,
      "name": "Triage",
      "position": { "x": 120, "y": 80 },
      "config": { "agent_id": "..." },
      "retry_policy": { "max_attempts": 2 },
      "timeout_seconds": 300,
      "approval_required": false,
      "disabled": false,
      "notes": "Why this step exists",
      "group_id": "g_1" }
  ],
  "edges": [
    { "id": "e_1", "from": "trg_1", "to": "n_1",
      "label": "true", "condition": { "when": "always|success|failure", "expression": "..." } }
  ],
  "variables": [
    { "name": "ticket_id", "type": "string|number|boolean|json",
      "required": true, "description": "..." }
  ],
  "settings": { "timezone": "UTC", "max_concurrency": 1 }
}
```

- `position` is a canvas-only layout hint, ignored by validation.
- `disabled` nodes are excluded from config/reachability validation and from
  future execution. Ids and types must still be sane.
- `notes` / `group_id` are metadata (grouping UI ships later).
- `type_version` pins the node-definition version (migration foundation).
- Edge `label` doubles as the output-port key for multi-output nodes
  (`true`/`false`, switch route names).

## Trigger requirements

`webhook` → `config.path`; `schedule` → `config.cron`; `event` →
`config.event`. Webhook `secret` must be a `credential_id`/`{{...}}`
reference — literals are rejected (`SECRET_VALUE`).

## Graph rules

Errors: `NO_TRIGGER` · `DUPLICATE_ID` (triggers+nodes share a namespace) ·
`UNKNOWN_*` · `NODE_CONFIG_REQUIRED` · `SELF_LOOP` · `EDGE_INTO_TRIGGER` ·
`DUPLICATE_EDGE` · `CYCLE_DETECTED` (DAG-only v1) · `UNREACHABLE_NODE` ·
`MULTIPLE_INBOUND_EDGES` (except `merge` fan-in) · `SECRET_VALUE` ·
variable/type/position/timeout/retry rules.

Warnings (advisory): `TRIGGER_WITHOUT_EDGES` · `NODE_WITHOUT_OUTGOING` ·
`INVALID_EDGE_PORT` · `UNKNOWN_*_REFERENCE` · `UNBALANCED_EXPRESSION` ·
`UNUSED_VARIABLE`.

Every issue carries `severity` (`error`|`warning`), `code`, `message`,
plus `node_id` / `field` / `edge_id` locators.

## Schema versioning (§44)

`schema_version` is gated by `migrate_definition()` (backend) and
`migrateDefinitionSchema()` (frontend). Only `1.0` exists: unknown versions
are rejected with a clear error. Future 1.1/2.0 migrations plug into those
two functions — no other code changes needed.

## Extending

1. Add the type + required config to **both** validators.
2. Add icon/label/ports/defaults/category to the registry
   (`node-catalog.ts`) — the canvas renders any registered type generically.
3. Bump `schema_version` only for breaking changes; keep old readers working.
