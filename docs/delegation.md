# Delegation

## Formal delegation object

`delegation_requests`: source/target agent, task, contract, reason, required
capabilities, constraints, budget, deadline, policy, status
(`pending → accepted/rejected/expired/cancelled → completed`), decision
metadata, idempotency key. Every transition persisted; even rejections are
auditable.

## Lifecycle

Create → validate authority → find candidate → assign → accept → execute →
review → complete/revise/escalate. Acceptance creates an `AgentCommitment`
(task, agent, deadline, budget, expected output) and assigns the
orchestration task. Reassignment preserves attempt history.

## Policies

`explicit_only | manager_selected | capability_based | load_aware |
cost_aware | policy_based | hybrid`. All funnel through the deterministic
capability matcher; load/cost only order pre-filtered candidates. Agents and
tasks are selected — models remain the Model Router's job.

## Specialist selection

`discovery + availability + capacity + trust + scope + budget` with explicit
reasons. Dynamic delegation creates validated tasks (authorization, budget,
policy, capability, graph validation all still apply).

## Constraints

No delegation outside the organization, outside allowed team scope, beyond
authority, above budget, or above risk policy unless explicitly authorized.
Cross-team delegation defaults to DENY and is audited when enabled.

## Failure matrix (configurable)

1 failure → retry · 2 → reassign · 3 → escalate · policy violation →
immediate escalation. Worker replacement transfers only authorized context.
