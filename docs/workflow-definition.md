# Workflow Definition Contract (v1)

Single source of truth: backend `openagent.services.workflow_definition`
(pure validator) and frontend `src/features/workflows/` (`types.ts`,
`schema.ts`, `validate.ts`). Both implement identical rules; the backend is
authoritative at publish time.

## Shape

```json
{
  "schema_version": "1.0",
  "triggers": [
    { "id": "trg_1", "type": "manual|webhook|schedule|event",
      "name": "Run manually", "config": {} }
  ],
  "nodes": [
    { "id": "n_1", "type": "agent|condition|loop|transform|approval|webhook|tool|delay",
      "name": "Triage", "position": { "x": 120, "y": 80 },
      "config": { "agent_id": "..." },
      "retry_policy": { "max_attempts": 2 },
      "timeout_seconds": 300 }
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

Notes:

- `position` is a canvas-only layout hint and is ignored by validation.
- Trigger `position` is likewise layout-only.
- `condition.label` on canvas edges mirrors the output port (`true`/`false` for
  condition nodes); `condition.when` gates branch execution semantics.

## Node reference

| Type | Required config | Notes |
|---|---|---|
| `agent` | `agent_id` or `agent_name` | Optional `task`, `max_steps` |
| `condition` | `expression` | Two outputs: `true` / `false` |
| `loop` | `items`, `max_iterations` 1..10000 | Iterates a collection expression |
| `transform` | `mapping` or `expression` | Pure data mapping, no model call |
| `approval` | non-empty `approvers` list | Terminal: pauses for human sign-off |
| `webhook` | `url`, valid `method` | Outbound HTTP call |
| `tool` | `tool_id` or `tool_name` | Registered tool invocation |
| `delay` | positive `duration_seconds` | Wait step |

Trigger requirements: `webhook` needs `config.path`, `schedule` needs
`config.cron`, `event` needs `config.event`.

## Graph rules (errors)

`NO_TRIGGER` · `DUPLICATE_ID` (triggers+nodes share a namespace) ·
`UNKNOWN_TRIGGER_TYPE` / `UNKNOWN_NODE_TYPE` · `NODE_CONFIG_REQUIRED` ·
`SELF_LOOP` · `EDGE_INTO_TRIGGER` · `UNKNOWN_EDGE_SOURCE/TARGET` ·
`DUPLICATE_EDGE` · `CYCLE_DETECTED` (v1 is DAG-only) ·
`UNREACHABLE_NODE` (every node must trace back to a trigger) ·
variable name/type/duplication rules · `settings.max_concurrency` 1..32.

Warnings (advisory): `TRIGGER_WITHOUT_EDGES`, `NODE_WITHOUT_OUTGOING`.

## Lifecycle

Drafts may be saved while invalid. `POST .../publish` validates strictly and
returns 422 with machine-readable `details` (`code`, `message`, `field`) on
failure. Every definition change snapshots an immutable version (`v1`, `v2`,
…); versions are never mutated. Statuses: `draft ↔ active` only via
`/publish` and `/unpublish`; `→ archived` via PATCH; archived is read-only.

## Extending

1. Add the type + required config to **both** validators (backend service and
   `features/workflows/validate.ts` + `node-catalog.ts`).
2. Add the icon/label/ports/defaults to `node-catalog.ts`.
3. Bump `schema_version` only for breaking changes; keep old versions readable.
