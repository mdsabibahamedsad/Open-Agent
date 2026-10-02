# Evaluator Engine (MP20)

Central quality control: **Act → Observe → Verify → Evaluate → Correct →
Re-verify → Complete.** Never Act → Claim success → Done.

## Pipeline

```text
Agent / Workflow / Code / Browser / Tool
                    ↓
                Execution
                    ↓
              Evidence Capture (provenance + hash, immutable)
                    ↓
                Evaluator
                    ↓
          ┌─────────┼─────────┐
          ↓         ↓         ↓
       PASS      FAIL      UNCERTAIN
          ↓         ↓         ↓
      Complete   Correct    Escalate (human via MP19)
```

## Core rule

The agent's statement `"I succeeded"` is never proof. Success is verified
with observable evidence; deterministic checks dominate scores.

## Module map (`apps/api/src/openagent/evaluator/`)

| Module | Responsibility |
|---|---|
| `types.py` | EvaluationType (16+registry), lifecycle + transitions, decisions, evidence types/trust, failure classes, strategies, budgets |
| `criteria.py` | Declarative criteria parsing, versioned rubric library |
| `evidence.py` | Tamper-resistant collector (provenance + SHA-256, redacted) |
| `deterministic.py` | Pure verifiers: HTTP, JSON-schema, files, tests, workflow nodes, browser, git, side effects, secrets, markers |
| `llm.py` | Provider-neutral LLM judge via Model Router (strict JSON, framed untrusted content, separation) |
| `scoring.py` | Normalization, consensus, policy-driven decisions |
| `engine.py` | `EvaluatorEngine`: create → evidence → verify → vote → finalize |
| `correction.py` | `SelfCorrectionEngine`: classify → plan → bounded retry → re-evaluate |
| `gates.py` | Built-in + org quality gates |
| `benchmarks.py` | Benchmark runs + regression detection |
| `integrations.py` | Agent/workflow/tool/MCP/browser/code/sandbox/multi-agent/memory/human hooks |
| `metrics.py`, `config.py` | Counters, production-safe settings |

## Evaluation types

`TASK_SUCCESS OUTPUT_QUALITY FACTUALITY COMPLETENESS CORRECTNESS
POLICY_COMPLIANCE TOOL_RESULT WORKFLOW_RESULT CODE_QUALITY TEST_RESULT
BROWSER_RESULT STRUCTURED_OUTPUT FORMAT_COMPLIANCE GOAL_COMPLETION SAFETY
REGRESSION` (+ `CUSTOM` + org registry).

## Decisions

`PASS FAIL RETRY CORRECT ESCALATE REQUEST_HUMAN STOP`. PASS requires
score ≥ threshold AND required checks green AND no safety hit.
Disagreement default: `CONSERVATIVE_FAIL` (configurable to `HUMAN_REVIEW`,
`SECOND_REVIEW`, `MORE_EVIDENCE`).
