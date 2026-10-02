# Orchestration Guide

## Concepts

- **Orchestration run**: a durable execution of one objective.
- **Task graph**: tasks + dependencies with policies (`all_success`,
  `any_success`, `allow_partial`, `ignore_failure`).
- **Assignment**: deterministic matching of tasks to agents.
- **Delegation**: one agent formally hands a task to another (depth-limited).
- **Handoff**: structured state transfer between agents (no private context).
- **Supervisor**: monitors, retries, reassigns, escalates, enforces budgets.

## Quick start (API)

```bash
# 1. Create a run (Idempotency-Key supported)
curl -X POST $API/api/v1/organizations/$ORG/orchestrations \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: proposal-001" \
  -d '{"objective": "Research the AI automation market and prepare a SaaS proposal."}'

# 2. Plan (explicit tasks, template, or rule-based default)
curl -X POST $API/api/v1/organizations/$ORG/orchestrations/$RUN/plan \
  -d '{"template": "research_team"}'

# 3. Start execution
curl -X POST $API/api/v1/organizations/$ORG/orchestrations/$RUN/start

# 4. Watch progress
curl $API/api/v1/organizations/$ORG/orchestrations/$RUN/tasks
curl $API/api/v1/organizations/$ORG/orchestrations/$RUN/events
```

## Planning

Plans can be supplied explicitly (`tasks: [{task_id, title, dependencies,
required_capabilities, ...}]`), generated from a built-in template
(`research_team`, `software_team`, `content_team`), or produced by the
rule-based planner. Agent-assisted planning (`plan_with_agent`) routes through
the Agent Runtime and is always validated before persistence.

Validation rejects: empty objectives, bad/duplicate task ids, unknown or
self dependencies, cycles, excessive depth/tasks, unknown agents, risk
downgrades, dangerous actions without `requires_approval`, bad timeouts or
retry counts.

## Execution semantics

- Independent tasks run concurrently (bounded by `max_parallel_agents`).
- Dependent tasks wait until their dependency policy is satisfied.
- Each task spawns an agent run via the Agent Runtime (`AgentLoop` +
  Model Router + Tool Runtime). Without provider credentials the task fails
  honestly with `MODEL_UNAVAILABLE` — output is never fabricated.
- Retries follow the task's `retry_strategy`; attempts are preserved.
- Conflicting results are represented as `Conflict` rows for reviewer
  resolution — no silent winner-picking.

## Budgets

Set per run or per organization. Children inherit bounded fractions. Track
`allocated / consumed / remaining` via the run payload and budget ledger.
Overspend pauses the run.

## Human approval

Tasks with `requires_approval: true` (or `HIGH`/`CRITICAL` risk when the org
requires it) emit approval-gated events. The full approval UI ships in
Master Prompt 19; the orchestration integration point (status `WAITING` +
approval hook) exists now.

## SDK

```python
client.orchestrations.create(...)   # TS SDK: client.orchestrations.create(...)
client.orchestrations.start(...)
client.orchestrations.pause(...)
client.orchestrations.resume(...)
client.orchestrations.cancel(...)
client.orchestrations.tasks(...)
```

## Workflow integration

Add an `orchestration` node with `{objective | template, budget, timeout_seconds}`.
The node creates a run, returns `WAITING` with the run id as resume token, and
resolves with the final result when the run terminates.

## Limits and fairness

Defaults: 200 tasks/run, 50 agents/run, depth 5, 10 parallel tasks. All
configurable per organization with RBAC-protected settings.
