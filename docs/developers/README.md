# OpenAgent Developer Platform

The OpenAgent Developer Platform is the single, canonical way to extend OpenAgent.
There is exactly one extension type registry, one permission catalog, and one
trust model — every extension kind (agents, tools, workflow nodes, connectors,
MCP servers, skills, evaluators, providers, UI, templates) is an entry in that
registry, never a parallel plugin system.

Backend source of truth: `apps/api/src/openagent/developer/`
(`types.py`, `manifest.py`, `permissions.py`, `security.py`, `signing.py`,
`packaging.py`, `versioning.py`, `service.py`, `mocks.py`, `config.py`, `errors.py`).

## Extension types (20-type registry)

From `developer/types.py` (`ExtensionType`):

| Type | What it is |
|------|------------|
| `agent` | Autonomous agent with model, memory, tools |
| `agent-team` | Multi-agent team (workforce) |
| `tool` | Single callable capability executed via the Tool Runtime |
| `workflow-node` | Custom node for the workflow engine |
| `workflow-template` | Reusable workflow template |
| `connector` | Third-party integration (OAuth, webhooks, polling) |
| `mcp-server` | MCP server (tools + resources + prompts) |
| `mcp-tool` / `mcp-resource` / `mcp-prompt` | Single MCP primitive |
| `skill` | Reusable skill pack (prompts, playbooks, tools) |
| `evaluator` | Quality gate / judge for runs and artifacts |
| `memory-provider` / `model-provider` / `model-adapter` | Pluggable providers |
| `browser-extension` | Browser automation profile |
| `sandbox-profile` | Secure execution profile |
| `integration` | Legacy alias kept for migration (prefer `connector`) |
| `ui-extension` | Frontend surface (pages, widgets) |
| `automation-pack` | Bundle of agents + workflows + connectors |

Per-kind guides live in [`extensions/`](extensions/agents.md).

## Permission catalog

Permissions are declared in `openagent.yaml` under `permissions:` and enforced
server-side (`developer/permissions.py`). Every permission is explicit,
reviewable, enforceable, auditable, and revocable. Least privilege by default;
new scaffolds get `("tool:execute", "filesystem:workspace")` only.

| Permission | Meaning | Approval-gated |
|------------|---------|----------------|
| `network:outbound` | Outbound HTTPS to declared allowlisted hosts | no (allowlist required) |
| `network:restricted` | Private/restricted network access (SSRF-sensitive) | **yes** |
| `filesystem:workspace` | R/W inside the extension workspace | no |
| `filesystem:artifact` | R/W declared artifacts only | no |
| `tool:execute` | Invoke other tools via Tool Runtime | no |
| `connector:use` | Use declared connector connections | no |
| `memory:read` / `memory:write` | Scoped memory access | no |
| `browser:use` | Drive browser sessions under browser policy | **yes** |
| `sandbox:execute` | Execute code inside the Sandbox boundary | no |
| `mcp:connect` | Connect to declared MCP servers | no |
| `secret:access` | Access declared secret *references* (never values) | **yes** |
| `workflow:execute` | Start workflow executions | no |
| `agent:invoke` | Invoke sub-agents under policy | no |
| `model:invoke` | Invoke models via the Model Router | no |
| `evaluation:run` | Run evaluators on observable outputs | no |
| `webhook:receive` | Receive inbound webhooks on declared endpoints | no |
| `storage:use` | Object storage within quota | no |
| `billing:read` | Read own usage/entitlement state | no |

High-risk permissions (`network:restricted`, `browser:use`, `secret:access`)
require a human approval record for `COMMUNITY`/`UNTRUSTED` extensions and can
never be silently self-granted: an installation cannot grant more than the
manifest declares.

## Lifecycle

```
idea → init → code → test → validate → package → scan → sign → publish
     → review gates → install → deploy → health check → activate
       → monitor → update / rollback → deprecate
```

Stage machine (`ExtensionLifecycle`): `DRAFT → VALIDATED → PACKAGED → SIGNED →
PUBLISHED → ACTIVE`, with `DISABLED`, `DEPRECATED`, `QUARANTINED`, `REVOKED`,
`UNPUBLISHED` as terminal/safety states. Quarantine immediately blocks new
execution; rollback restores the last known-good verified version. Every
transition is audited.

## Architecture

```
Developer
   │
   ├─► SDK  (@openagent/sdk TS · openagent-sdk Python)
   ├─► CLI  (openagent init/dev/validate/test/build/package/publish/…)
   └─► Portal (web: /templates /skills /marketplace /publisher)
                     │
                     ▼
        ┌─ FastAPI ─ /organizations/{id}/developer|/extensions ─┐
        │  validate → test → package → scan → compat → sign      │
        │  → publish → install → deploy → health → activate      │
        └───────────────────────┬───────────────────────────────┘
           │            │             │               │
      Tool Runtime   Sandbox    ConnectorEngine   Model Router
      (tools)     (isolation)   (OAuth/SSRF guard)  (LLM judge)
           │            │             │               │
           └────────────┴──────┬──────┴───────────────┘
                               ▼
              PostgreSQL (extension_* tables) · Redis queues
              Audit log ← every transition · Security events
```

Module map (`apps/api/src/openagent/developer/*`):

