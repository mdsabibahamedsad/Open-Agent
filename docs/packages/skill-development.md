# Skill Development

A skill is a reusable capability package attachable to agents, agent teams,
workflows, workforces, tasks and manager agents.

## Definition

```json
{
  "kind": "SKILL",
  "slug": "web-research",
  "name": "Web Research",
  "payload": {
    "instructions": "Search authoritative sources, cross-check two independent sources, record citations.",
    "input_schema": { "type": "object", "properties": { "topic": { "type": "string" } } },
    "output_schema": { "type": "object", "properties": { "findings": { "type": "array" } } },
    "required_tools": ["browser-search"],
    "required_connectors": [],
    "model_requirements": { "reasoning_required": false },
    "memory_requirements": { "memory_mode": "project" },
    "security_requirements": { "sandbox": "required" },
    "evaluation_criteria": ["factuality", "citation requirement"]
  }
}
```

Skills are versioned immutably (`skill_versions`) and published explicitly.
Instructions are scanned for prompt-injection, policy-override and
exfiltration patterns — violations block publication.

## Composition

```text
Research Skill + SEO Skill + Content Writing Skill + Fact Checking Skill
= SEO Content Workforce
```

Composition is dependency resolution over skill requirements: incompatible
tools/models, conflicting permissions or runtime requirements, and circular
references are detected before install/attach (`DEPENDENCY_CONFLICT`,
`CIRCULAR_DEPENDENCY`).

## Attaching

`POST /skills/{id}/attach` with `{target_type: agent|workflow, target_id}`:

1. Skill must be PUBLISHED.
2. Required tools checked against ToolPolicy denials (fail closed).
3. A new **draft** version of the target is created with the skill appended —
   the original is never mutated.

Skills never bypass Tool Runtime, RBAC, Human Approval, Sandbox, connector
policies, agent policies or organization policies.

## CLI

```bash
python scripts/openagent_package.py skill-init ./my-skill --slug acme.seo-research
```
