# Approval System — Security Model (MP19)

## Threat model

| Threat | Mitigation |
|---|---|
| Model self-approval | `requester_id != approver_id` enforced server-side; service accounts blocked from approving |
| Client forges `approved=true` | Booleans ignored; execution requires `ApprovalEngine.begin_execution` on a persisted APPROVED record |
| Approval replay | `approval_token` (server-generated, `secrets.token_urlsafe`), `use_count/max_uses`, `EXECUTING` lock via `SELECT … FOR UPDATE` |
| Action tampering (TOCTOU) | Canonical envelope hash compared at execution; mismatch → `INVALIDATED` + security event |
| Expired approval use | Checked at decision and execution; `expire_due` sweeper; `EXPIRED` terminal |
| Cross-tenant access (IDOR) | Path org vs auth-context org on every endpoint + engine; security event on attempt |
| Privilege escalation | RBAC `approval:*`; `required_role` per policy; platform privilege → `platform_owner` only |
| Policy downgrade | Max-restrictiveness merge; platform mandatory baseline always evaluated |
| Prompt injection ("user already approved") | Model text is untrusted data; only platform records prove approval |
| Memory-based authorization | Historical approvals are audit context, never grants |
| Webhook replay | Existing signed pipeline: HMAC-SHA256, timestamp header, retries, delivery logs |
| Race (double approve) | Row-level locking + idempotency keys; quorum counting for multi-approval |
| Secret leakage | `redact_params` before persistence; redaction in UI/API/logs; snapshot stores redacted params only |

## Approval lifecycle

`create_request → PENDING → (approve [quorum] | reject | cancel | expire | escalate)
→ APPROVED → begin_execution (hash+expiry+uses check) → EXECUTING
→ finish_execution → EXECUTED / EXECUTION_FAILED`.

## Expiration

`expires_at` is enforced lazily on every read/transition/execution path, so
correctness never depends on a sweeper. Operators should still schedule
`ApprovalEngine.expire_due()` (cron/beat) for hygiene, audit timeliness, and
the `approval.expired` events + metrics.

## Break-glass
Opt-in only (`ENABLE_BREAK_GLASS`), explicitly configured runbook, strongly
authenticated, time/scope-limited, multi-approved, highly audited. There is no
master-password bypass; the Master Account remains subject to platform policy.
