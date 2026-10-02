# OpenAgent API Documentation

## Overview

OpenAgent API is a RESTful API built with FastAPI for managing AI agents, workflows, and organizational resources.

## Base URL

```
http://localhost:8000/api/v1
```

## Authentication

All API endpoints (except health checks) require authentication via session cookie or API key.

### Session Authentication

```bash
# Login
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "password": "password123"}'

# The session cookie will be set automatically
```

### API Key Authentication

```bash
curl -H "Authorization: Bearer oa_abc123..." \
  http://localhost:8000/api/v1/auth/me
```

## Organization Context

Most endpoints require an organization context. Provide it via header:

```bash
curl -H "X-Organization-ID: <organization-uuid>" \
  http://localhost:8000/api/v1/agents
```

## API Endpoints

### Health Checks

#### GET /api/v1/health
Basic health check.

**Response:**
```json
{
  "status": "ok",
  "service": "openagent-api",
  "environment": "development"
}
```

#### GET /api/v1/health/ready
Readiness check with dependency verification.

**Response:**
```json
{
  "status": "ok",
  "service": "openagent-api",
  "checks": {
    "database": true,
    "redis": true
  }
}
```

### Authentication

#### POST /api/v1/auth/register
Register a new user.

**Request:**
```json
{
  "email": "user@example.com",
  "password": "securepassword123",
  "display_name": "John Doe"
}
```

**Response:**
```json
{
  "message": "Registration successful. Please check your email to verify your account.",
  "user_id": "uuid",
  "verification_sent": true
}
```

#### POST /api/v1/auth/login
Login user.

**Request:**
```json
{
  "email": "user@example.com",
  "password": "securepassword123",
  "remember_me": false
}
```

**Response:**
```json
{
  "user": {
    "id": "uuid",
    "email": "user@example.com",
    "display_name": "John Doe",
    "avatar_url": null,
    "status": "active",
    "email_verified": true,
    "is_superadmin": false
  },
  "session_token": "token",
  "expires_at": "2024-01-01T00:00:00Z"
}
```

#### POST /api/v1/auth/logout
Logout current session or all sessions.

**Request:**
```json
{
  "logout_all": false
}
```

#### POST /api/v1/auth/verify-email
Verify email address.

**Request:**
```json
{
  "token": "verification-token"
}
```

#### POST /api/v1/auth/forgot-password
Request password reset.

**Request:**
```json
{
  "email": "user@example.com"
}
```

#### POST /api/v1/auth/reset-password
Reset password with token.

**Request:**
```json
{
  "token": "reset-token",
  "password": "newsecurepassword123"
}
```

#### POST /api/v1/auth/change-password
Change password (authenticated).

**Request:**
```json
{
  "current_password": "oldpassword123",
  "new_password": "newsecurepassword123"
}
```

#### GET /api/v1/auth/me
Get current user info.

**Response:**
```json
{
  "id": "uuid",
  "email": "user@example.com",
  "display_name": "John Doe",
  "avatar_url": null,
  "status": "active",
  "email_verified": true,
  "is_superadmin": false,
  "is_platform_owner": false,
  "created_at": "2024-01-01T00:00:00Z"
}
```

#### GET /api/v1/auth/sessions
List active sessions.

#### DELETE /api/v1/auth/sessions/{session_id}
Revoke a specific session.

### Organizations

#### GET /api/v1/organizations
List organizations (paginated).

#### POST /api/v1/organizations
Create organization.

#### GET /api/v1/organizations/{id}
Get organization details.

#### PATCH /api/v1/organizations/{id}
Update organization.

#### DELETE /api/v1/organizations/{id}
Delete organization.

### Members

#### GET /api/v1/organizations/{organization_id}/members
List organization members.

#### POST /api/v1/organizations/{organization_id}/members
Invite member.

#### PATCH /api/v1/organizations/{organization_id}/members/{user_id}
Update member role.

#### DELETE /api/v1/organizations/{organization_id}/members/{user_id}
Remove member.

### Invitations

#### GET /api/v1/organizations/{organization_id}/invitations
List invitations.

#### POST /api/v1/organizations/{organization_id}/invitations
Create invitation.

#### POST /api/v1/invitations/accept
Accept invitation.

#### POST /api/v1/organizations/{organization_id}/invitations/{invitation_id}/revoke
Revoke invitation.

