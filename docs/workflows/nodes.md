# Node Registry & Catalog

`features/workflows/node-catalog.ts` is the central registry (§8). The canvas,
palette, inspector, and validator all read from it — adding a node never
requires touching the editor.

## Categories (§9)

`Triggers · Logic · Data · AI · Agents · Tools · HTTP · Integrations ·
Human · Utilities · Advanced`. The set is data, not code:
`definitionsByCategory()` orders known categories first, then any custom ones
alphabetically. `Integrations` is intentionally empty — the extension point.

## Node table (built-in, all `source: "builtin"`, `version: 1`)

| Type | Category | Ports | Required config |
|---|---|---|---|
| `agent` | Agents | in → out | `agent_id` or `agent_name` |
| `prompt` | AI | in → out | `prompt` + (`model` or `model_router_profile`) |
| `condition` | Logic | in → true/false | `expression` |
| `switch` | Logic | in → routes…+default | `routes: [{name, expression}]` |
| `merge` | Logic | in (fan-in) → out | — |
| `loop` | Logic | in → out | `items`, `max_iterations` 1..10000 |
| `set` | Data | in → out | non-empty `values` object |
| `transform` | Data | in → out | `mapping` or `expression` |
| `filter` | Data | in → out | `items` + `predicate` |
| `map` | Data | in → out | `items` + `expression` |
| `variable` | Utilities | in → out | `mode` set/get + `name` |
| `approval` | Human | in → out (terminal) | non-empty `approvers` |
| `webhook` | HTTP | in → out | `url`, valid `method` |
| `tool` | Tools | in → out | `tool_id` or `tool_name` |
| `delay` | Utilities | in → out | positive `duration_seconds` |
| `subworkflow` | Advanced | in → out | `workflow_id` (not executed yet) |
| `code_agent` | Agents | in → out | `objective` + (`repository_id` or `repository`); `max_steps` 1..200; optional `execution_policy`/`review_policy`/`approval_policy` objects |
| `code_search` | Tools | in → out | `query` + (`workspace_id` or `repository_id`) |
| `code_read` | Tools | in → out | `path` (+ `workspace_id`, `start`, `end`) |
| `code_patch` | Tools | in → out | `task_id` + `diff` (unified diff text) |
| `code_test` | Tools | in → out | `command` (+ `profile` TEST/LINT/TYPECHECK/BUILD/PACKAGE/MIGRATION) |
| `code_lint` | Tools | in → out | `command` (+ `profile`) |
| `code_review` | Tools | in → out | `task_id` or `diff` |
| `git_commit` | Tools | in → out | `task_id` + `message` |
| `create_pr` | Tools | in → out | `task_id` + `title` (+ `summary`, `open`) |

Triggers: `manual` (no config) · `webhook` (`path` + secret reference) ·
`schedule` (`cron`) · `event` (`event`).

## Connection model (§13–14)

- Every node has one input (single inbound edge), except `merge` (fan-in).
  Triggers are sources only (no inbound edges, ever).
- Outputs are port keys: `['out']`, `condition → ['true','false']`,
  `switch → [...routeNames, 'default']` (dynamic via `outputPortsFor`).
- Edge `{ id, from, to, label?, condition? }`: `label` selects the output
  port on multi-output sources; `condition.when` is execution semantics for
  MP08. Port mismatches are warnings (`INVALID_EDGE_PORT`), structural
  violations are errors.

## Registering a node (§45, §54)

```ts
import { registerNodeDefinition } from '@/features/workflows/node-catalog';

registerNodeDefinition({
  type: 'acme.pagerduty', version: 1,
  label: 'PagerDuty', description: '…', icon: Bell,
  category: 'Integrations', source: 'organization',
  outputs: ['out'], hasInput: true,
  defaultConfig: { credential_id: '' },
  configFields: [
    { key: 'credential_id', label: 'Credential', type: 'credential', required: true },
  ],
});
```

Duplicates (`type@version`) throw; `unregisterNodeDefinition` removes.
The backend validator must learn the new type before publish passes —
mirror the `NODE_TYPES` set and `_validate_node_config`.

## Config field types

`text · textarea · number · boolean · select · keyvalue · stringlist ·
expression ({{...}} + suggestions) · json (inline syntax check) ·
credential (reference-only input)`. Fields flagged `sensitive` are stripped
on copy/paste and never echoed in errors.
