# Developer REST API (API v1)

Base: `{API_URL}/api/v1`. Auth: `Authorization: Bearer <key>` + org scope
`X-Organization-ID: <org>` (or `/organizations/{id}/…` path param). All
application APIs are versioned; there are no unversioned endpoints.

## Endpoint groups

### Developer projects & environments

| Method | Path | Description |
|--------|------|-------------|
| GET/POST | `/organizations/{id}/developer/projects` | List / create projects |
| GET | `/organizations/{id}/developer/projects/{pid}` | Project detail (+ extensions) |
| POST | `/organizations/{id}/developer/projects/{pid}/members` | Add member |
| GET/PUT | `/organizations/{id}/developer/environments?project_id=` | List / upsert env (development\|staging\|production) |

### Extensions lifecycle

| Method | Path | Description |
|--------|------|-------------|
| GET/POST | `/organizations/{id}/extensions[?type=]` | List (filter by 20-type registry) / create definition |
| GET | `/organizations/{id}/extensions/{eid}` | Definition + versions |
| POST | `/organizations/{id}/extensions/{eid}/versions` | Create version (manifest must match slug) |
| POST | `/organizations/{id}/extensions/{eid}/validate` | Validate manifest + sources (no exec) |
| POST | `/organizations/{id}/extensions/{eid}/test` | Sandboxed standard harness |
| POST | `/organizations/{id}/extensions/{eid}/package` | Build `.oaext` (refuses host install hooks) |
| GET | `/organizations/{id}/extensions/{eid}/artifact` | Artifact digest/size metadata |
| POST | `/organizations/{id}/extensions/{eid}/publish` | Security-gated publish |
| POST | `/organizations/{id}/extensions/{eid}/sign` | Register pubkey → returns digest to sign |
| POST | `/organizations/{id}/extensions/{eid}/sign/complete` | Submit offline Ed25519 signature |
| POST | `/organizations/{id}/extensions/{eid}/install` | Install into env (permits ≤ manifest) |
| POST | `/organizations/{id}/extensions/{eid}/disable` | Disable |
| POST | `/organizations/{id}/extensions/{eid}/quarantine` | Emergency quarantine `{reason}` |
| POST | `/organizations/{id}/extensions/{eid}/rollback?installation_id=` | Rollback to known-good |

### Registry, webhooks, events, usage

| Method | Path | Description |
|--------|------|-------------|
| GET | `/organizations/{id}/developer/deployments` | Deployment history |
| GET/POST | `/organizations/{id}/developer/webhooks` | List / register webhook (events + secret ref) |
| DELETE | `/organizations/{id}/developer/webhooks/{wid}` | Remove webhook |
| GET | `/organizations/{id}/developer/events` | Versioned event schemas |
| GET | `/organizations/{id}/developer/usage` | Aggregated analytics |
| GET | `/api/v1/developer/sdk` | Public SDK metadata (no auth) |
| GET | `/api/v1/developer/errors` | Public error taxonomy (no auth) |
| GET | `/api/v1/developer/events` | Public event catalog (no auth) |

Required permissions (`require_permission`): `package:create` (packaging),
`package:read` (artifact), `package:manage` (publish/sign/quarantine),
`package:execute` (install).

## Auth

```bash
curl -H "Authorization: Bearer $OPENAGENT_API_KEY" \
     -H "X-Organization-ID: $OPENAGENT_ORG_ID" \
     "$OPENAGENT_API_URL/api/v1/organizations/$OPENAGENT_ORG_ID/extensions?type=tool"
```

Short-lived Bearer tokens; rotation supported. Never put keys in URLs, logs,
or manifests. `401` = missing/invalid, `403` = valid auth but denied
(includes `APPROVAL_REQUIRED` detail for gated permissions).

## Pagination

List endpoints accept `?page=&page_size=` (defaults `1` / `20`, max `100`):

```json
{ "data": [...], "page": 1, "page_size": 20, "total": 137 }
```

Iterate until `page * page_size >= total`. Analytics endpoints may return
`day` buckets instead.

## Idempotency

Mutating calls accept `Idempotency-Key: <unique>`; replaying the same key
returns the original result instead of duplicating (versions, publishes,
installs, deploys). Generate with `uuid4`, scope per operation:

```bash
curl -X POST -H "Idempotency-Key: $UUID" .../extensions/{eid}/publish
```

## Errors

Shape: `{ "error": { "code": "...", "message": "...", "request_id": "..." } }`.
Codes: `AUTHENTICATION_ERROR(401)`, `AUTHORIZATION_ERROR(403)`,
`POLICY_DENIED(403)`, `APPROVAL_REQUIRED(403)`, `NOT_FOUND(404)`,
`CONFLICT(409)`, `VALIDATION_ERROR(422)`, `COMPATIBILITY_ERROR(422)`,
`EXTENSION_ERROR(422)`, `RATE_LIMITED(429)`, `TIMEOUT(504)`,
`TOOL_EXECUTION_ERROR/CONNECTOR_ERROR/MCP_ERROR/SANDBOX_ERROR/DEPLOYMENT_ERROR(502)`.
Production never returns stack traces, secrets, or internal paths.

## Rate limits

Per key + org. `429` includes `Retry-After`; back off exponentially with
jitter and retry with the same idempotency key.

## Webhook verification (HMAC-SHA256, `developer/errors.py`)

Header: `v1,t=<unix>,id=<delivery_id>,sig=<hex>` where
`sig = HMAC(secret, "v1.{t}.{id}.{sha256(body)}")`. Reject when the `v1`
prefix is missing, `|now - t| > 300s`, JSON has no `event` field, or
comparison fails (constant-time).

```python
from openagent.developer.errors import verify_webhook

result = verify_webhook(secret, body, header)
if not result["ok"]:
    raise ValueError(result["reason"])  # malformed | timestamp outside tolerance | signature mismatch
```

```typescript
import { createHmac, timingSafeEqual } from "node:crypto";

function verify(secret: string, body: Buffer, header: string): boolean {
  const parts = Object.fromEntries(
    header.split(",").map((c) => c.trim().split("=") as [string, string]),
  );
  if (!header.startsWith("v1") || !parts.sig || !parts.t) return false;
  if (Math.abs(Date.now() / 1000 - Number(parts.t)) > 300) return false;
  const bodyHash = createHash("sha256").update(body).digest("hex");
  const base = `v1.${parts.t}.${parts.id}.${bodyHash}`;
  const sig = createHmac("sha256", secret).update(base).digest("hex");
  return timingSafeEqual(Buffer.from(sig), Buffer.from(parts.sig));
}
```
