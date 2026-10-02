# Security — Orchestration Addendum

## Tenant isolation

Every orchestration table carries `organization_id`. Service lookups use
`get_by_id_with_org`; discovery never returns another org's agents; the API
rejects path/header org mismatches with 403.

## Authorization

All orchestration endpoints require authentication + membership and enforce
RBAC (`agent:read` for reads, `agent:create` for planning/relationships,
`agent:run` for execution control). Delegation, handoff, reassignment, and
cancellation append to `audit_logs`.

## Prompt-injection resistance

Model-generated plans are untrusted data: parsed with `parse_plan_dict`,
validated with `validate_plan`, and framed with `frame_untrusted` before any
use in prompts.

## Privilege escalation

Child tasks cannot lower their parent's risk level (`RISK_DOWNGRADE`
rejected). Self-delegation and cross-org delegation are denied. Trust levels
inform policy but never override authorization.

## Budget isolation

Child budgets are fractions of remaining parent budget
(`BudgetState.child_budget`). Overspend raises `BudgetExceeded`.

## Secret isolation

`sanitize_dict` redacts secret-looking keys at every persistence boundary
(task input, outputs, messages, events, handoff packages). Bearer/API-key
patterns are redacted in free text. Never store credentials in task payloads.

## Output limits

Outputs capped at 256KB per task, messages at 256KB, artifacts at 50MB —
configurable per organization.
