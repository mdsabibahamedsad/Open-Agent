# Evaluations API (MP20)

Base: `/api/v1/organizations/{organization_id}`. Auth + `X-Organization-ID`.
RBAC: `evaluation:read/create/decide/admin`. Tenant isolation on every route.

## Evaluations

```http
GET    /evaluations?status=&decision=&evaluation_type=&agent_id=&workflow_id=&task_id=
POST   /evaluations                     # create (PENDING) with criteria + evidence
GET    /evaluations/:id                 # detail: evidence, checks, votes, plans, feedback
POST   /evaluations/:id/verify          # run deterministic checks (preferred)
POST   /evaluations/:id/vote            # record immutable evaluator vote
POST   /evaluations/:id/llm-vote        # server-side LLM judge (501 if no provider)
POST   /evaluations/:id/finalize        # consensus + policy decision (terminal)
POST   /evaluations/:id/retry           # NEW linked evaluation (history untouched)
POST   /evaluations/:id/correct         # build correction plan (bounded)
POST   /evaluations/:id/feedback        # append-only human feedback
GET    /evaluations/:id/evidence
GET    /evaluations/:id/history         # votes, checks, plans, attempts, feedback
```

## Corrections / rubrics / gates / benchmarks / quality

```http
GET    /correction-plans?status=
POST   /correction-plans/:id/attempt    # record outcome; server owns budget/loop verdicts
GET    /evaluation-rubrics  (+ built-ins)
POST   /evaluation-rubrics  |  PATCH /evaluation-rubrics/:id   # versioned
GET    /quality-gates       (+ built-ins)
POST   /quality-gates  |  PATCH /quality-gates/:id
POST   /quality-gates/:id/evaluate      # no side effects; MP19 approval checked read-only
GET    /benchmarks
POST   /benchmarks
POST   /benchmarks/:id/run              # aggregate item scores + regression
GET    /benchmarks/:id/runs
GET    /quality/overview                # dashboard aggregates
```

## Runtime verify hooks

```http
POST   /agents/:id/runs/:run_id/evaluate        # finished runs only
POST   /workflows/:wid/executions/:eid/verify
POST   /tools/verify                            # incl. mcp.* via independent state
POST   /code/tasks/:tid/verify                 # tests + secrets + diff
POST   /browser/tasks/:tid/verify              # URL/DOM/success/challenge
POST   /orchestrations/:run/tasks/:task/review  # accept/reject/reassign/escalate
```

There is no `force_success` / `disable_evaluation` / `bypass_quality_gate`
endpoint, and none must ever be added.
