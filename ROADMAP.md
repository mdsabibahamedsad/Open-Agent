# Open-Agent Roadmap

Phases marked from the actual implementation in this repository.
`ARCHITECTURE.md` documents the current state of each subsystem.

## Completed

- [x] **Phase 01 — Foundation**: pnpm + Turborepo monorepo, Docker Compose, CI
- [x] **Phase 02 — Database & Persistence**: PostgreSQL + SQLAlchemy 2.0, Alembic migrations (27 revisions, single head)
- [x] **Phase 03 — Authentication & Authorization**: sessions, API keys, service accounts, RBAC/ABAC
- [x] **Phase 04 — Agent Runtime**: agent execution engine, runs, task graphs
- [x] **Phase 05 — Workflow Engine**: visual builder, versioned definitions, executions
- [x] **Phase 06 — Model Router**: multi-provider routing, adapters
- [x] **Phase 07 — Tool Runtime**: typed tools, policies, risk levels, execution events
- [x] **Phase 08 — MCP**: servers, tools, resources, prompts, policies
- [x] **Phase 09 — Multi-Agent Orchestration**: runs, delegation, handoff, budgets, supervisor
- [x] **Phase 10 — Management Layer**: managers, contracts, reviews, escalations, dynamic teams
- [x] **Phase 11 — Memory**: vector + relational memory, policies, consolidation
- [x] **Phase 12 — Browser Automation**: sessions, Playwright engine, policies, artifacts
- [x] **Phase 13 — Code Agent**: repositories, workspaces, patches, reviews, PR drafts
- [x] **Phase 14 — Sandbox**: policy engine, Docker isolation, profiles, leases, artifacts
- [x] **Phase 15 — Human Approval**: risk engine, policies, escalation, delegation
- [x] **Phase 16 — Evaluator**: rubrics, verification, self-correction, quality gates, benchmarks
- [x] **Phase 17 — Universal Integrations**: 11 official connectors, OAuth2, webhooks, polling
- [x] **Phase 18 — Templates/Skills/Presets**: versioned packages, validation, install/rollback
- [x] **Phase 19 — Marketplace**: listings, publishers, reviews, moderation
- [x] **Phase 20 — Billing & Commerce**: provider-neutral billing, entitlements, quotas, payouts
- [x] **Phase 21 — Cloud Runtime**: workers, queues, placements, artifacts, autoscaling signals
- [x] **Phase 22 — Operations**: health, alerts, incidents, deployments, audit
- [x] **Phase 23 — Enterprise Identity**: SSO, SCIM, zero-trust policies, devices, controls
- [x] **Phase 24 — Developer Platform (MP28)**: TS + Python SDKs, CLI, extension SDK, manifest/packaging/signing, projects, local registry, developer portal, 14 examples, 10 starter templates

## In Progress

- [ ] **Phase 25 — Production Reliability & Observability Hardening**
  Disaster recovery, SLOs, load/chaos validation, backup/restore verification.

## Planned

- [ ] **Phase 26 — Production Release**
  Release engineering, versioned distributions, upgrade paths, long-term support policy.
- [ ] **Desktop app** (`apps/desktop/` is currently an empty placeholder)
- [ ] **Docs site** (`apps/docs/` is currently an empty placeholder)
- [ ] Live (non-mock) billing provider activation — interfaces exist, provider is disabled by default
