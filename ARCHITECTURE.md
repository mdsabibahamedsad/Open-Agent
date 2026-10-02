# OpenAgent Architecture

## Current Repository State

This is a fresh monorepo initialization for OpenAgent - an open-source AI Workforce Operating System.

## Chosen Stack

### Frontend
- **Framework**: Next.js 14+ (App Router)
- **Language**: TypeScript (strict mode)
- **Styling**: Tailwind CSS
- **UI Components**: shadcn/ui + Radix UI primitives
- **State Management**: React Context + TanStack Query
- **Build Tool**: Turborepo

### Backend
- **Framework**: FastAPI
- **Language**: Python 3.11+
- **Validation**: Pydantic v2
- **ORM**: SQLAlchemy 2.0 (async)
- **Migrations**: Alembic
- **Database**: PostgreSQL 15+
- **Cache/Queue**: Redis 7+
- **Testing**: pytest + httpx

### Infrastructure
- **Containerization**: Docker + Docker Compose
- **CI/CD**: GitHub Actions
- **Monorepo**: pnpm workspaces + Turborepo

## Architectural Decisions

### 1. Monorepo Structure

```
openagent/
├── apps/                 # Deployable applications
│   ├── web/             # Next.js frontend
│   ├── api/             # FastAPI backend
│   ├── worker/          # Background job worker
│   ├── desktop/         # Future Tauri/Electron app
│   └── docs/            # Documentation site
├── packages/            # Shared internal packages
│   ├── core/            # Core utilities, constants
│   ├── config/          # Configuration management
│   ├── types/           # Shared TypeScript/Python types
│   ├── logger/          # Structured logging
│   ├── database/        # Database abstraction
│   ├── security/        # Security utilities
│   ├── agent-runtime/   # Agent execution runtime
│   ├── workflow-engine/ # Workflow execution engine
│   ├── model-router/    # LLM model routing
│   ├── tool-system/     # Tool abstraction
│   ├── mcp/             # Model Context Protocol
│   ├── memory/          # Memory system
│   ├── browser/         # Browser automation
│   ├── sandbox/         # Secure execution sandbox
│   ├── evaluator/       # Evaluation framework
│   └── sdk/             # Public SDK
├── integrations/        # Third-party integrations
├── marketplace/         # Marketplace packages
├── infrastructure/      # Infrastructure as code
├── examples/            # Example applications
├── tests/               # Cross-cutting tests
└── docs/                # Architecture documentation
```

### 2. Dependency Rules

```
apps/web       → packages/types, packages/config, packages/core
apps/api       → packages/types, packages/config, packages/core, packages/logger, packages/database, packages/security
apps/worker    → packages/types, packages/config, packages/core, packages/logger, packages/database
packages/*     → packages/core, packages/config, packages/types (where applicable)
packages/core  → (no internal dependencies)
packages/config → packages/core
packages/types → packages/core
packages/logger → packages/core, packages/config
packages/database → packages/core, packages/config, packages/logger
packages/security → packages/core, packages/config
```

**Forbidden Dependencies:**
- Frontend packages → Backend packages
- Domain packages (agent-runtime, workflow-engine) → UI packages
- Infrastructure packages → Domain packages
- Circular dependencies between any packages

### 3. Layered Backend Architecture

```
API Layer (FastAPI routes)
    ↓
Application Services (Business logic, orchestration)
    ↓
Domain Layer (Entities, value objects, domain services)
    ↓
Infrastructure Layer (Database, external APIs, Redis)
```

### 4. Multi-Tenant Foundation

All organization-scoped resources include `organization_id`. Tenant isolation is enforced at the database/repository layer, not just in application code.

### 5. API Versioning

All application APIs are versioned: `/api/v1/`, `/api/v2/`, etc. No unversioned endpoints.

### 6. Error Handling

Consistent error contract:
```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "Human readable message",
    "request_id": "uuid",
    "details": {}
  }
}
```

### 7. Request Correlation

Every request gets a `request_id` (UUID) propagated through logs, errors, and responses.

### 8. Configuration

Environment-based configuration with `.env.example` for documentation. No secrets in code.

### 9. Logging

Structured JSON logging in production, pretty logging in development. Request correlation IDs included.

## Future Extension Points