#### POST /api/v1/organizations/{organization_id}/invitations/{invitation_id}/resend
Resend invitation.

### Roles & Permissions

#### GET /api/v1/organizations/{organization_id}/rbac/permissions
List permissions.

#### GET /api/v1/organizations/{organization_id}/rbac/roles
List roles.

#### POST /api/v1/organizations/{organization_id}/rbac/roles
Create custom role.

#### GET /api/v1/organizations/{organization_id}/rbac/roles/{role_id}
Get role with permissions.

#### PATCH /api/v1/organizations/{organization_id}/rbac/roles/{role_id}
Update role.

#### DELETE /api/v1/organizations/{organization_id}/rbac/roles/{role_id}
Delete role.

#### GET /api/v1/organizations/{organization_id}/rbac/roles/{role_id}/permissions
Get role permissions.

#### PUT /api/v1/organizations/{organization_id}/rbac/roles/{role_id}/permissions
Set role permissions (replace all).

#### POST /api/v1/organizations/{organization_id}/rbac/roles/{role_id}/permissions/{permission_id}
Add permission to role.

#### DELETE /api/v1/organizations/{organization_id}/rbac/roles/{role_id}/permissions/{permission_id}
Remove permission from role.

### Teams

#### GET /api/v1/organizations/{organization_id}/teams
List teams.

#### POST /api/v1/organizations/{organization_id}/teams
Create team.

#### GET /api/v1/organizations/{organization_id}/teams/{team_id}
Get team details.

#### PATCH /api/v1/organizations/{organization_id}/teams/{team_id}
Update team.

#### DELETE /api/v1/organizations/{organization_id}/teams/{team_id}
Delete team.

#### GET /api/v1/organizations/{organization_id}/teams/{team_id}/members
List team members.

#### POST /api/v1/organizations/{organization_id}/teams/{team_id}/members
Add team member.

#### DELETE /api/v1/organizations/{organization_id}/teams/{team_id}/members/{user_id}
Remove team member.

#### PATCH /api/v1/organizations/{organization_id}/teams/{team_id}/members/{user_id}
Update team member role.

### Service Accounts

#### GET /api/v1/organizations/{organization_id}/service-accounts
List service accounts.

#### POST /api/v1/organizations/{organization_id}/service-accounts
Create service account (returns API key once).

#### GET /api/v1/organizations/{organization_id}/service-accounts/{account_id}
Get service account.

#### PATCH /api/v1/organizations/{organization_id}/service-accounts/{account_id}
Update service account.

#### DELETE /api/v1/organizations/{organization_id}/service-accounts/{account_id}
Delete service account.

#### POST /api/v1/organizations/{organization_id}/service-accounts/{account_id}/rotate-key
Rotate API key.

#### GET /api/v1/organizations/{organization_id}/service-accounts/{account_id}/permissions
Get service account permissions.

#### PUT /api/v1/organizations/{organization_id}/service-accounts/{account_id}/permissions
Set service account permissions.

### Workflows

Requires `workflow:*` permissions (`execution:read` for run history).
Publish/restore/version map to `workflow:update`; import maps to
`workflow:create`; export maps to `workflow:read` (no new permission strings
— server authorization stays authoritative). Definitions follow
`docs/workflows/schema.md`. Drafts may be saved while invalid; publish is
gated on validity.

#### POST /api/v1/organizations/{organization_id}/workflows/validate
Validate a definition without persisting. Returns `{ valid, errors[], warnings[] }`.

#### GET /api/v1/organizations/{organization_id}/workflows
List workflows (`search`, `status`, paginated).

#### POST /api/v1/organizations/{organization_id}/workflows
Create workflow as draft with initial `v1` version. Accepts `tags`.
409 on slug conflict.

#### GET /api/v1/organizations/{organization_id}/workflows/{workflow_id}
Detail with latest version, version count, and last execution.

#### PATCH /api/v1/organizations/{organization_id}/workflows/{workflow_id}
Update name/description/tags/guarded status. A changed definition snapshots
a new draft version (`vN+1`). Accepts `expected_updated_at` for optimistic
concurrency — 409 `STALE_UPDATE` on mismatch.

#### POST /api/v1/organizations/{organization_id}/workflows/{workflow_id}/duplicate
Duplicate (latest definition becomes `v1` of the copy).

