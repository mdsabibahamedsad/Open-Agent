# Evaluation Architecture (MP20)

```text
                 ┌──────────────────┐
                 │   User / Goal    │
                 └────────┬─────────┘
                          ↓
                 ┌──────────────────┐
                 │ Agent / Workflow │
                 └────────┬─────────┘
                          ↓
                 ┌──────────────────┐
                 │     Execute      │
                 └────────┬─────────┘
                          ↓
                 ┌──────────────────┐
                 │    Evidence      │
                 └────────┬─────────┘
                          ↓
                 ┌──────────────────┐
                 │    Verify        │
                 └────────┬─────────┘
                          ↓
                 ┌──────────────────┐
                 │    Evaluate      │
                 └────────┬─────────┘
                          ↓
              ┌───────────┼───────────┐
              ↓           ↓           ↓
            PASS        FAIL       UNCERTAIN
              ↓           ↓           ↓
           Complete    Correct      Human /
                         ↓          Evidence
                       Retry
                         ↓
                     Re-evaluate
```

## Persistence

`evaluations` (+13 satellite tables: evidence, results, checks,
disagreements, rubrics + versions, plans, attempts, feedback, gates,
benchmarks, runs). Migration `019`. Tenant-isolated, indexed by
org/status/decision/type/task/parent.

## Versioning

Every evaluation stores evaluator/rubric/policy/model/verification
versions plus input/output hashes and criteria hash — reproducible
without promising LLM determinism.

## Security boundaries

Evaluator cannot authorize (no approval powers); correction cannot widen
policy; humans decide UNCERTAIN via MP19; history immutable; cross-tenant
forbidden; budgets enforced; evaluators isolated from evaluated agents
(separate models, framed inputs, strict outputs).
