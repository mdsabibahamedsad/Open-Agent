# Preset Development

Presets are reusable, versioned configuration hints. They declare intent;
routers and engines enforce policy at use time.

## Model presets

Examples: `fast`, `balanced`, `reasoning`, `coding`, `local`, `low-cost`, `high-quality`.

```json
{
  "kind": "MODEL_PRESET",
  "slug": "balanced",
  "payload": {
    "strategy": "balanced",
    "required_capabilities": ["chat"],
    "minimum_context_window": 32000,
    "reasoning_required": false,
    "budget": { "max_cost_usd_per_task": 0.5 },
    "fallback": "fast"
  }
}
```

Model presets reference the Model Router by capability/strategy — never by
provider secret or direct model handle. Unknown keys and embedded secrets
are rejected.

## Agent presets

Starter shapes (`research-agent`, `coding-agent`, `support-agent`, …): system
prompt skeleton, default skills, tool allow-lists, guardrail defaults.

## Workflow presets

Recipes such as `lead → research → score → CRM` or
`GitHub issue → coding agent → sandbox → tests → PR`, bundled with their
agents, skills, connectors, tools and configuration schema.

## Memory presets

Examples: `minimal`, `conversation`, `long-term-assistant`, `research-memory`,
`team-shared`.

```json
{
  "kind": "MEMORY_PRESET",
  "slug": "team-shared",
  "payload": {
    "memory_mode": "team-shared",
    "memory_scopes": ["team"],
    "retention": "project",
    "retrieval_policy": "recent-first",
    "write_policy": "agent-write"
  }
}
```

Memory presets resolve through the Memory Engine and can never override
organization memory policies (most-restrictive wins).
