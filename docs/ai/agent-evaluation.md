# Agent, Workflow & Model Evaluation (MP20)

## Agents

`POST /agents/:id/runs/:run_id/evaluate` verifies finished runs from stored
steps/output: output is MODEL_GENERATED evidence, tool results are
TOOL_VERIFIED. Organizations track per-agent accuracy, completion, tool-use
correctness, policy compliance, cost, latency, reliability, recovery via
`/quality/overview` + filtered evaluation lists. Scores are contextual,
never absolute truth.

## Workflows

`POST /workflows/:id/executions/:eid/verify` checks required nodes from
execution metadata. Workflow nodes `verify/evaluate/assert/quality_gate/
retry/correct` (plus existing `approval` for human review) compose
Verify → Gate → PASS/FAIL→correct/UNCERTAIN→human flows in the builder.
Metrics: success/failure/retry rates, duration, tool failures, human
interventions, quality, cost.

## Models

LLM votes record `model_version` + usage. Compare models by task quality,
latency, cost, failure and verification-success rates within an evaluation
dataset — never global rankings. Evaluator routing respects platform/org
policy, cost caps, availability, privacy, and local-only requirements
(`fast / reasoning / local / high-quality` profiles via Model Router).

## Multi-agent

`POST /orchestrations/:run/tasks/:task/review` returns accept / reject /
reassign / escalate from the task evaluation. Managers verify workers;
handoff packs carry task, requirements, evidence, failures, and eval
results — no hidden chain-of-thought.

## Memory

`memory_learning_payload` stores redacted learnings (strategies, failure
patterns, preferences) linked to evaluations. Memory never overrides
current evidence and never holds secrets.
