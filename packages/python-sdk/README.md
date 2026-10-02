# OpenAgent Python SDK

Production Python SDK for the OpenAgent API (`openagent==1.0.0`).
Sync (`OpenAgent`) and async (`AsyncOpenAgent`) clients over `httpx`.

## Install

```bash
pip install openagent
# or from this monorepo
pip install ./packages/python-sdk
# dev / tests
pip install "./packages/python-sdk[dev]"
```

Requires Python `>=3.9`, `httpx>=0.25`.

## Auth

Pass credentials explicitly or via environment (shared with the CLI story):

| Env var | Meaning |
|---|---|
| `OPENAGENT_API_KEY` | Bearer API key (**required**) |
| `OPENAGENT_API_URL` | Base URL, default `http://localhost:8000` |
| `OPENAGENT_ORG` (alias `OPENAGENT_ORGANIZATION_ID`) | Default organization id |

Every request sends `Authorization: Bearer <key>`, `X-Organization-ID`
(when an org is set), and a unique `X-Request-ID`. Write calls accept an
`Idempotency-Key` via `idempotency_key=...`.

## Quickstart (sync)

```python
from openagent import OpenAgent

client = OpenAgent(api_key="sk_...", organization_id="org_123")

agent = client.agents.create(name="support-bot", model="default")
print(agent["id"])

run = client.agents.run(agent["id"], input={"message": "hello"})
for event in client.agent_runs.stream(run["id"]):
    print(event["event"], event["data"])

client.close()
# or: with OpenAgent(...) as client: ...
```

## Quickstart (async)

```python
import asyncio
from openagent import AsyncOpenAgent

async def main():
    async with AsyncOpenAgent(api_key="sk_...", organization_id="org_123") as client:
        agent = await client.agents.create(name="support-bot")
        run = await client.agents.run(agent["id"], input={"message": "hello"})
        print((await client.agent_runs.get(run["id"]))["status"])

asyncio.run(main())
```

## Resources

| Attribute | API surface |
|---|---|
| `client.agents` | CRUD + `run`, `list_runs` |
| `client.agent_runs` | `list/get/create/cancel/list_steps/stream` |
| `client.workflows` | CRUD + `execute`, executions (`get/cancel/stream`) |
| `client.executions` | Cloud executions `list/get/create/cancel/logs/stream_logs` |
| `client.tools` | CRUD + `execute`, `list_versions` |
| `client.connectors` | CRUD + `test`, connections, credentials (`rotate`), webhooks |
| `client.mcp` | Servers CRUD + `connect/disconnect`, server tools + `call_tool` |
| `client.memory` | CRUD + `search/transition/review/correct` |
| `client.models` | Discovery: `list/get/discover/list_providers/recommend` |
| `client.evaluations` | CRUD + `run/list_runs/get_run`, rubrics, quality gates |
| `client.sandboxes` | CRUD + `execute`, executions, profiles |
| `client.approvals` | CRUD + `approve/reject/cancel`, policies, delegations |
| `client.marketplace` | `search`, listings (+`install`), publishers, reviews, favorites |
| `client.registries` | CRUD + `lookup`, `publish_package` |
| `client.billing` | products, prices, checkout sessions, subscriptions, entitlements, usage, quotas, invoices, revenue, payouts |
| `client.projects` | Developer projects `list/get/create/update_environment` |
| `client.extensions` | Full lifecycle: `create_version/validate/test/package/artifact/publish/sign/sign_complete/install/disable/quarantine/rollback/deploy` |
| `client.deployments` | Developer deployments `list/get/cancel/logs` |
| `client.events` | `list_schemas` (public), org `list/iterate/get`, `usage` |
| `client.webhooks` | Developer webhook CRUD + `rotate_secret/test` + `verify` helper |

## Pagination

List methods return a `PaginatedResult` (`items`, `total`, `next_cursor`, `has_more`):

```python
page = client.agents.list(limit=50)
print(page.items, page.next_cursor)

for agent in client.agents.iterate(limit=100):
    print(agent["id"])
```

Async: `await client.agents.list(...)`, `async for a in client.agents.iterate(...)`.

## Streaming (SSE)

```python
for event in client.agent_runs.stream(run_id):
    # {"event": "message", "data": {...}}
    ...
```

## Idempotency

```python
client.extensions.publish(ext_id, idempotency_key="publish-0001")
```

Retries happen only for `GET` (and `HEAD`/`OPTIONS`) or for writes that
carry an `idempotency_key`. On `429` the server's `Retry-After` header is
honored, otherwise exponential backoff applies.

## Errors

```python
from openagent import NotFoundError, RateLimitError, OpenAgentError

try:
    client.agents.get("missing")
except NotFoundError as exc:
    print(exc.code, exc.message, exc.request_id)
except RateLimitError as exc:
    print("retry after", exc.retry_after, exc.rate_limit)
except OpenAgentError as exc:
    print(exc)
```

The backend returns `{"error": {"code", "message", "request_id"}}` or
`{"detail": ...}`; the SDK maps these to a typed taxonomy
(`AuthenticationError`, `AuthorizationError`, `ValidationError`,
`NotFoundError`, `ConflictError`, `RateLimitError`, `TimeoutError`,
`PolicyDeniedError`, `ApprovalRequiredError`, `CompatibilityError`,
`ExtensionError`, `ToolExecutionError`, `ConnectorError`, `MCPError`,
`SandboxError`, `DeploymentError`). Messages are safe-only and truncated.

## Webhooks

```python
from openagent.webhooks import sign_webhook, verify_webhook, parse_webhook

header = sign_webhook(secret, body, delivery_id="dlv_1")
result = verify_webhook(secret, body, header)  # {"ok", "reason", "delivery_id"}
if result["ok"]:
    payload = parse_webhook(body)  # requires an "event" field
```

Or via the resource helper: `client.webhooks.verify(secret, body, header)`.
Verification enforces the `v1,t=..,id=..,sig=..` format, constant-time
comparison, and a 300s replay window.