1. **Agent Runtime** - Pluggable agent execution engine
2. **Workflow Engine** - Visual workflow builder (authoring: done, MP07) + execution (MP08) + `orchestration` node (MP13)
3. **Model Router** - Multi-provider LLM routing
4. **Tool System** - Extensible tool framework
5. **MCP** - Model Context Protocol integration
6. **Multi-Agent Orchestration (MP13)** - `apps/api/src/openagent/orchestration/` (runs, task graph, planner + validation, assignment, delegation, handoff, budgets, supervisor, executor) with tables `orchestration_runs/tasks/dependencies`, `agent_relationships/capabilities/messages/handoffs/conflicts`, budget ledgers, and events; API under `/organizations/{id}/orchestrations`; worker queue `orchestration`; frontend `/orchestrations` workspace + `/agents/organization`. See `docs/multi-agent-architecture.md`.
7. **Management Layer (MP14)** - `apps/api/src/openagent/management/` (manager profiles + authority, contracts, formal delegation lifecycle, structured handoff + context manifests, review/revision/quality gates, escalation chains + human hook, dynamic teams + charters, collaboration/negotiation/commitments, availability/capacity, manager loop, routed messaging, prompt builder; boundaries for MP15/MP19/MP20); tables `manager_profiles/agent_contracts/delegation_requests/agent_commitments/handoff_packages/review_results/escalations/agent_departments/dynamic_teams/team_charters/dynamic_team_memberships/agent_availability/agent_capacity/plan_versions/collaboration_requests/manager_decisions`; API under `/organizations/{id}/management` + SSE stream; `manager_tick` worker job; frontend `/management`, escalation center, org chart, workspace management tabs. See `docs/manager-architecture.md`.
3. **Model Router** - Multi-provider LLM routing
4. **Tool System** - Extensible tool framework
5. **MCP** - Model Context Protocol integration
6. **Memory** - Vector + relational memory
7. **Browser (MP16)** - `apps/api/src/openagent/browser/` (service, security gates, observations, tools, client) + `packages/browser/` (provider-neutral Playwright/Chromium engine: sessions, tasks, actions, extraction, hardening, research, vision hooks, artifacts, telemetry, SDK) + API `/api/v1/browser/*` + frontend `/browser` workspace & `/browser/playground`; DB tables `browser_*` (migration `015`); tools `browser.*` registered in Tool Runtime; workflow nodes `browser_agent/action/extract`. See `docs/browser/overview.md`.
8. **Code Agent (MP17)** - `apps/api/src/openagent/code/` (service, providers, safe git, intelligence/indexing, patches, review, security, tools, client) + API `/api/v1/repositories/*` & `/api/v1/code/*` + frontend `/code` workspace & `/code/playground` + SDK `code` namespace (`packages/sdk`, `CodeClient`); DB tables `repositories/code_workspaces/code_tasks/code_task_steps/code_file_index/code_symbols/code_references/code_dependencies/code_chunks/code_embeddings/code_execution_runs/code_test_results/code_reviews/code_review_findings/code_patches/code_commits/code_pull_requests` (migration `016`); tools `code.*` registered in Tool Runtime; workflow nodes `code_agent/search/read/patch/test/lint/review`, `git_commit`, `create_pr` (validator + executors + frontend catalog); docs `docs/code-agent/*`; examples `examples/code-agent/*`. Execution profiles + `CodeExecutionProvider` form the MP18 sandbox boundary. See `docs/code-agent/overview.md`.
9. **Sandbox (MP18)** - `apps/api/src/openagent/sandbox/` (policy engine, profiles, docker/local providers + k8s stub, manager, tools, client, code adapter, settings + prod checks) + API `/api/v1/sandboxes/*`, `/api/v1/sandbox-profiles/*`, `/api/v1/sandbox-executions/*` + frontend `/sandbox` console & `/sandbox/playground` + SDK `sandbox` namespace (`packages/sdk`, `SandboxClient`); DB tables `sandboxes/sandbox_profiles/sandbox_executions/sandbox_leases/sandbox_artifacts/sandbox_events/sandbox_image_policies` (migration `017`); tools `sandbox.*` registered in Tool Runtime; Code Agent execution migrated to Sandbox via `SandboxCodeExecutionProvider` (host runner is explicit dev-only fallback, refused in production); images `infrastructure/docker/sandbox/`; static gate `scripts/sandbox_security_gate.py` (CI); docs `docs/sandbox/*`; examples `examples/sandbox/*`. See `docs/sandbox/overview.md`.
10. **Approval & Guardrails (MP19)** - `apps/api/src/openagent/approvals/` (types/state machine, taxonomy, risk engine, declarative policy engine, hashing/redaction, ApprovalEngine, central guard, runtime integrations, escalation, delegation, notifications, metrics, config) + API `/api/v1/organizations/{id}/approvals|approval-policies|approval-delegations` + approval-bound resume for WAITING workflow executions + `approval_id` verification in tool/browser/code/sandbox execution paths (client `approved` booleans are never proof); DB tables `approval_steps/decisions/policies/policy_versions/escalations/action_snapshots/events/delegations` (migration `018`); frontend `/approvals` center + detail with danger confirmation + policy simulator hook; SDK `approvals` namespace; docs `docs/security/approval-system|guardrails|risk-engine|high-risk-actions|human-in-the-loop`, `docs/architecture/approval-architecture`, `docs/api/approvals`; examples `examples/approvals/*`.
11. **Evaluator & Quality Control (MP20)** - `apps/api/src/openagent/evaluator/` (types/lifecycle, criteria + versioned rubrics, tamper-resistant evidence, deterministic verifiers, provider-neutral LLM judge via Model Router, scoring/consensus/decisions, EvaluatorEngine, SelfCorrectionEngine with budgets + loop detection, quality gates, benchmarks + regression, runtime integrations, metrics, config) + API `/api/v1/organizations/{id}/evaluations|evaluation-rubrics|quality-gates|benchmarks|correction-plans|quality` + verify hooks on agents/runs, workflows/executions, tools (incl. MCP), code tasks, browser tasks, orchestration reviews + workflow nodes `verify/evaluate/assert/quality_gate/retry/correct` (validator + executors + frontend catalog; human review reuses `approval` node + MP19); DB tables `evaluation_evidence/results/disagreements/rubrics/rubric_versions/verification_checks/correction_plans/attempts/feedback/quality_gates/benchmarks/benchmark_runs` + `evaluations` MP20 columns (migration `019`); frontend `/quality` center + evaluation detail (evidence/checks/votes/timeline/feedback) + gates + benchmarks; SDK `evaluator` namespace (no force-success APIs); docs `docs/ai/evaluator-engine|verification|self-correction|quality-gates|evidence-system|agent-evaluation|model-evaluation`, `docs/architecture/evaluation-architecture`, `docs/api/evaluations`; examples `examples/evaluator/*`.
12. **Universal Integrations (MP21)** - `apps/api/src/openagent/connectors/` (types/lifecycles, manifest validation, registry + capability discovery, Fernet credential crypto, SSRF guard, shared HTTP stack with retries/circuit-breaker/pooling, OAuth2 manager with PKCE, webhook verify/normalize, polling cursors, rate limits, pagination caps, mapping engine, normalized resources, ConnectorEngine pipeline, guarded SQL connector, metrics, config) + 11 official providers (gmail/slack/discord/telegram/github/gitlab/google_calendar/google_drive/notion/hubspot/postgres) + generic HTTP executor for declarative custom connectors + API `/api/v1/organizations/{id}/connectors|integration-connections|credentials|connector-webhooks` + signature-authenticated `POST /api/v1/webhooks/:connector/:connection/:endpoint` + Tool Runtime delegation (`connector:*` tools, single engine-owned gate) + workflow nodes `connector_action/trigger/search/resource` (validator + executors + frontend catalog) + agent discovery search (incl. MCP origins); DB tables `connectors/versions/capabilities/actions/triggers/resources/connections/permissions/webhooks/events/health/usage/cursors` + legacy `integrations` migration (migration `020`); frontend `/integrations` + catalog + detail + connection + custom API builder + webhooks + settings credentials; SDK `integrations` namespace + `packages/connector-sdk`; docs `docs/integrations/*`, `docs/api/integrations`; examples `examples/integrations/*`; generator `scripts/connector-new.py`.
8. **Sandbox** - Secure code execution
9. **Evaluator** - Agent/workflow evaluation
10. **Evaluator** - Agent/workflow evaluation
11. **Marketplace (MP22 foundation)** - `apps/api/src/openagent/packages/` (types, semver + constraints, manifest, config schema, dependency resolver, security scanner, signing, validation engine, export/import, installer with preview/update/rollback, catalog abstraction, resource graph, telemetry, programmatic builders) + tables `reusable_packages/package_versions/package_resources/package_dependencies/skills/skill_versions/presets/preset_versions/package_installations/installation_resources/package_signatures/package_security_scans/package_validation_results/package_forks/package_update_plans/package_categories/publisher_profiles` (migration `021`) + API `/organizations/{id}/packages|skills|presets|catalog|installations` + frontend Template Center `/templates`, detail `/templates/[slug]`, `/skills`, `/presets`, `/settings/packages`, catalog-backed `/marketplace` + SDK `packages` namespace + CLI `scripts/openagent_package.py` + official samples `marketplace/packages/*`. See `docs/packages/`.
12. **Marketplace, Publishers & Commerce Foundation (MP23)** - `apps/api/src/openagent/marketplace/` (listing lifecycle + transitions, publisher verification, policy engine + license-compat heuristics, provider-neutral search query, factual ratings, review eligibility + anti-abuse, content sanitizer + URL safety, content-addressed distribution with archive bomb/traversal guards, billing-provider protocol with disabled default, entitlement gates, registry trust, transparent recommendations, explainable health, notification fan-out with prefs) + tables `marketplaces/policies/listings/listing_versions/publisher_members/publisher_followers/categories/tags/listing_tags/reviews/responses/review_reports/favorites/events/analytics_daily/security_advisories/package_revocations/distribution_artifacts/locations/artifact_downloads/marketplace_reports/moderation_actions/products/prices/entitlements/revenue/payouts/billing_webhook_events/notifications/notification_prefs/registries` + extended `publisher_profiles` (migration `022`) + API `/marketplace|/listings|/publishers|/reviews|/favorites|/security-advisories|/marketplace-reports|/master/marketplace|/distribution|/commerce|/publisher|/notifications` + worker queue `marketplace` + frontend `/marketplace` (+search, category, detail, publisher), `/publisher/*` studio, `/master/marketplace` console + SDK `marketplace/publishers/listings/reviews/advisories/distribution` namespaces + CLI `marketplace|publisher` groups + dev seed `scripts/seed_marketplace.py`. Real payments/payouts deferred to MP24. See `docs/marketplace/`.
13. **Cloud Registry, Billing, Entitlements & Creator Revenue (MP24)** - `apps/api/src/openagent/commerce/` (money/minor-units, provider-neutral `BillingProvider`/`PayoutProvider`/`TaxProvider` + deterministic mock + disabled default, registry client with local/mock providers, entitlement engine, quota/usage math, ledger/fee math, coupon validation, webhook verification) + `service.py` orchestration (verified-webhook-only payments, dual-written entitlements, idempotent everything, audited everything) + tables `billing_customers/checkout_sessions/payments/payment_events/subscriptions/commerce_entitlements/usage_meters/records/summaries/quotas/quota_usage/invoices/lines/refunds/disputes/credit_accounts/transactions/fee_policies/creator_ledger_entries/commerce_payouts/payout_events/promotions/promo_codes/redemptions/tax_calculations/registry_syncs/registry_cache/registry_credentials` + extended MP23 tables (migration `023`, extended `ProductType`/`PricingModel` enums) + API `/registries|/products|/prices|/checkout|/subscriptions|/entitlements|/usage|/quotas|/invoices|/refunds|/disputes|/credits|/revenue|/payouts|/promotions|/billing|/webhooks/billing/{provider}|/master/billing` + worker queue `commerce` (usage aggregation, entitlement expiry, webhook backlog, payout sweep) + frontend `/settings/registries|/settings/billing|/settings/usage`, `/publisher/products|/publisher/revenue`, `/master/billing` + SDK `registries/billing/products/prices/checkout/subscriptions/entitlements/usage/quotas/invoices/revenue/payouts` namespaces + CLI `scripts/openagent_commerce.py` + RBAC `billing|payout|registry` resources. See `docs/commerce/`, `docs/billing/`, `docs/entitlements/`, `docs/usage/`, `docs/creator-monetization/`, `docs/payouts/`, `docs/registries/`.
11. **Billing** - Usage metering
12. **Enterprise** - SSO, RBAC, audit logs

