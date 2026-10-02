# Dynamic Teams

## Lifecycle

`created → forming → active → winding_down → completed | cancelled`.
Teams are `persistent | temporary | orchestration_scoped | task_scoped`.
Completion requires `WINDING_DOWN` plus zero pending run tasks (artifact
collection first). History is never deleted.

## Formation

`form_team` performs greedy capability cover over discovered, available,
in-capacity agents — one agent per role, deterministic ordering, uncovered
roles reported honestly. Member budgets subdivide the parent allocation
(`split_budget` normalizes oversubscription); member deadlines stagger
inside the charter window (`allocate_deadlines` never extends the root).

## Charter

Objective, scope, responsibilities per role, communication rules, completion
criteria, deadline, budget (`team_charters`, 1:1 with the team).

## Membership

Agent, role, responsibilities, required (not granted) permissions,
task scope, status. Team membership grants no organization-wide access.
Size capped by the manager's `max_team_size`.

## Collaboration without ownership

`REQUEST_INFORMATION | SHARE_RESULT | REQUEST_REVIEW | REQUEST_ARTIFACT |
REQUEST_ANALYSIS` — collaboration never transfers ownership (use handoff).
Negotiation covers availability/effort/completion only; permission/scope/
budget terms are stripped and reject the bid. Acceptance creates commitments
with deadlines; progress reports are informational (0–1 clamped) and blocked
states (`MISSING_INPUT`, `MISSING_PERMISSION`, …) surface to managers.

## Communication

Routed through `CommunicationService`: channel authorization
(`direct | team | manager | escalation | broadcast`), rate limits, message
budgets (per task/agent, collaboration/handoff/delegation caps), sanitized
payloads, metadata-only audit with configurable retention.
