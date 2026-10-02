# Self-Correction (MP20)

```text
Execution → Evaluation → Failure Analysis → Correction Plan →
Approval/Policy Check → Retry → Re-evaluate
```

## Failure classes

`TRANSIENT TOOL_ERROR NETWORK_ERROR AUTH_ERROR VALIDATION_ERROR MODEL_ERROR
CONTEXT_ERROR PLANNING_ERROR EXECUTION_ERROR DATA_ERROR POLICY_ERROR
SECURITY_ERROR REQUIREMENT_MISMATCH QUALITY_FAILURE UNKNOWN`.

## Strategies

`RETRY_SAME RETRY_WITH_BACKOFF RETRY_WITH_NEW_MODEL RETRY_WITH_NEW_TOOL
MODIFY_PARAMETERS REFINE_PROMPT EXPAND_CONTEXT REPLAN ROLLBACK
ASK_ANOTHER_AGENT REQUEST_HUMAN STOP`. There is intentionally no
disable-policy / bypass-approval / widen-sandbox strategy.

Strategy defaults per failure class (e.g. TRANSIENT→backoff,
AUTH/POLICY/SECURITY→STOP, REQUIREMENT_MISMATCH→human). Only
policy-allowed strategies run.

## Root-cause record

`SYMPTOM / CAUSE / EVIDENCE / CORRECTION / EXPECTED_RESULT`. Unknown causes
stay unknown — the engine never pretends certainty.

## Budgets (every loop bounded)

`max_attempts max_correction_cycles max_tokens max_cost max_time
max_tool_calls max_browser_actions max_sandbox_executions`
(defaults 3/3/50k/$5/30min/50/30/20). Exhaustion → STOP.

## Loop detection

Failure signatures (class + reason + target + strategy) stop repeats:
same signature 3× → STOP + security event. Oscillating solutions and
resource growth are cut by budgets.

## Security

Correction cannot bypass RBAC, approval, sandbox, network, MCP, or platform
policy; cannot expose secrets; cannot override human rejection. Strategies
needing a human (`REQUEST_HUMAN`, `ASK_ANOTHER_AGENT`) park for approval
before retrying. A failed action grants no new privilege.

## History

Terminal evaluations are immutable. Correction creates NEW linked
evaluations (`parent_evaluation_id`, `attempt_number`), so the timeline
Attempt 1 → Failed → Root cause → Plan → Attempt 2 → Passed stays auditable.