#### DELETE /api/v1/organizations/{organization_id}/workflows/{workflow_id}
Soft-delete.

#### POST /api/v1/organizations/{organization_id}/workflows/{workflow_id}/publish
Validate strictly, then activate. 422 with field-level `details` when invalid.

#### POST /api/v1/organizations/{organization_id}/workflows/{workflow_id}/unpublish
Return an active workflow to draft.

#### GET /api/v1/organizations/{organization_id}/workflows/{workflow_id}/versions
List immutable versions (newest first).

#### GET /api/v1/organizations/{organization_id}/workflows/{workflow_id}/versions/{version}
Get one version snapshot (e.g. `v3`).

#### POST /api/v1/organizations/{organization_id}/workflows/{workflow_id}/restore
Restore a snapshot as a new draft version (`{version}`). History is
append-only; audit records `workflow.restored`.

#### POST /api/v1/organizations/{organization_id}/workflows/import
Import an export envelope or raw definition as a draft. Untrusted input:
structure-checked and schema-gated. 409 on slug conflict.

#### GET /api/v1/organizations/{organization_id}/workflows/{workflow_id}/export
Portable envelope (`format: "openagent-workflow"`). `?version=v3` selects a
snapshot. Safe by construction — definitions hold references only.

#### GET /api/v1/organizations/{organization_id}/workflows/{workflow_id}/executions
Read-only execution history (paginated).

#### POST /api/v1/organizations/{organization_id}/workflows/{workflow_id}/execute
501 `EXECUTION_ENGINE_NOT_IMPLEMENTED` until the execution engine ships.

### Orchestrations

Requires `agent:*` permissions (`agent:read` for reads, `agent:create` for
create/plan/relationships/capabilities, `agent:run` for
start/pause/resume/cancel/retry/reassign/delegate/handoff). Path
`organization_id` must match the authenticated org context (403 otherwise).
`Idempotency-Key` header (or `idempotency_key` field) dedupes run creation.

#### POST /api/v1/organizations/{organization_id}/orchestrations
Create a run (`objective`, optional `budget`, `root_agent_id`, `team_id`,
`template`, `metadata`). 201.

#### GET /api/v1/organizations/{organization_id}/orchestrations
List runs (`status`, paginated).

#### GET /api/v1/organizations/{organization_id}/orchestrations/{id}
Run detail with budget, usage, and final result.

#### POST /api/v1/organizations/{organization_id}/orchestrations/{id}/plan
Attach a task graph: explicit `tasks`, a `template` (`research_team`,
`software_team`, `content_team`), or the rule-based default. 422 on invalid
plans (cycles, unknown deps, risk downgrades, dangerous actions without
approval).

#### POST /api/v1/organizations/{organization_id}/orchestrations/{id}/start
Execute the DAG (parallel + sequential). Returns the terminal run state.

#### POST /api/v1/organizations/{organization_id}/orchestrations/{id}/pause
Pause (state persists; running tasks follow safe-stop policy).

#### POST /api/v1/organizations/{organization_id}/orchestrations/{id}/resume
Resume a paused run.

#### POST /api/v1/organizations/{organization_id}/orchestrations/{id}/cancel
Cancel a run and all pending tasks. Completed work remains available.

#### GET /api/v1/organizations/{organization_id}/orchestrations/{id}/tasks
List tasks with status, assignment, depth, and outputs.

#### GET /api/v1/organizations/{organization_id}/orchestrations/{id}/agents
Agent groups with assigned tasks and live status.

#### GET /api/v1/organizations/{organization_id}/orchestrations/{id}/messages
Durable agent message bus history.

#### GET /api/v1/organizations/{organization_id}/orchestrations/{id}/events
Structured execution events with trace ids.

#### POST /api/v1/organizations/{organization_id}/orchestrations/{id}/tasks/{task_id}/retry
Retry a failed/timed-out task (attempt history preserved).

#### POST /api/v1/organizations/{organization_id}/orchestrations/{id}/tasks/{task_id}/reassign
Reassign a task to another agent (`{agent_id}`).

#### POST /api/v1/organizations/{organization_id}/orchestrations/{id}/tasks/{task_id}/delegate
Formal delegation (`{parent_agent_id, target_agent_id}`), depth-limited.

#### POST /api/v1/organizations/{organization_id}/orchestrations/{id}/tasks/{task_id}/handoff
Structured handoff (private context never transferred; secrets redacted).

