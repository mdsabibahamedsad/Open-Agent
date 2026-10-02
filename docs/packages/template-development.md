# Template Development

## Agent template

```json
{
  "kind": "AGENT",
  "slug": "research-manager",
  "name": "Research Manager",
  "payload": {
    "system_prompt": "Coordinate research workers and synthesize cited reports.",
    "model_preset": "BALANCED",
    "skills": ["web-research"],
    "tools": ["browser-search"],
    "memory": { "memory_mode": "team-shared", "retention": "project" },
    "capabilities": ["web.read"],
    "guardrails": { "max_steps": 25 },
    "evaluation": { "minimum_quality_score": 0.7 }
  }
}
```

Installing creates a real `agents` row (DRAFT) + `agent_versions` snapshot;
execution uses the Agent Runtime with the referenced model preset resolved
through the Model Router.

## Workflow template

Payload holds the workflow definition (`triggers`, `nodes`, `connections`,
`variables`, `agents`, `tools`, `approvals`, `outputs`) plus
`credential_reference` / `connection_reference` descriptors — never secret
values. Installing creates `workflows` + `workflow_versions` rows executed
by the existing Workflow Engine (including `approval` nodes for high-risk
steps).

## Workforce template

```json
{
  "kind": "WORKFORCE",
  "slug": "marketing-workforce",
  "name": "Marketing Workforce",
  "payload": {
    "manager": "marketing-manager",
    "workers": ["research", "content", "seo", "analytics"],
    "handoff_rules": ["research -> content", "content -> seo"],
    "budgets": { "max_cost_usd": 25 },
    "approval_rules": ["publish_content"],
    "evaluation_rules": { "minimum_quality_score": 0.75 }
  }
}
```

Workforces reuse Multi-Agent Orchestration and the manager layer — no
second orchestration engine. The installer materializes member agents
first, then records the team graph as installation resources (visualized
with the resource graph / Mermaid export).

## Referencing, not copying

Templates reference tools, connectors, models, memory and credentials by
stable IDs and version constraints. Required credentials/connectors/tools/
models/skills surface in the install preview; missing or policy-denied
items block installation with explicit errors.

## Quick start

```bash
python scripts/openagent_package.py init ./my-workforce --slug acme.marketing --type WORKFORCE
# edit my-workforce/manifest.json
python scripts/openagent_package.py validate ./my-workforce
python scripts/openagent_package.py build ./my-workforce -o ./dist
```

Or programmatically with `openagent.packages.builder.PackageDefinition`.
