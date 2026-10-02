# Human-in-the-Loop (MP19)

## Generalized pause

`WAITING_FOR_HUMAN` reasons: `APPROVAL_REQUIRED, CAPTCHA, MISSING_INFORMATION,
AMBIGUOUS_ACTION, SECURITY_REVIEW, MANUAL_TAKEOVER`. Shared by Agent Runtime
(`AgentRunStatus.WAITING` / `WAITING_FOR_APPROVAL` loop state), Workflow Engine
(`WAITING` + approval-bound `/resume`), Browser (`WAITING_FOR_HUMAN`, never
auto-solves CAPTCHAs), Code tasks (`WAITING_FOR_APPROVAL`), Sandbox executions
(`WAITING`), and Orchestration (`WAITING` tasks + parked approvals).

## Agent experience

Paused agents receive structured status only:

```json
{ "status": "WAITING_FOR_APPROVAL", "approval_id": "...", "message": "Human approval required" }
```

Approved: `{ "status": "APPROVED", "approval_id": "..." }`.
Rejected: `{ "status": "REJECTED", "reason": "..." }`.

No reviewer secrets, no internal policies, no credential data in model context.

## Approval-aware memory

Store approval EVENTS (`action X approved at time Y`), never standing
permissions. History informs audit/context, never auto-authorizes.

## Organization admin guide

1. Review `Approval Center → Pending`; check risk badge, impact, diff/preview, policy reason.
2. Dangerous actions need the explicit production acknowledgment + confirm dialog.
3. Use `simulate` before changing policies; prefer `REQUIRE_MULTI_APPROVAL` for finance/prod.
4. Delegation is scoped + expiring; review `approval-delegations` regularly.
5. Watch the Security Dashboard for self-approval / replay / cross-tenant attempts.