#### GET|POST /api/v1/organizations/{organization_id}/orchestrations/{id}/relationships
List/create agent relationships (`manages`, `can_delegate_to`, ...).

#### POST /api/v1/organizations/{organization_id}/orchestrations/capabilities
Advertise an agent capability.

### Management

Requires `agent:*` (`agent:read` for reads, `agent:create` for mutations,
`agent:run` for manager ticks). Base: `/api/v1/organizations/{id}/management`.

Managers: `POST/GET /managers`, `GET /managers/{agent_id}`,
`POST /managers/{agent_id}/tick?run_id=`, `GET /agents/{id}/reports`,
`GET /agents/{id}/team`, `GET /agents/{id}/capabilities`,
`PUT /agents/{id}/availability|/capacity`.
Contracts: `POST/GET /contracts`.
Delegations: `POST/GET /delegations`, `GET /delegations/{id}`,
`POST /delegations/{id}/accept|reject|expire|cancel|complete`.
Handoffs: `POST/GET /handoffs`, `GET /handoffs/{id}`,
`POST /handoffs/{id}/accept|reject|execute|complete|expire|cancel`.
Reviews: `POST/GET /reviews`.
Escalations: `POST/GET /escalations`, `GET /escalations/{id}`,
`POST /escalations/{id}/ack|acknowledge|progress|resolve|chain|close`.
Teams: `POST /teams`, `POST /teams/form`, `GET /teams`, `GET /teams/{id}`
(with members + charter), `POST /teams/{id}/form|activate|wind_down|complete|cancel`,
`POST /teams/{id}/members`, `DELETE /teams/{id}/members/{agent_id}`.
Departments: `POST/GET /departments`.
Collaboration: `POST /collaborations`, `POST /collaborations/{id}/accept|decline|complete|cancel`.
Progress: `POST /runs/{run_id}/tasks/{task_id}/progress`.
Task escalation: `POST /runs/{run_id}/tasks/{task_id}/escalate`.
Plans: `POST|GET /runs/{run_id}/plan-versions`. Decisions: `GET /runs/{run_id}/decisions`.
Console: `GET /console`. Org chart: `GET /organization/chart`.
Live stream: `GET /runs/{run_id}/stream` (SSE `text/event-stream`, cookie auth,
`Last-Event-ID` resume; ~5-minute windows, then reconnect).

### Repositories & Code Agent

Requires `code:read` for reads, `code:execute` for mutations. Host
filesystem paths are never returned; writes accept `credential_ref`
handles only — never raw secrets. Full guide: `docs/code-agent/overview.md`.

Repositories: `POST /api/v1/repositories` (`provider, name, full_name,
clone_url, default_branch?, visibility?, credential_ref?, provider_config?`),
`GET /api/v1/repositories`, `GET /api/v1/repositories/{id}`,
`POST /api/v1/repositories/{id}/connect`,
`POST /api/v1/repositories/{id}/sync`,
`DELETE /api/v1/repositories/{id}`,
`POST /api/v1/repositories/remote/list` (`provider, credential_ref`).

Workspaces: `POST /api/v1/code/workspaces` (`repository_id, task_id?,
branch?`), `GET /api/v1/code/workspaces?status=`,
`GET /api/v1/code/workspaces/{id}`,
`GET /api/v1/code/workspaces/{id}/status` (dirty flag, change count),
`POST /api/v1/code/workspaces/{id}/branches` (`name`),
`GET /api/v1/code/workspaces/{id}/files?prefix=`,
`GET /api/v1/code/workspaces/{id}/files/read?path=&start=&end=`,
`DELETE /api/v1/code/workspaces/{id}?force=`.

Coding tasks: `POST /api/v1/code/tasks` (`repository_id, objective,
branch?, max_steps?, max_duration_seconds?, risk_level?, budgets?`),
`GET /api/v1/code/tasks?status=&repository_id=`,
`GET /api/v1/code/tasks/{id}`,
`POST /api/v1/code/tasks/{id}/cancel|pause|resume`,
`GET /api/v1/code/tasks/{id}/plan|diff|events|artifacts`,
`POST /api/v1/code/tasks/{id}/patch` (`diff, approved?`),
`POST /api/v1/code/tasks/{id}/commit` (`message`),
`POST /api/v1/code/tasks/{id}/push` (`approved?, force?`),
`POST /api/v1/code/tasks/{id}/tests/plan`.