| Module | Responsibility |
|--------|----------------|
| `types.py` | Extension-type registry, permission catalog, trust levels, lifecycle, events, compat matrix |
| `manifest.py` | `openagent.yaml` schema (`ExtensionManifest`), strict validation |
| `permissions.py` | Permission enforcement + trust model |
| `security.py` | Static scans, secret detection, install-hook safety |
| `signing.py` | Ed25519 package signing / verification, key rotation, revocation |
| `packaging.py` | Deterministic `.oaext` archives, checksums, SBOM, provenance |
| `versioning.py` | Semver, constraints, compatibility, deprecation metadata |
| `service.py` | Lifecycle orchestration pipeline |
| `mocks.py` | Deterministic offline test mocks |
| `config.py` | `DeveloperSettings`, deployment plan/stages |
| `errors.py` | Public error taxonomy, webhook sign/verify |

DB tables (`apps/api/src/openagent/db/models/developer.py`):
`developer_projects`, `developer_project_members`, `developer_environments`,
`extension_definitions`, `extension_versions`, `extension_installations`,
`extension_deployments`, `developer_webhooks`, `developer_webhook_deliveries`,
`extension_analytics_daily`, `extension_trust_records`.

## The manifest (`openagent.yaml`)

Every extension ships an `openagent.yaml` validated by `ExtensionManifest`.
Field names below match `manifest.py` exactly:

```yaml
manifest_version: "1"          # == MANIFEST_VERSION
name: my-org/hello-agent       # slug, must match extension slug
namespace: my-org               # optional publisher namespace
version: 1.0.0                  # semver (validated)
display_name: Hello Agent
description: A minimal agent that greets the world.
author: {name: Your Name, email: you@example.com, url: https://example.com}
license: MIT
repository: https://github.com/my-org/hello-agent
documentation: https://docs.example.com/hello-agent
type: agent                     # one of the 20 registry values
runtime: {language: typescript, entrypoint: src/index.ts, version: ""}
permissions: [tool:execute, filesystem:workspace]
capabilities: [greet]
required_services: []
config_schema:                  # JSON Schema for install-time config (no secrets!)
  type: object
  properties: {greeting: {type: string}}
secrets: [OPENAI_API_KEY]       # REFERENCE names only (UPPER_SNAKE), never values
network: {allowed_hosts: []}
storage: {}
compatibility:                  # defaults shown; validated against matrix
  openagent: ">=1.0.0 <2.0.0"
  sdk: ">=1.0.0 <2.0.0"
  extension_api: "1.x"
  api_version: v1
dependencies: [{name: "@openagent/extension-sdk", version: ^1.0.0, optional: false}]
optional_dependencies: []
ui: {}
commands: []
events: [agent.run.completed.v1]  # subscribed developer events
hooks: []
metadata: {}
security:
  trust_level: UNTRUSTED         # CORE|VERIFIED|ORGANIZATION|COMMUNITY|UNTRUSTED
  network_policy: restricted     # none|restricted|allowlisted
  allowed_hosts: []
  sandbox_profile: ""
  risk_notes: ""
```

Cross-field rules enforced by the backend (never silently widened):

- `network:outbound` requires `network.allowed_hosts` (or
  `security.allowed_hosts`) non-empty.
- `network:restricted` requires `security.network_policy: allowlisted` with
  explicit `allowed_hosts`.
- `secrets` must be `UPPER_SNAKE_CASE` reference names; mapping shapes
  (values) are rejected.
- `config_schema` must not embed credential material (`AKIA…`, private keys).
- Unknown types / permissions / duplicate permissions are rejected.

## Idea → deploy flow

1. **Idea** — pick a type from the registry; choose least-privilege permissions.
2. **Init** — `openagent init --type agent --name my-org/hello-agent`
   scaffolds `openagent.yaml` + `src/` + tests (see `templates/`).
3. **Code** — build against the extension-sdk builder API
   (`defineAgent`, `defineTool`, `defineWorkflowNode`, `defineConnector`,
   `defineMCPServer`, `defineSkill`, `defineEvaluator`).
4. **Test** — `openagent dev` (local run with deterministic mocks) then
   `openagent test` (standard harness: contract checks per type, sandboxed).
5. **Validate** — `openagent validate` runs the CREATE→VALIDATE gate:
   manifest, schemas, dependencies, permissions, compatibility, secret scan.
6. **Package** — `openagent build && openagent package` produces a
   deterministic `.oaext` archive with checksums, SBOM, and provenance.
   Host install hooks (`preinstall`/`postinstall`) are refused.
7. **Publish** — `openagent publish` runs the security gate (secret hits block
   unless an audited override with reason is supplied; critical findings
   always block), then review gates and registry listing.
8. **Deploy** — `openagent deploy --env staging|production` walks the
   deployment stages
   (`validate,test,build,package,security_scan,compatibility_check,sign,deploy,health_check,activate`);
   `openagent rollback` restores the last known-good version.

## Docs map

- [`sdk/`](sdk/README.md) — TypeScript + Python SDK reference
- [`cli/`](cli/README.md) — full CLI command reference
- [`extensions/`](extensions/agents.md) — per-kind build guides (7 kinds)
- [`publishing.md`](publishing.md) — publish pipeline + secret-override policy
- [`versioning.md`](versioning.md) — semver + 1.x compat matrix + deprecations
- [`migrations.md`](migrations.md) — SDK migration guides
- [`api.md`](api.md) — REST reference (auth, pagination, idempotency, webhooks)
- [`security.md`](security.md) — secret handling, sandbox, injection, SSRF, prod
- [`threat-model.md`](threat-model.md) — threats mapped to platform controls