## MP28 Developer Platform (Extension Architecture)

Single canonical extension architecture (§3, §13): one extension type
registry (20 types), one permission catalog, one trust model. All extension
kinds are entries in `apps/api/src/openagent/developer/types.py` — never
parallel plugin systems. Guides: `docs/developers/`.

```
Developer
   ├─► SDK (@openagent/sdk TS · openagent-sdk Python)
   ├─► CLI (openagent: init/dev/validate/test/build/package/publish/deploy/rollback)
   └─► Portal (web: /templates /skills /marketplace /publisher)
                     │
                     ▼
   FastAPI: /organizations/{id}/developer/* + /organizations/{id}/extensions/*
   validate → test → package → scan → compat → sign → publish → install
                     │
        ┌────────────┼────────────┬──────────────┐
        ▼            ▼            ▼              ▼
   Tool Runtime   Sandbox   ConnectorEngine  Model Router
   (tool:execute) (sandbox: (OAuth/SSRF       (model:invoke,
                   execute)  guard)            LLM judge)
        └────────────┴────────────┴──────────────┘
                     ▼
   PostgreSQL (extension_* tables) · Redis queues (orchestration/marketplace/commerce)
   Audit log ← every lifecycle transition · Security events
```

### Backend modules (`apps/api/src/openagent/developer/*`)

