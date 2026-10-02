# Multi-Agent Orchestration Architecture

> MP14 management layer: see `docs/manager-architecture.md`,
> `docs/delegation.md`, `docs/agent-handoff.md`, `docs/escalation.md`,
> `docs/dynamic-teams.md`, `docs/agent-contracts.md`.

## Overview

The Multi-Agent Orchestration Engine turns a high-level objective into coordinated
work across specialized agents. It is **infrastructure, not a demo**: plans,
tasks, assignments, messages, handoffs, budgets, and events are persisted and
executed by background workers.

```
User Objective
      ↓
Planner (rule-based default, agent-assisted hook)
      ↓
TaskPlan → Plan Validation (cycles, depth, risk, budgets, approvals)
      ↓
OrchestrationRun (CREATED → PLANNING → READY)
      ↓
Agent Discovery + Assignment (capabilities, policy, workload)
      ↓
Executor (parallel + sequential, leases, heartbeats, retries)
      ↓  ↙───────────────┴───────────────↘
Agent Runtime → Model Router → Tool Runtime → MCP / tools
      ↓
Result Aggregation + Conflict Handling
      ↓
Supervisor Review → Final Result (SUCCEEDED / PARTIALLY_SUCCEEDED / FAILED)
```

## Layering (no bypasses)

```
Multi-Agent Orchestrator
  ├── Agent Runtime (openagent/runtime/agent_core.py: AgentLoop)
  ├── Model Router (openagent/runtime/router.py: ModelRouter)
  ├── Tool Runtime (openagent/runtime/tools.py: ToolExecutionManager)
  ├── Workflow Runtime (runtime/executors: `orchestration` node)
  ├── Policy / RBAC (services/authorization.py + api/dependencies.py)
  ├── Memory Hook (workspace references; full memory in MP15)
  └── Observability (orchestration_events + core outbox + metrics)
```

Every agent invocation goes through `AgentLoop → Model Router → Tool Runtime →
MCP adapter`. The orchestrator never calls providers or tools directly.

## Lifecycle

### Orchestration runs

`CREATED → PLANNING → READY → RUNNING ⇄ WAITING / PAUSED → SUCCEEDED |
PARTIALLY_SUCCEEDED | FAILED | CANCELLED | TIMED_OUT`

Transitions are enforced by `orchestration/types.py: VALID_RUN_TRANSITIONS`.
Invalid transitions raise `INVALID_TRANSITION`.

### Tasks

`CREATED → READY → ASSIGNED → RUNNING ⇄ WAITING → SUCCEEDED | FAILED |
SKIPPED | CANCELLED | TIMED_OUT` (plus `PAUSED`).

A task becomes `READY` only when its dependency policy is satisfied:

- `ALL_SUCCESS` — every dependency succeeded/skipped.
- `ANY_SUCCESS` / `ALLOW_PARTIAL` — at least one succeeded.
- `IGNORE_FAILURE` — all terminal, regardless of outcome.

### Agent participation

`CREATED → READY → STARTING → RUNNING ⇄ WAITING / HANDOFF / PAUSED →
COMPLETING → SUCCEEDED | FAILED | CANCELLED | TIMED_OUT | TERMINATED`

## Task model

Persisted as `orchestration_tasks` with:

- identity: `id`, `orchestration_run_id`, `external_task_id` (planner-visible),
  `parent_task_id`, `assigned_agent_id`, `agent_run_id`
- work: `title`, `description`, `instructions`, `input` (sanitized, never secrets)
- scheduling: `status`, `priority` (critical/high/normal/low), `dependencies`
  (edge table), `dependency_policy`, `required_capabilities`
- safety: `risk_level`, `required_permissions`, `requires_approval`
- resilience: `retry_count`, `max_retries`, `retry_strategy`, `timeout_seconds`,
  `depth`, leases (`lease_owner`, `lease_expires_at`, `last_heartbeat_at`)
- results: `output` (size-capped), `error`, attempts history preserved

## Agent relationships

Stored as data in `agent_relationships`, not Python conditionals:
`MANAGES | REPORTS_TO | COLLABORATES_WITH | CAN_DELEGATE_TO | CAN_REVIEW |
SPECIALIZES_IN`. Hierarchy informs delegation/visibility/reporting, but
authorization is still enforced independently per operation.

## Roles and capabilities

