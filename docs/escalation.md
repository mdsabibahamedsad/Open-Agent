# Escalation

## Chain

Worker → Team Manager → Senior Manager → CEO → Human. Each hop records
history; `chain_level` tracks depth (configurable `max_depth`, default 4).

## Triggers

`blocked | permission_denied | budget_exceeded | deadline_risk |
repeated_failure | high_risk_action | ambiguous_requirement |
conflicting_outputs | missing_capability`.

## Severity

`info | warning | high | critical`. Severity never auto-equals danger —
policy defines meaning. Critical + human hook routes to human approval.

## Policy

`EscalationPolicy`: triggers, target, timeout, severity, retry policy,
human-approval hook. Higher-risk children escalate instead of silently
elevating privileges.

## Human hook (MP19 boundary)

`ApprovalRequiredError`, `ApprovalRequestHook`, `ApprovalPolicy` are the
integration surface. Critical escalations create `Approval` rows
(`AGENT_ACTION`) today; the full approval UI arrives in MP19.

## States

`open → acknowledged → in_progress → resolved → closed`, with `escalated`
for chain movement. All transitions validated and audited.
