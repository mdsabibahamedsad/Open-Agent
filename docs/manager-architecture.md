# Manager Architecture

## Concept

A manager is an Agent Runtime entity with an explicit `ManagerProfile`
— not a separate runtime and never an unrestricted admin. Authority is a
configurable allow-list (`ManagerAuthority`) plus scope boundaries; every
management operation still passes RBAC/policy/credential authorization.

```
USER → ROOT / CEO AGENT → Manager Decision Loop
                                        │
                    ┌───────────────────┼───────────────────┐
                    ▼                   ▼                   ▼
                MANAGER             MANAGER             MANAGER
                    │                   │                   │
                Workers             Workers             Workers
                    │                   │                   │
                    └───────────────────┼───────────────────┘
                                        ▼
                              RESULT REVIEW → AGGREGATION → FINAL RESULT
```

## ManagerProfile

`manager_profiles`: label (ceo/executive/manager/lead/custom — never
hard-coded), managed capabilities, delegation policy, review/escalation/team
policies, budget share, limits (workers, depth, direct reports, active tasks,
delegations, replans, team size), allowed actions, scope
(platform/organization/department/team), department/team binding.

## CEO / root agent

The root agent receives the objective, sets success criteria, chooses
strategy, plans, delegates to managers, monitors, handles escalation, and
validates the final result. `CEO ≠ Platform Owner`: the label grants no
platform administration privileges.

## Manager decision loop

Controlled state machine (no unrestricted recursive model calls):

```
OBSERVE → UNDERSTAND → PLAN → DELEGATE → MONITOR → REVIEW → CORRECT → COMPLETE
```

Driven by `ManagerDecisionLoop` with `ManagerLoopBudget` (max decisions,
replans, delegations, revisions, time, cost).Executed via `manager_tick`
(API or `manager_tick` worker job); each tick records a `DecisionRecord`
(operational rationale only — never chain-of-thought).

## Manager prompt architecture

`build_manager_prompt` assembles bounded context: system policy, role,
objective, team summary, active tasks (capped), contracts, constraints,
budget, execution metadata, referenced outputs, selected messages.
`compress_messages` reduces history to counts + head/tail. MP15 extends via
`ContextProvider`.

## Failure handling

- Manager crash → `recover_manager` suspends the profile and reattaches live
  child tasks to a replacement; history preserved.
- Root failure → orchestrator recovery policy (retry/replace/restore/pause/escalate).
- Loop protection: task ancestry, delegation graph, depth limits, repetition
  detection, budgets, timeouts.