| Module | Responsibility |
|--------|----------------|
| `types.py` | Extension-type registry (20), permission catalog, trust levels, lifecycle, `DEVELOPER_EVENTS` (20), compat matrix 1.x |
| `manifest.py` | `ExtensionManifest` schema for `openagent.yaml`; rejects unknown types/permissions, embedded secret values, unsafe network declarations |
| `permissions.py` | `check_permissions` enforcement + trust model (trust never bypasses authorization; no self-grant) |
| `security.py` | Static scans, secret detection (`SECRET_PATTERNS`), install-hook safety; `blocks_publish`/`blocks_install` |
| `signing.py` | Ed25519 signing/verification, `key_id` rotation, revocation at verify time |
| `packaging.py` | Deterministic `.oaext` archives, checksums, SBOM, provenance |
| `versioning.py` | Semver, constraints, `check_compatibility`, `DEPRECATIONS` |
| `service.py` | Lifecycle orchestration: validate→test→build→package→scan→compat→sign→deploy→health→activate; quarantine/rollback |
| `mocks.py` | Deterministic offline test mocks (LLM, Tool, Connector, MCP, Browser, Sandbox, Memory, Workflow, Agent, Webhook, Storage) |
| `config.py` | `DeveloperSettings` (`OPENAGENT_DEV_*`; secret override forbidden in production), deployment stages |
| `errors.py` | Public error taxonomy (16 codes), webhook HMAC-SHA256 sign/verify (`v1`, 300s replay window) |

