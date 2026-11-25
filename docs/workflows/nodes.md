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

Regenerated from `apps/api/src/openagent/registry/node-registry.json` (`registry_version 1.0`) by `scripts/generate_node_docs.py`.

| Type | Category | Ports | Required config |
|---|---|---|---|
| `agent` | Agents | in → out | `agent_id` |
| `browser_agent` | Agents | in → out | `objective` |
| `code_agent` | Agents | in → out | `objective` + `repository_id` |
| `assert` | AI | in → out | `conditions` |
| `correct` | AI | in → out | — |
| `evaluate` | AI | in → out | — |
| `prompt` | AI | in → out | `model` + `prompt` |
| `quality_gate` | AI | in → out | — |
| `retry` | AI | in → out | `max_attempts` |
| `verify` | AI | in → out | `checks` |
| `condition` | Logic | in → true/false | `expression` |
| `loop` | Logic | in → out | `items` |
| `merge` | Logic | in → out | — |
| `split_in_batches` | Logic | in → out | — |
| `stop_and_error` | Logic | in → out | `message` |
| `switch` | Logic | in → out | `routes` |
| `aggregate` | Data | in → out | — |
| `code` | Data | in → out | `code` |
| `compare_datasets` | Data | in → same/different/only_in_a/only_in_b | — |
| `compression` | Data | in → out | `action` |
| `convert_to_file` | Data | in → out | — |
| `edit_fields` | Data | in → out | — |
| `extract_from_file` | Data | in → out | — |
| `filter` | Data | in → out | `items` + `predicate` |
| `html` | Data | in → out | `action` |
| `limit` | Data | in → out | — |
| `map` | Data | in → out | `items` + `expression` |
| `read_binary_file` | Data | in → out | `path` |
| `remove_duplicates` | Data | in → out | — |
| `set` | Data | in → out | `values` |
| `sort` | Data | in → out | — |
| `split_out` | Data | in → out | `field` |
| `transform` | Data | in → out | `mapping` |
| `write_binary_file` | Data | in → out | `path` |
| `xml` | Data | in → out | `action` |
| `browser_action` | Tools | in → out | `action_type` |
| `browser_extract` | Tools | in → out | `selector` |
| `code_lint` | Tools | in → out | `command` |
| `code_patch` | Tools | in → out | `task_id` + `diff` |
| `code_read` | Tools | in → out | `path` |
| `code_review` | Tools | in → out | — |
| `code_search` | Tools | in → out | `query` |
| `code_test` | Tools | in → out | `command` |
| `connector_action` | Tools | in → out | `action_id` |
| `connector_resource` | Tools | in → out | `kind` |
| `connector_search` | Tools | in → out | `query` |
| `connector_trigger` | Tools | → out | `trigger_id` |
| `create_pr` | Tools | in → out | `task_id` + `title` |
| `git_commit` | Tools | in → out | `task_id` + `message` |
| `tool` | Tools | in → out | `tool_id` |
| `respond_to_webhook` | HTTP | in → out | — |
| `webhook` | HTTP | in → out | `url` |
| `approval` | Human | in → out | `approvers` |
| `crypto` | Utilities | in → out | `action` |
| `datetime` | Utilities | in → out | `action` |
| `delay` | Utilities | in → out | `duration_seconds` |
| `no_op` | Utilities | in → out | — |
| `variable` | Utilities | in → out | `mode` + `name` |
| `subworkflow` | Advanced | in → out | `workflow_id` |

### Triggers (6)

| Trigger | Ports | Required config |
|---|---|---|
| `chat` | → out | — |
| `event` | → out | `event` |
| `execute_workflow` | → out | — |
| `manual` | → out | — |
| `schedule` | → out | `cron` |
| `webhook` | → out | `path` |

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