Search/review/execute/PR: `POST /api/v1/code/search` (`workspace_id,
query, mode=text|regex|symbol|references|semantic, symbol?, top_k?`),
`POST /api/v1/code/review` (`task_id` or `filename+content`),
`POST /api/v1/code/execute` (`workspace_id?, task_id?,
profile=TEST|LINT|TYPECHECK|BUILD|PACKAGE|MIGRATION|CUSTOM, command`),
`POST /api/v1/code/pr` (`task_id, title, summary?, open?` — opens but
never merges), `GET /api/v1/code/health`.

Task states: `QUEUED INITIALIZING ANALYZING PLANNING EDITING VALIDATING
TESTING REVIEWING WAITING_FOR_APPROVAL COMMITTING READY_FOR_PR SUCCEEDED
FAILED CANCELLED TIMED_OUT`. Risk: `LOW/MEDIUM/HIGH/CRITICAL` (push=HIGH,
force push=CRITICAL, denied by default).

### Sandboxes & Secure Execution

Requires `sandbox:read` for reads, `sandbox:execute` for mutations.
Container/host paths are never returned (storage refs instead);
credentials travel as `credential_refs` only. Full guide:
`docs/sandbox/overview.md`.

Sandboxes: `POST /api/v1/sandboxes` (`profile?, task_id?,
workspace_host_path?, workspace_mode?, image?, image_digest?,
ttl_seconds?, labels?`), `GET /api/v1/sandboxes?status=`,
`GET /api/v1/sandboxes/{id}`, `POST /api/v1/sandboxes/{id}/start|stop`,
`DELETE /api/v1/sandboxes/{id}`,
`GET /api/v1/sandboxes/security/check` (production posture diagnostic).

Execution: `POST /api/v1/sandboxes/{id}/execute` (`command` as argv list
or string, `workdir?, env?, credential_refs?, timeout_seconds?,
approved?, artifacts?, target_environment?`),
`GET /api/v1/sandboxes/{id}/executions`,
`GET /api/v1/sandboxes/{id}/executions/{execution_id}`,
`GET /api/v1/sandbox-executions/{execution_id}`,
`POST /api/v1/sandboxes/{id}/executions/{execution_id}/cancel`,
`GET /api/v1/sandboxes/{id}/events|artifacts`.

Leases (multi-agent sharing): `POST /api/v1/sandboxes/{id}/leases`
(`owner, ttl_seconds?, task_id?`),
`POST .../leases/{lease_id}/heartbeat|release`.

Profiles: `GET /api/v1/sandbox-profiles`, `POST /api/v1/sandbox-profiles`
(`config`), `DELETE /api/v1/sandbox-profiles/{name}`.

Execution states: `QUEUED RUNNING WAITING(=WAITING_FOR_APPROVAL)
SUCCEEDED FAILED TIMED_OUT CANCELLED KILLED RESOURCE_LIMIT POLICY_DENIED
SANDBOX_ERROR`. Profiles: `READ_ONLY TEST LINT TYPECHECK BUILD PACKAGE
DEVELOPMENT DATA_PROCESSING CUSTOM`; network `NO_NETWORK` by default.

### Invitations

#### GET /api/v1/organizations/{organization_id}/invitations
List invitations.

#### POST /api/v1/organizations/{organization_id}/invitations
Create invitation.

#### POST /api/v1/invitations/accept
Accept invitation.

#### POST /api/v1/organizations/{organization_id}/invitations/{invitation_id}/revoke
Revoke invitation.

#### POST /api/v1/organizations/{organization_id}/invitations/{invitation_id}/resend
Resend invitation.

#### POST /api/v1/organizations/{organization_id}/invitations/expire
Expire old invitations.

### Service Accounts

#### GET /api/v1/organizations/{organization_id}/service-accounts
List service accounts.

#### POST /api/v1/organizations/{organization_id}/service-accounts
Create service account.

#### GET /api/v1/organizations/{organization_id}/service-accounts/{account_id}
Get service account.

#### PATCH /api/v1/organizations/{organization_id}/service-accounts/{account_id}
Update service account.

#### DELETE /api/v1/organizations/{organization_id}/service-accounts/{account_id}
Delete service account.

#### POST /api/v1/organizations/{organization_id}/service-accounts/{account_id}/rotate-key
Rotate API key.

