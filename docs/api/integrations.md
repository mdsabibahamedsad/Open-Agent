# Integrations API (MP21)

Base: `/api/v1/organizations/{organization_id}` (+ public `/api/v1/webhooks/...`).
Auth: session + `X-Organization-ID`. RBAC: `connector:*`, `credential:*`,
`webhook:*`, `tool:read`. Tenant isolation on every route. Secrets are
never returned — create/rotate respond with masked metadata; webhook
secrets are shown once.

## Catalog & discovery

```http
GET    /connectors?category=&trust=&search=
GET    /connectors/:id                      # manifest, secrets stripped
GET    /connectors/:id/actions              # schemas, risk, verification
GET    /connectors/:id/capabilities
GET    /connectors/:id/triggers
GET    /connectors/search?q=&kind=          # compact agent-facing descriptors
POST   /connectors                          # register custom (connector:admin)
POST   /connectors/sync                     # publish definitions + Tool rows
```

## Connections

```http
GET    /integration-connections?connector_id=&status=
POST   /integration-connections             # creates UNCONNECTED
GET    /integration-connections/:id         # + health history
PATCH  /integration-connections/:id
DELETE /integration-connections/:id
POST   /integration-connections/:id/connect    # OAuth authorize URL + scopes
POST   /integration-connections/:id/callback   # state-verified token exchange
POST   /integration-connections/:id/disconnect # revoke + clear
POST   /integration-connections/:id/test       # safe, non-mutating
POST   /integration-connections/:id/execute    # gated action execution
GET    /integration-connections/:id/health     # states + usage
GET    /integration-connections/:id/events
POST   /integration-connections/:id/permissions  # least-privilege grants
```

`execute` returns the provider result, or `WAITING_FOR_APPROVAL` with an
`approval_id` to resume with. Tool path (`/tools/execute` on
`connector:*` tools) delegates to the same engine — one gate, never two.

## Credentials

```http
GET    /credentials?provider=              # masked
POST   /credentials                        # encrypted envelope storage
POST   /credentials/:id/rotate
POST   /credentials/:id/revoke
DELETE /credentials/:id                    # ciphertext wiped first
```

## Webhooks

```http
GET    /connector-webhooks?connection_id=
POST   /connector-webhooks?connection_id=   # secret shown once
POST   /connector-webhooks/:id/rotate
DELETE /connector-webhooks/:id
POST   /api/v1/webhooks/:connector/:connection/:endpoint   # public, signed
```

The public receiver resolves the registered endpoint row first (never
trusts URL names), decrypts the bound secret, verifies HMAC/timestamp,
dedupes delivery IDs, filters event types, normalizes, and publishes to
the event bus. Failures are 403/404/409/410/413 — never 500s with detail.
