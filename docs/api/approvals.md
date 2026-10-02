# Approvals API (MP19)

Base: `/api/v1/organizations/{organization_id}`. Auth: session cookie +
`X-Organization-ID`. Tenant isolation + RBAC on every route.

## Approvals

```http
GET    /approvals?status=PENDING&risk_level=HIGH&limit=50&offset=0
POST   /approvals                       # approval:create (usually the guard creates these)
GET    /approvals/taxonomy
POST   /approvals/simulate              # policy simulator, never executes
GET    /approvals/:id                   # detail + audit_timeline
POST   /approvals/:id/approve           # approval:approve, idempotency_key supported
POST   /approvals/:id/reject
POST   /approvals/:id/cancel
POST   /approvals/:id/escalate
GET    /approvals/:id/history
```

## Policies & delegation

```http
GET    /approval-policies
POST   /approval-policies               # approval:admin, declarative rules only
PATCH  /approval-policies/:id           # versioned
DELETE /approval-policies/:id
POST   /approval-delegations            # approval:admin, scoped + expiring
```

## Executing with an approval

Pass `approval_id` to the guarded operation; the server verifies hash, expiry,
and single-use before running:

- `POST …/tools/execute` → `{ tool_id, input, approval_id? }` (`WAITING` + `approval_id` when gated)
- `POST /api/v1/browser/tasks/:id/actions` → `{ action_type, page_id, input, approval_id? }`
- `POST /api/v1/sandboxes/:id/execute` → `{ …, approval_id? }`
- `POST /api/v1/code/tasks/:id/patch|push` → `{ …, approval_id? }`
- `POST …/workflows/:wid/executions/:eid/resume` → `{ approval_id }` (required)

Legacy `approved: true` booleans are NOT proof of approval and no longer execute
gated actions.

## Webhooks

Subscribe to `approval.created|approved|rejected|expired|escalated|executed`
via the existing signed webhook pipeline (HMAC-SHA256 + timestamp + retries).