#### GET /api/v1/organizations/{organization_id}/service-accounts/{account_id}/permissions
Get permissions.

#### PUT /api/v1/organizations/{organization_id}/service-accounts/{account_id}/permissions
Set permissions.

### File Uploads

#### POST /api/v1/files/uploads
Initiate file upload.

#### POST /api/v1/files/uploads/{upload_id}/complete
Complete file upload.

#### GET /api/v1/files/uploads/{upload_id}
Get upload status.

#### POST /api/v1/files/uploads/{upload_id}/complete
Complete upload with file content.

#### GET /api/v1/files/uploads/{upload_id}/download
Download file.

#### GET /api/v1/files/uploads/{upload_id}/url
Get presigned download URL.

#### DELETE /api/v1/files/uploads/{upload_id}
Delete upload.

### Scheduled Jobs

#### GET /api/v1/organizations/{organization_id}/scheduler/jobs
List scheduled jobs.

#### POST /api/v1/organizations/{organization_id}/scheduler/jobs
Create scheduled job.

#### GET /api/v1/organizations/{organization_id}/scheduler/jobs/{job_id}
Get scheduled job.

#### PATCH /api/v1/organizations/{organization_id}/scheduler/jobs/{job_id}
Update scheduled job.

#### DELETE /api/v1/organizations/{organization_id}/scheduler/jobs/{job_id}
Delete scheduled job.

#### POST /api/v1/organizations/{organization_id}/scheduler/jobs/{job_id}/trigger
Manually trigger job.

### Webhooks

#### GET /api/v1/organizations/{organization_id}/webhooks
List webhooks.

#### POST /api/v1/organizations/{organization_id}/webhooks
Create webhook.

#### GET /api/v1/organizations/{organization_id}/webhooks/{webhook_id}
Get webhook.

#### PATCH /api/v1/organizations/{organization_id}/webhooks/{webhook_id}
Update webhook.

#### DELETE /api/v1/organizations/{organization_id}/webhooks/{webhook_id}
Delete webhook.

#### POST /api/v1/organizations/{organization_id}/webhooks/{webhook_id}/test
Test webhook.

### Integrations & Connectors

Full reference: `docs/api/integrations.md`.

#### GET /api/v1/organizations/{organization_id}/connectors
Connector catalog (definitions + status; `category`, `trust`, `search` filters).

#### GET /api/v1/organizations/{organization_id}/connectors/{id}
Connector detail (manifest, secrets stripped).

#### GET /api/v1/organizations/{organization_id}/connectors/{id}/actions
Actions with JSON schemas, risk levels, verification defs.

#### GET /api/v1/organizations/{organization_id}/connectors/{id}/capabilities
#### GET /api/v1/organizations/{organization_id}/connectors/{id}/triggers
#### GET /api/v1/organizations/{organization_id}/connectors/search
Compact agent-facing discovery (`q`, `kind`).

#### POST /api/v1/organizations/{organization_id}/connectors
Register a custom connector (`connector:admin`).

#### POST /api/v1/organizations/{organization_id}/connectors/sync
Publish definitions + Tool rows (`connector:admin`).

#### GET /api/v1/organizations/{organization_id}/integration-connections
#### POST /api/v1/organizations/{organization_id}/integration-connections
#### GET /api/v1/organizations/{organization_id}/integration-connections/{id}
#### PATCH /api/v1/organizations/{organization_id}/integration-connections/{id}
#### DELETE /api/v1/organizations/{organization_id}/integration-connections/{id}
#### POST /api/v1/organizations/{organization_id}/integration-connections/{id}/connect
OAuth authorize URL + scopes.

#### POST /api/v1/organizations/{organization_id}/integration-connections/{id}/callback
State-verified token exchange.

#### POST /api/v1/organizations/{organization_id}/integration-connections/{id}/disconnect
#### POST /api/v1/organizations/{organization_id}/integration-connections/{id}/test
Safe, non-mutating connection test.

#### POST /api/v1/organizations/{organization_id}/integration-connections/{id}/execute
Gated action execution (returns result or `WAITING_FOR_APPROVAL`).

#### GET /api/v1/organizations/{organization_id}/integration-connections/{id}/health
#### GET /api/v1/organizations/{organization_id}/integration-connections/{id}/events
#### POST /api/v1/organizations/{organization_id}/integration-connections/{id}/permissions
#### POST /api/v1/organizations/{organization_id}/integration-connections/{id}/poll
#### POST /api/v1/organizations/{organization_id}/integration-connections/{id}/poll/schedule

