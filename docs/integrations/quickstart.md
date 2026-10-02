# Integrations Quickstart

Connect a service in under five minutes. All privileged operations flow
through Connector → Policy → Risk/Approval → Tool Runtime → Verify → Audit.

## 1. Browse the catalog

`GET /api/v1/organizations/{id}/connectors?search=github`
or open `/integrations/catalog`. Trust badges (`CORE/VERIFIED/ORGANIZATION/
COMMUNITY/CUSTOM/UNTRUSTED`) drive policy — community/custom never elevate.

## 2. Create a connection (least privilege)

```http
POST /api/v1/organizations/{id}/integration-connections
{
  "connector_id": "github",
  "name": "ci-read",
  "granted_capabilities": ["github.repositories.read", "github.issues.read"]
}
```

Grant only what the workflow needs. Unknown capabilities are rejected;
`deny_actions`/`allow_actions` in `policy_config` narrow further.

## 3. Attach a credential (never in code)

Create via `Settings → Credentials` (values masked, shown once), then attach:

```http
PATCH /api/v1/organizations/{id}/integration-connections/{connection_id}
{ "credential_id": "<credential_id>" }
```

Raw secrets never reach models, logs, or the frontend after creation.

## 4. OAuth (GitHub/Slack/Google/...)

```http
POST .../integration-connections/{id}/connect {"redirect_uri": "https://app.example.com/integrations/connected/{id}"}
→ { "authorize_url": "https://provider...&state=..." }
```

Approve the shown scopes, complete provider authorization, and the callback
verifies HMAC state, single-use PKCE verifier, redirect allowlist, then
encrypts tokens (Fernet envelope, credential-bound). Expired tokens refresh
once automatically when a `refresh_token` is stored.

## 5. Execute through the gate

```http
POST .../integration-connections/{id}/execute
{ "action_id": "github.create_issue", "input": {"repo": "acme/app", "title": "bug"} }
```

High-risk actions return `WAITING_FOR_APPROVAL` with an `approval_id`;
resume with the same call plus `approval_id`. Mutations are verified
(`verify_tool_call`) and audited (`connector.action_executed`).

## 6. Events → workflows

- Webhooks: create per-connection endpoints (`/connector-webhooks`),
  HMAC-verified with timestamp + replay guard, normalized to
  `{event_type, provider, resource_id, timestamp, payload_reference}`,
  published on the internal event bus → workflow triggers.
- Polling: for providers without webhooks, declare `poll_config`
  (`interval_seconds` ≥ 60, `max_items` ≤ 500); the scheduler runs bounded
  cycles with cursor persistence + dedupe + backoff.

## 7. Test without providers

```python
from openagent.connectors.testing import MockProviderHTTP, MockAuth, mock_ctx
```

Every official connector ships tests on these fakes — no real credentials.
See `docs/integrations/testing.md`.
