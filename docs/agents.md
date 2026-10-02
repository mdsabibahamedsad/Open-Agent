# Agents

## Roles

Agent roles are extensible. Built-in names (`ceo`, `manager`, `planner`,
`researcher`, `developer`, `coder`, `designer`, `browser_agent`,
`data_analyst`, `marketing_agent`, `sales_agent`, `operations_agent`,
`qa_agent`, `security_agent`, `writer`, `reviewer`, `specialist`, `worker`,
`custom`) are suggestions stored in `agent_relationships.role` — custom roles
are first-class.

```python
# Example: advertise an extensible role via relationship metadata
{"role": "researcher", "description": "..."}
```

## Capabilities

Capabilities are advertised rows (`agent_capabilities`):

```
name                 # e.g. research.web, coding.python, testing.automation
description
version
required_tools
required_permissions
risk_level
availability
```

Register via `POST /organizations/{id}/orchestrations/capabilities`.
Matching is exact, case-insensitive, and deterministic.

## Hierarchy and relationships

Relationships (`agent_relationships`) support `manages`, `reports_to`,
`collaborates_with`, `can_delegate_to`, `can_review`, `specializes_in`.
Manage them via the orchestration relationships endpoints and inspect them in
`/agents/organization`.

## Detail view

The agent detail surfaces role, capabilities, current task, status, model,
tool usage, delegations, handoffs, cost, and execution time — only safe
execution metadata and outputs, never hidden chain-of-thought.