#### GET /api/v1/organizations/{organization_id}/credentials
Masked credential list (secrets never returned).

#### POST /api/v1/organizations/{organization_id}/credentials
Encrypted credential storage.

#### POST /api/v1/organizations/{organization_id}/credentials/{id}/rotate
#### POST /api/v1/organizations/{organization_id}/credentials/{id}/revoke
#### DELETE /api/v1/organizations/{organization_id}/credentials/{id}

#### GET /api/v1/organizations/{organization_id}/connector-webhooks
#### POST /api/v1/organizations/{organization_id}/connector-webhooks
Secret shown once; hash stored.

#### POST /api/v1/webhooks/{connector}/{connection}/{endpoint}
Public inbound receiver (signature-authenticated, no session).

### Health & Monitoring

#### GET /api/v1/health
Basic health check.

#### GET /api/v1/health/ready
Readiness check.

### Error Responses

All error responses follow this format:

```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "Human readable message",
    "request_id": "req_abc123",
    "details": [
      {
        "field": "field_name",
        "code": "VALIDATION_ERROR",
        "message": "Field is required"
      }
    ],
    "status_code": 400
  }
}
```

### Common Error Codes

| Code | HTTP Status | Description |
|------|-------------|-------------|
| VALIDATION_ERROR | 422 | Request validation failed |
| NOT_FOUND | 404 | Resource not found |
| UNAUTHORIZED | 401 | Authentication required |
| FORBIDDEN | 403 | Insufficient permissions |
| INTERNAL_ERROR | 500 | Server error |
| CONFLICT | 409 | Resource conflict |
| RATE_LIMITED | 429 | Too many requests |
| SERVICE_UNAVAILABLE | 503 | Service temporarily unavailable |
| BAD_REQUEST | 400 | Invalid request |
| UNPROCESSABLE_ENTITY | 422 | Semantic validation error |

### Pagination

List endpoints support pagination:

```
?page=1&page_size=20
```

Response includes pagination metadata:

```json
{
  "data": [...],
  "meta": {
    "page": 1,
    "page_size": 20,
    "total_items": 100,
    "total_pages": 5,
    "has_next": true,
    "has_prev": false
  }
}
```

### Rate Limiting

Rate limits apply to auth endpoints:

- Login: 10 requests/minute
- Register: 5 requests/hour
- Password reset: 3 requests/hour
- Email verification: 5 requests/hour

Response headers:
```
X-RateLimit-Limit: 10
X-RateLimit-Remaining: 9
X-RateLimit-Reset: 1234567890
Retry-After: 60
```

### Idempotency

For mutation endpoints, include `Idempotency-Key` header:

```
Idempotency-Key: uuid-v4
```

Response will be cached for 24 hours.

### Versioning

API version is in URL path: `/api/v1/`

Future versions will be at `/api/v2/`, etc.

### WebSocket Support

WebSocket endpoints available at `/api/v1/ws/...` for real-time updates.

### SDKs

Official SDKs:
- Python: `pip install openagent-sdk` (`CodeClient` in
  `openagent.code.client` — repositories, workspaces, tasks with
  `wait()`/`result()`, search, review, commit, push, PR drafts;
  `SandboxClient` in `openagent.sandbox.client` — sandboxes, `execute()`/
  `wait()`/`cancel()`, leases, profiles, `security_check()`)
- TypeScript: `npm install @openagent/sdk` (`sdk.code` namespace with
  `sdk.code.tasks.create/wait/result`, search, review, execute, `preparePR`;
  `sdk.sandbox` namespace with `create/start/stop/destroy`, `execute/wait/cancel`,
  leases, profiles, `securityCheck`)

```python
task = await openagent.code.tasks.create(
    repository="repo-id",
    objective="Fix the failing authentication tests",
)
await task.wait()
result = await task.result()
```

```python
execution = await openagent.sandbox.execute(
    profile="TEST",
    command=["pytest", "tests/"],
    workspace=workspace_id,
)
result = await execution.wait()
```

### Support

- Documentation: https://docs.openagent.ai
- Issues: https://github.com/openagent/openagent/issues
- Email: support@openagent.ai