### SDK / CLI packages

| Package | Role |
|---------|------|
| `packages/sdk` (`@openagent/sdk`) | Public TS SDK: agents/tools/workflows/connectors/MCP/memory/evaluations/extensions/events; Bearer auth, org scoping, idempotency keys |
| Python `openagent-sdk` | Same contract for Python runtimes (auth, pagination, idempotency, webhook verify) |
| `packages/cli` (`openagent`) | Full lifecycle CLI: init/login/logout/whoami/dev/validate/test/build/package/publish/deploy/rollback + resource groups; JSON/CI mode, exit codes 0–6 |
| `packages/connector-sdk` | Connector manifest validation + scaffolding (server re-validates authoritatively) |
| Extension-sdk builder API | `defineAgent/defineTool/defineWorkflowNode/defineConnector/defineMCPServer/defineSkill/defineEvaluator` used by all examples/templates |

### DB tables (`apps/api/src/openagent/db/models/developer.py`)

`developer_projects`, `developer_project_members`, `developer_environments`,
`extension_definitions`, `extension_versions`, `extension_installations`,
`extension_deployments`, `developer_webhooks`, `developer_webhook_deliveries`,
`extension_analytics_daily`, `extension_trust_records`. All rows
organization-scoped (global rows readable cross-tenant only via the catalog
path with visibility checks).

### Routes (`apps/api/src/openagent/api/v1/developer.py`)

- `/organizations/{id}/developer/projects[. ..]` — projects, members, environments
- `/organizations/{id}/developer/environments`, `/developer/webhooks`, `/developer/events`, `/developer/usage`
- `/organizations/{id}/extensions[. ..]` — CRUD, versions, validate/test/package/artifact/publish/sign/install/disable/quarantine/rollback
- `/api/v1/developer/sdk|/errors|/events` — public metadata (no auth)

## Database Design Principles

- UUID primary keys
- `created_at`, `updated_at` on all tables
- Soft deletes (`deleted_at`) where appropriate
- JSONB for flexible metadata
- Organization-scoped tables include `organization_id`
- Audit trails for sensitive operations
- Alembic for migrations

## Security Baseline

- CORS configured per environment
- Security headers (CSP, HSTS, etc.)
- Input validation at API boundaries
- No stack traces in production errors
- Secrets only in environment variables
- Dependency scanning in CI