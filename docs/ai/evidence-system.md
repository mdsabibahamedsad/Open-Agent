# Evidence System (MP20)

## Types

`TOOL_RESULT HTTP_RESPONSE DATABASE_STATE FILE_STATE GIT_STATE TEST_RESULT
BROWSER_STATE SCREENSHOT_REFERENCE DOM_STATE WORKFLOW_EVENT AGENT_OUTPUT
USER_FEEDBACK APPROVAL_EVENT MODEL_RESPONSE STRUCTURED_OUTPUT METRIC LOG`.

## Provenance

Every record: source, source_type, source_id, timestamp, execution/tool/
agent/org ids, content hash. Trust is classified server-side
(`classify_trust`); agents cannot self-label output as verified.

## Rules

- Secrets redacted before storage (canonical approvals redaction).
- Records immutable after capture; tampering fails the evaluation safely.
- Terminal evaluations reject new evidence.
- Screenshots store references, never raw blobs, in evidence rows.
- Current execution evidence takes precedence over memory, always.

## LLM-judge input

Evidence is digested trust-labeled, redacted, truncated, and framed as
`<untrusted-evidence>` data. Page/tool/agent content can never override
evaluator instructions.

## Evaluator outputs

Strict schema only: `{decision, score, confidence, reason_codes}`.
Malformed output → rejected (UNCERTAIN path), never guessed. No
chain-of-thought is requested, stored, or exposed.
