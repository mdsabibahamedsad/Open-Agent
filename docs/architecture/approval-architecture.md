# Approval Architecture (MP19)

## Flow

```text
Agent / Workflow / Tool / Browser / Code / Sandbox / MCP / Orchestration
                    ↓
             Policy Engine (platform > org > team > agent > workflow > tool > request)
                    ↓
              Risk Engine (explainable 0–100 + reasons)
                    ↓
            Approval Decision (ALLOW | DENY | REQUIRE_APPROVAL | REQUIRE_MULTI_APPROVAL | REQUIRE_ESCALATION)
             ↙           ↘
        APPROVAL        NO APPROVAL
           ↓                 ↓
       Human Review      Execute
           ↓
      Approve / Reject (ApprovalEngine, server-side state machine)
           ↓
        Execute via existing runtime (hash-verified, single-use)
           ↓
        Audit (audit_logs + approval_events + security_events + event outbox)
```

## Invariants (enforced, tested)

1. No model can approve its own action (`requester != approver`, service identities blocked).
2. No client request can mark an approval approved (transitions only via `ApprovalEngine`).
3. No expired approval can execute (`expires_at` checked at decision AND execution).
4. No modified action can reuse an approval (canonical SHA-256 envelope hash).
5. No cross-tenant approval access (org check on every transition + security event).
6. No lower-level policy can weaken mandatory platform policy (max-restrictiveness wins).
7–9. Memory / conversation / tool output can never grant authorization (only persisted approvals).
10–13. MCP / Browser / Code / Sandbox funnel through the same gate.
14. Manager agents cannot fabricate approval (orchestrator `approved` sets must derive from records).
15. Master Account is not a bypass (platform_owner is a scoped role, still gated + audited).
16–20. Every approval auditable; high-risk defaults safe; sandbox controls never weakened;
    secrets never persisted/logged; approvals bound to deterministic snapshots.

## Key modules

- `apps/api/src/openagent/approvals/` — types, taxonomy, risk, policy, hashing,
  engine, guard, integrations, escalation, delegation, notifications, metrics, config.
- `apps/api/src/openagent/db/models/approval.py` — `approvals` + 8 satellite tables.
- `apps/api/src/openagent/api/v1/approvals.py` — REST: approvals, policies, delegations, simulate.
- Integrations: tool execute endpoint (central gate), agent loop (pure pre-gate +
  `WAITING` pause), workflow resume (approval-bound), browser/sandbox/code services
  (persisted-approval verification, `approved` booleans no longer proof), orchestration
  (parked approvals for gated tasks).

## States

`PENDING → APPROVED → EXECUTING → EXECUTED`, with `REJECTED / EXPIRED / CANCELLED /
EXECUTION_FAILED / INVALIDATED` side transitions. See `ALLOWED_TRANSITIONS`.