- Roles are extensible (`agent_relationships.role`, `AgentRoleName` enum for
  built-ins: ceo/manager/planner/researcher/developer/coder/.../custom).
- Capabilities are advertised rows (`agent_capabilities`: name, description,
  version, required_tools, required_permissions, risk_level, availability),
  e.g. `research.web`, `coding.python`, `testing.automation`.
- Assignment is deterministic and explainable: explicit assignment →
  capability match → availability/health → workload → cost hint. Reasons are
  recorded on the `TASK_ASSIGNED` event.

## Delegation and handoff

- `delegate_task(parent, task, target)` validates organization match,
  availability, budget, depth (`max_delegation_depth`, default 5), and risk
  non-downgrade. Self-delegation and cross-org delegation are denied.
- Handoff transfers structured state (`task, objective, completed_work,
  artifacts, relevant_context, constraints, warnings, expected_next_action`).
  `PRIVATE` context is never transferred; secret-looking keys are redacted.
- Internal messaging uses `AgentCommunicationAdapter` (protocol-neutral;
  `InMemoryCommunicationAdapter` ships; external A2A transports can implement
  the same interface later). Durable messages persist in `agent_messages`.

## Execution tree and concurrency

- The executor runs level-by-level: tasks whose dependencies are satisfied run
  concurrently under a semaphore (`max_parallel_agents`, per-org caps).
- Fairness hooks: per-org / per-run / global concurrency settings exist in
  `OrchestrationOrgSettings`; the worker queue is the shared Redis
  infrastructure (`orchestration` logical queue).
- Priority scheduling: critical → high → normal → low; lower priorities are
  never starved indefinitely because levels drain fully each pass.

## Budgets

Run-level `Budget` (`max_total_steps/tokens/cost/execution_time/tasks/agents/
delegation_depth/tool_calls/parallel_tasks`). Children receive bounded
sub-budgets (`BudgetState.child_budget`) that can never exceed remaining
parent budget. Every model call contributes usage; `BUDGET_WARNING` fires at
80%, overspend raises `BudgetExceeded` and pauses/fails the run honestly.

## Failure handling

- Retry strategies: `none | fixed | exponential_backoff | reassign | replan`
  with `max_retries` caps. Attempts are preserved in
  `orchestration_task_attempts` — history is never erased.
- Failure propagation is policy-driven via dependency policies + supervisor
  decisions (`retry | reassign | skip | fail_parent | escalate | pause`).
- Stalled agents: heartbeat + timeout detection (no chain-of-thought
  inspection). Loops: delegation-chain repetition + depth limits. Deadlocks:
  unknown deps and cycles rejected at plan time, re-checked at runtime.
- Cancellation propagates root → tasks → agent runs; completed work stays
  available. Pause persists state; resume continues from it.
- Crash recovery: task leases expire; the worker reclaims `RUNNING/WAITING`
  tasks with expired leases back to `READY` on startup.

## Security boundaries

- Tenant isolation on every query (`organization_id` + `get_by_id_with_org`).
- RBAC: `agent:read/create/run` permissions enforced on all endpoints.
- Prompt-injection framing: model-generated plans are untrusted data, always
  schema-validated before execution.
- No privilege escalation: child risk must not be lower than parent risk;
  worker agents cannot self-promote.
- Secret isolation: `sanitize_dict` redacts secret-looking keys; outputs are
  size-capped; credentials never flow through messages.
- Audit: delegation, handoff, reassignment, denials, cancellations, and
  high-risk executions append to `audit_logs`.
- Resource protection: configurable caps for agents, tasks, depth, message and
  artifact sizes, execution time, tokens, tool calls, cost.

## Trust model

Tool trust levels (`CORE | VERIFIED | ORGANIZATION | COMMUNITY | UNTRUSTED`)
influence policy but never override authorization.

## Observability

- `orchestration_events` rows (trace_id/span_id/parent_span_id) chain
  Orchestration → Task → AgentRun → ModelCall → ToolCall, mirrored to the
  core event outbox.
- Metrics: orchestrations/tasks/agent-runs/delegations/handoffs totals,
  durations, token usage, estimated cost.

## Configuration

Organization settings (`settings.orchestration`): max agents/tasks per run,
max delegation depth, max parallel agents, default timeout/budget, delegation
toggles, approval requirements, and feature flags
(`multi_agent_orchestration`, `agent_delegation`, `agent_handoff`,
`parallel_agents`, `agent_reassignment`, `orchestration_workspace`).
