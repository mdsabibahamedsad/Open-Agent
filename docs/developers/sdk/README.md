# OpenAgent SDK Reference (v1.0.0, API v1, extension API 1.x)

Two first-class SDKs, one platform contract: Bearer auth, org scoping via
`X-Organization-ID`, `Idempotency-Key` on mutating calls, cursor pagination,
and the public error taxonomy (`code` + `message` + `request_id`).

## Install

```bash
# TypeScript
pnpm add @openagent/sdk
# Python
pip install openagent-sdk
```

## Auth

```typescript
import { createSDK } from "@openagent/sdk";

const client = createSDK({
  apiUrl: "http://localhost:8000",
  apiKey: process.env.OPENAGENT_API_KEY!,
  organizationId: process.env.OPENAGENT_ORG_ID!,
});
```

```python
from openagent_sdk import OpenAgentClient

client = OpenAgentClient(
    api_url="http://localhost:8000",
    api_key=os.environ["OPENAGENT_API_KEY"],
    organization_id=os.environ["OPENAGENT_ORG_ID"],
)
```

Config resolution order: explicit args → `OPENAGENT_API_URL` /
`OPENAGENT_API_KEY` / `OPENAGENT_ORG_ID` env → stored CLI profile
(`~/.config/openagent/config.json`, mode `0600`).

## Agents

```typescript
const agent = await client.agents.create(
  { name: "researcher", model: "gpt-4o-mini", tools: ["web.search"] },
  { idempotencyKey: "agent-researcher-001" },
);
const agents = await client.agents.list({ page: 1, page_size: 20 });
```

```python
agent = client.agents.create(
    {"name": "researcher", "model": "gpt-4o-mini", "tools": ["web.search"]},
    idempotency_key="agent-researcher-001",
)
agents = client.agents.list(page=1, page_size=20)
```

## Tools

```typescript
const result = await client.tools.invoke(
  "calculator.evaluate", { expression: "2*(3+4)" },
);
```

```python
result = client.tools.invoke("calculator.evaluate", {"expression": "2*(3+4)"})
```

Tool calls execute inside the Tool Runtime under the installation's granted
permissions; approval-gated tools return `APPROVAL_REQUIRED` with an
`approval_id` to resume against.

## Workflows

```typescript
const wf = await client.workflows.create({ name: "triage", definition: {...} });
const run = await client.workflows.execute(wf.id, { input: { ticket: "VIP outage" } });
```

```python
wf = client.workflows.create({"name": "triage", "definition": {...}})
run = client.workflows.execute(wf["id"], {"input": {"ticket": "VIP outage"}})
```

## Connectors

```typescript
const conns = await client.integrations.list({ category: "communication" });
const conn = await client.integrations.connect("github", {
  scopes: ["repo:read"], credential_ref: "cred_123",
});
await client.integrations.invoke(conn.id, "github.list_repos", { org: "my-org" });
```

```python
conns = client.integrations.list(category="communication")
conn = client.integrations.connect("github", {"scopes": ["repo:read"]})
client.integrations.invoke(conn["id"], "github.list_repos", {"org": "my-org"})
```

## MCP

```typescript
await client.mcp.connect("deep-research", { transport: "stdio" });
const out = await client.mcp.callTool("deep-research", "search", { q: "SSRF defenses" });
const res = await client.mcp.readResource("deep-research", "kb://ssrf");
```

```python
client.mcp.connect("deep-research", {"transport": "stdio"})
out = client.mcp.call_tool("deep-research", "search", {"q": "SSRF defenses"})
```

## Memory

```typescript
await client.memory.write({ scope: "agent:researcher", key: "pref", value: "concise" });
const mem = await client.memory.read({ scope: "agent:researcher", key: "pref" });
```

```python
client.memory.write({"scope": "agent:researcher", "key": "pref", "value": "concise"})
mem = client.memory.read({"scope": "agent:researcher", "key": "pref"})
```

## Evaluations

```typescript
const evalRun = await client.evaluator.run({
  target: { type: "agent_run", id: run.id },
  rubric: "factuality@2",
});
```

```python
eval_run = client.evaluator.run(
    {"target": {"type": "agent_run", "id": run["id"]}, "rubric": "factuality@2"}
)
```

There are no force-success APIs; verification evidence is tamper-resistant and
scored by deterministic verifiers + Model-Router judges.

## Extensions (developer namespaces)

```typescript
const ext = await client.extensions.create({ slug: "acme/greeter", type: "agent" });
await client.extensions.createVersion(ext.id, { version: "1.0.0", manifest });
await client.extensions.validate(ext.id);
await client.extensions.publish(ext.id, { files });
const sdkMeta = await client.developer.sdk();       // public, no auth
const errTaxonomy = await client.developer.errors();// public, no auth
```

```python
ext = client.extensions.create({"slug": "acme/greeter", "type": "agent"})
client.extensions.create_version(ext["id"], {"version": "1.0.0", "manifest": manifest})
client.extensions.validate(ext["id"])
```

## Events (webhooks you receive)

Subscribe to versioned developer events (`DEVELOPER_EVENTS` in
`developer/types.py`): `agent.run.started.v1`, `agent.run.completed.v1`,
`agent.run.failed.v1`, `workflow.execution.started.v1`,
`workflow.execution.completed.v1`, `workflow.execution.failed.v1`,
`tool.invoked.v1`, `tool.completed.v1`, `tool.failed.v1`,
`connector.event.received.v1`, `mcp.server.connected.v1`,
`mcp.server.disconnected.v1`, `deployment.started.v1`,
`deployment.completed.v1`, `deployment.failed.v1`, `extension.published.v1`,
`extension.installed.v1`, `extension.quarantined.v1`, `package.published.v1`,
`evaluation.completed.v1`. Verify signatures per `api.md` (HMAC-SHA256
`v1,t=…,id=…,sig=…`, 5-minute replay window).

## Errors

All errors share the shape `{ error: { code, message, request_id } }`.
Stable codes (`developer/errors.py`): `AUTHENTICATION_ERROR`,
`AUTHORIZATION_ERROR`, `VALIDATION_ERROR`, `NOT_FOUND`, `CONFLICT`,
`RATE_LIMITED`, `TIMEOUT`, `POLICY_DENIED`, `APPROVAL_REQUIRED`,
`COMPATIBILITY_ERROR`, `EXTENSION_ERROR`, `TOOL_EXECUTION_ERROR`,
`CONNECTOR_ERROR`, `MCP_ERROR`, `SANDBOX_ERROR`, `DEPLOYMENT_ERROR`.
Production responses carry safe info only — no stack traces or secrets.

```typescript
try { await client.agents.create({...}); }
catch (err: any) {
  if (err.code === "APPROVAL_REQUIRED") { /* open approval flow */ }
  if (err.code === "RATE_LIMITED") { /* back off with Retry-After */ }
}
```

## Rate limits

Limits are per API key + org; `429` responses include `Retry-After`.
Back off exponentially with jitter; reuse idempotency keys on retry so
mutating calls are safe to replay.

## Versioning

- API: `/api/v1/…` (no unversioned endpoints). SDK `1.0.0` targets API `v1`
  and extension API `1.x` (manifest `"1"`). Compat matrix:
  `openagent >=1.0.0 <2.0.0`, `sdk >=1.0.0 <2.0.0`.
- Events carry a `.v1` suffix; breaking event changes get a new version while
  the old one is deprecated (never silently altered).
- Deprecated SDK entry points are announced with replacements
  (see `../versioning.md`) — e.g. legacy positional
  `client.agents.create(name, …)` → `client.agents.create({name, …})`.
