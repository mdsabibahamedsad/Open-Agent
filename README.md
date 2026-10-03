# Open-Agent

### The Open-Source Operating System for AI Agents

Build, orchestrate, automate, and deploy autonomous AI workforces.

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/mdsabibahamedsad/Open-Agent.svg)](https://github.com/mdsabibahamedsad/Open-Agent/stargazers)
[![GitHub issues](https://img.shields.io/github/issues/mdsabibahamedsad/Open-Agent.svg)](https://github.com/mdsabibahamedsad/Open-Agent/issues)
[![CI](https://github.com/mdsabibahamedsad/Open-Agent/actions/workflows/ci.yml/badge.svg)](https://github.com/mdsabibahamedsad/Open-Agent/actions)

[Documentation](docs/) · [Architecture](ARCHITECTURE.md) · [Roadmap](ROADMAP.md) · [Issues](https://github.com/mdsabibahamedsad/Open-Agent/issues) · [Contributing](CONTRIBUTING.md)

> Open-Agent is an open-source AI Workforce Operating System for building autonomous agents, visual workflows, tools, MCP integrations, browser automation, coding agents, persistent memory, multi-agent teams, secure execution environments, and AI-powered automation.

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Architecture](#architecture)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Usage](#usage)
- [Project Structure](#project-structure)
- [Development](#development)
- [What Is OpenAgent?](#what-is-openagent)
- [Product Vision](#product-vision)
- [Comparison With Traditional Automation (n8n-style)](#comparison-with-traditional-automation-n8n-style)
- [Core Capabilities](#core-capabilities)
- [Security and Privacy](#security-and-privacy)
- [Installation](#installation)
- [First-Run Setup](#first-run-setup)
- [CLI Reference](#cli-reference)
- [Configuration](#configuration)
- [AI Model Setup](#ai-model-setup)
- [Browser Setup](#browser-setup)
- [MCP Setup](#mcp-setup)
- [Workflow Examples](#workflow-examples)
- [Agent Examples](#agent-examples)
- [Troubleshooting](#troubleshooting)
- [Doctor, Repair, Update, Backup](#doctor-repair-update-backup)
- [Git and GitHub Integration](#git-and-github-integration)
- [Testing](#testing)
- [Repository Structure and Architecture](#repository-structure-and-architecture)
- [Release Process](#release-process)
- [FAQ](#faq)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [Security](#security)
- [License](#license)

## Overview

Traditional automation executes fixed, deterministic steps. Open-Agent is designed around a different unit of work:

```text
Traditional Automation
        ↓
Deterministic Workflows
        ↓
Open-Agent
        ↓
AI Workers + Workflows + Tools + Memory + Browser + Code + MCP
```

Agents reason, plan, and use tools; workflows provide deterministic structure where you need it; memory, browser access, code execution, and integrations give agents real capabilities — all behind policy, human approval, sandboxing, and audit logging.

## Features

Status reflects the actual implementation in this repository.

| Capability                   | Status | Notes                                                                                                                               |
| ---------------------------- | ------ | ----------------------------------------------------------------------------------------------------------------------------------- |
| AI Agents                    | ✅     | Runtime, versions, runs, lifecycle                                                                                                  |
| Workflow Automation          | ✅     | Visual builder, versioned definitions, executions                                                                                   |
| Model Routing                | ✅     | Multi-provider routing + adapters                                                                                                   |
| Tool Runtime                 | ✅     | Typed tools, policies, risk levels, execution events                                                                                |
| MCP                          | ✅     | Servers, tools, resources, prompts, policies                                                                                        |
| Multi-Agent Orchestration    | ✅     | Runs, delegation, handoff, budgets                                                                                                  |
| Team Management              | ✅     | Managers, contracts, reviews, escalations                                                                                           |
| Persistent Memory            | ✅     | Scoped memory, policies, consolidation                                                                                              |
| Browser Automation           | ✅     | Sessions, policies, artifacts                                                                                                       |
| Coding Agent                 | ✅     | Repos, workspaces, patches, reviews, PR drafts                                                                                      |
| Sandbox Execution            | ✅     | Profiles, Docker isolation, leases, artifacts                                                                                       |
| Human Approval               | ✅     | Risk engine, policies, escalation, delegation                                                                                       |
| Evaluation                   | ✅     | Rubrics, verification, self-correction, quality gates                                                                               |
| Integrations                 | ✅     | 11 official connectors (Gmail, Slack, Discord, Telegram, GitHub, GitLab, Calendar, Drive, Notion, HubSpot, Postgres) + generic HTTP |
| Templates / Skills / Presets | ✅     | Versioned packages, validation, install/rollback                                                                                    |
| Marketplace                  | ✅     | Listings, publishers, reviews, moderation                                                                                           |
| Billing & Metering           | 🚧     | Provider-neutral interfaces + disabled-by-default provider; full ledger/entitlement engine present                                  |
| Cloud Runtime                | ✅     | Workers, queues, placements, artifacts                                                                                              |
| Enterprise Security          | ✅     | SSO, SCIM, RBAC/ABAC, zero-trust policies, audit                                                                                    |
| Developer SDKs               | ✅     | TypeScript + Python + REST client                                                                                                   |
| CLI                          | ✅     | `openagent` — scaffold, validate, test, package, publish, deploy                                                                    |
| Extension System             | ✅     | 20 extension types, manifest, signing, local registry                                                                               |
| Developer Portal             | ✅     | Projects, extensions, API explorer, usage                                                                                           |
| Desktop App                  | 🗺️     | Planned (`apps/desktop/` is an empty placeholder)                                                                                   |

## Architecture

```text
                    ┌─────────────────────────┐
                    │      Open-Agent UI      │
                    │  Web + Developer Portal │
                    └────────────┬────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │      FastAPI (/api/v1)  │
                    └────────────┬────────────┘
                                 │
          ┌──────────────────────┼──────────────────────┐
          │                      │                      │
   ┌──────▼──────┐       ┌───────▼──────┐       ┌──────▼──────┐
   │ Agent Engine│       │Workflow Engine│       │ Model Router│
   │ + Teams     │       │ + Approvals   │       │ + Adapters  │
   └──────┬──────┘       └───────┬──────┘       └──────┬──────┘
          │                      │                      │
          └──────────────────────┼──────────────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │      Tool Runtime       │
                    └──────┬─────┬─────┬─────┘
                           │     │     │
                         MCP  Browser Sandbox
                           │     │     │
                    ┌──────▼─────▼─────▼──────┐
                    │ Memory / Integrations   │
                    │ Marketplace / Billing   │
                    └──────────────────────────┘
```

Background execution runs on Redis-backed workers (`apps/worker`).
PostgreSQL is the system of record (27 Alembic migrations, one canonical model per domain).
See [ARCHITECTURE.md](ARCHITECTURE.md) for the full technical document.

## Quick Start

**Normal user (no tech setup):** download `OpenAgent-Setup.exe` from Releases,
install, launch — first-run setup is automatic. Details: [INSTALLATION](docs/INSTALLATION.md).

**Developer:**

```cmd
git clone https://github.com/mdsabibahamedsad/Open-Agent.git
cd Open-Agent
setup.cmd
openagent-dev.cmd doctor
```

Prerequisites (developer mode only): Git, Node.js 20+, pnpm 8.15+, Python 3.11+, Docker & Docker Compose.
Run `pnpm doctor` at any time to verify your machine. Full guides: [quick-start](docs/getting-started/quick-start.md) · [Windows](docs/getting-started/windows.md) · [macOS](docs/getting-started/macos.md) · [Linux](docs/getting-started/linux.md) · [troubleshooting](docs/getting-started/troubleshooting.md).

```bash
git clone https://github.com/mdsabibahamedsad/Open-Agent.git
cd Open-Agent

cp .env.example .env
# Edit .env — at minimum set SECRET_KEY and ENCRYPTION_KEY
# (generate with: openssl rand -hex 32)

docker compose up -d
```

- Web: http://localhost:3000
- API: http://localhost:8000
- API docs (development): http://localhost:8000/docs

### Run modes

| Mode                 | Command                               | Details                                                |
| -------------------- | ------------------------------------- | ------------------------------------------------------ |
| Docker (recommended) | `docker compose up --build`           | [docker guide](docs/getting-started/docker.md)         |
| Guided native        | `pnpm setup` then `pnpm dev:local`    | [non-docker guide](docs/getting-started/non-docker.md) |
| Hybrid               | `pnpm infra:up` then `pnpm dev:local` | [hybrid guide](docs/getting-started/hybrid.md)         |
| Local AI             | `ollama serve` + provider config      | [local-ai guide](docs/getting-started/local-ai.md)     |

Supported: Windows (PowerShell/WSL2), macOS (Apple Silicon + Intel), Linux — each with Docker and non-Docker paths. pnpm 8.15 is canonical; npm can run root scripts after `pnpm install`.

### Automate locally — no Docker required

The CLI is also a local-first automation platform (SQLite/JSON + Ollama + local
workflow engine). No Docker, no cloud account needed:

```bash
npm install -g @openagent/cli   # official package (NOT `openagent` — that name
                                # is an unrelated registry placeholder)

openagent init

openagent start
```

**Windows, zero terminal:** download `OpenAgent-Setup.exe` from
[releases](https://github.com/mdsabibahamedsad/Open-Agent/releases),
double-click, click **Install OpenAgent** — runtime, database, local AI,
browser, shortcuts, health check and dashboard are all configured
automatically. Full guide: [one-click Windows install](docs/getting-started/windows-one-click.md).
`openagent setup --yes` performs the same flow from a shell
(`--offline` and `--skip-model` supported).

Then you get:

```text
Dashboard → http://localhost:5678
API       → http://localhost:5678/api
Webhook   → http://localhost:5678/webhook/:workflowId
```

Quick-start example (Schedule → Web Search → AI Agent → File):

```bash
openagent workflow list
openagent workflow run daily-news-digest
openagent logs --limit 5
openagent doctor
```

`openagent init` creates `.openagent/` (`agents/ workflows/ nodes/ memory/
credentials/ logs/ schedules/ executions/ workspace/`) plus `openagent.config.ts`.
Workflows are plain JSON, so they version-control cleanly. With Ollama running
(`ollama run qwen2.5`), AI nodes use your local model automatically; without a
reachable model they degrade to a clearly-labeled heuristic fallback instead of
failing. See `openagent ask --help`, `openagent workflow generate --help`, and
`openagent autonomous --help` for AI-driven automation.

### Build an extension in minutes

```bash
npm install -g @openagent/cli   # once published; or: pnpm --filter @openagent/cli build

openagent init --kind tool --language ts --name my-tool --yes
cd my-tool
openagent validate
openagent test
openagent package
openagent publish
```

### Use the SDKs

TypeScript:

```ts
import { OpenAgent } from "@openagent/sdk";

const client = new OpenAgent({ apiKey: process.env.OPENAGENT_API_KEY });

const agent = await client.agents.create({
  name: "Research Agent",
  model: "smart",
  instructions: "Research and summarize information.",
});
```

Python:

```python
from openagent import OpenAgent

client = OpenAgent(api_key=os.environ["OPENAGENT_API_KEY"])

agent = client.agents.create(
    name="Research Agent",
    model="smart",
)
```

## Configuration

All settings come from environment variables (see [.env.example](.env.example)). The main groups:

| Group         | Variables                                          | Notes                                                         |
| ------------- | -------------------------------------------------- | ------------------------------------------------------------- |
| App           | `OPENAGENT_ENV`, `LOG_LEVEL`, `API_URL`, `WEB_URL` | `development` enables `/docs`                                 |
| Database      | `DATABASE_URL`                                     | PostgreSQL 15+ (`postgresql+asyncpg://…`)                     |
| Queue/cache   | `REDIS_URL`                                        | Redis 7+                                                      |
| Security      | `SECRET_KEY`, `ENCRYPTION_KEY`                     | Min 32 chars; never commit real values                        |
| CORS          | `CORS_ORIGINS`                                     | Allowed web origins                                           |
| LLM providers | Provider keys per `docs/`                          | Model Router selects across configured providers              |
| Local models  | Ollama-compatible endpoint                         | Supported via Model Router adapters — see `docs/`             |
| Browser       | Playwright/Chromium settings                       | Policies gate navigation and extraction                       |
| Sandbox       | Docker image policies, profiles                    | `TEST`/`BUILD` profiles; host execution refused in production |

## Usage

- **Agents** — autonomous workers with instructions, tools, memory, budgets, and run history.
- **Workflows** — deterministic graphs with custom nodes, approvals, and quality gates.
- **Tools** — typed capabilities with schemas, risk levels, and policies; every call flows through the Tool Runtime.
- **MCP** — connect Model Context Protocol servers for tools, resources, and prompts.
- **Memory** — scoped persistent memory with importance, conflicts, and consolidation.
- **Multi-agent** — orchestrate teams with delegation, handoff contracts, and spend budgets.
- **Sandbox** — isolated code execution with profiles, leases, and artifact capture.
- **Integrations** — OAuth/API-key/webhook connectors with health checks and rate limits.
- **Marketplace** — publish and install versioned agents, tools, connectors, and templates.

Start with the 14 runnable examples in [`examples/`](examples/) and the 10 starter templates in [`templates/`](templates/).

## Project Structure

```text
Open-Agent/
├── apps/
│   ├── web/          # Next.js 14 dashboard + developer portal
│   ├── api/          # FastAPI backend (27 migrations, 68 test files)
│   └── worker/       # Redis-backed background jobs
├── packages/         # 25 workspace packages
│   ├── sdk/          # TypeScript SDK (OpenAgent class)
│   ├── api-client/   # Stable REST client
│   ├── sdk-types/    # Canonical public types
│   ├── extension-sdk/# defineAgent/defineTool/… builders
│   ├── developer-tools/ # validator, scanner, docgen, mocks
│   ├── cli/          # `openagent` command
│   ├── python-sdk/   # `openagent` PyPI package
│   ├── agent-runtime/ workflow-engine/ model-router/
│   ├── tool-system/ mcp/ memory/ browser/ sandbox/
│   ├── evaluator/ connector-sdk/ config/ core/
│   ├── types/ logger/ database/ security/
├── integrations/     # Provider implementations
├── marketplace/      # Official sample packages
├── examples/         # 14 runnable examples
├── templates/        # 10 starter templates
├── tests/            # Cross-cutting tests
├── docs/             # Guides, API, architecture, security
├── infrastructure/   # Docker, deployment assets
├── scripts/          # Operational scripts (packaging, commerce, ops)
├── .github/workflows/# CI (Node + Python + web build)
├── ARCHITECTURE.md  ROADMAP.md  CHANGELOG.md
├── CONTRIBUTING.md  SECURITY.md  CODE_OF_CONDUCT.md
└── LICENSE (MIT)
```

`apps/desktop/` holds the desktop controller (lifecycle, supervision, updates, first-run wizard); `apps/docs/` hosts the documentation site.

## Development

```bash
git clone https://github.com/mdsabibahamedsad/Open-Agent.git
cd Open-Agent

pnpm setup         # deps + .env with fresh dev secrets (never overwrites .env)
pnpm doctor        # verify environment (read-only)

# Option A — Docker for everything
pnpm dev           # or: docker compose up --build

# Option B — hybrid: infra in Docker, code native
pnpm infra:up
pnpm db:setup      # migrate + seed
pnpm dev:local     # web + api + worker, one banner, Ctrl+C stops all

# Option C — fully native (needs local Postgres 15+ + Redis 7+)
pnpm db:setup
pnpm dev:local
```

Manual equivalents (what the scripts do under the hood):

```bash
cp .env.example .env
docker compose up -d          # Postgres + Redis

# Backend
cd apps/api
python -m venv .venv && .venv/Scripts/activate   # Windows; use `source` on Unix
pip install -e ".[dev]"
alembic upgrade head
uvicorn openagent.main:app --reload --port 8000

# Frontend (new shell)
cd apps/web && pnpm dev

# Worker (new shell)
cd apps/worker && python -m worker.main
```

Verify:

```bash
pnpm typecheck     # all workspace packages
pnpm test          # all workspace tests
cd apps/api && pytest -q
cd apps/web && npx tsc --noEmit
```

## What Is OpenAgent?

OpenAgent is designed as an AI-native automation platform: deterministic
workflow structure where you need repeatability, plus AI agents that can
reason, plan, use tools, observe results, correct course, and remember —
all local-first, behind policy, approvals, sandboxing, and audit logging.

## Product Vision

Automation that starts from a **goal**, not a blank canvas:

```text
Traditional node-based automation:

Trigger → Node → Node → Node → Output
(fixed path; every branch drawn by hand)

OpenAgent's model:

Goal → AI reasoning → tool discovery → workflow planning
→ execution → observation → correction → memory → final result
(deterministic nodes where it matters; agents where judgment matters)
```

Compared with traditional node-based automation, OpenAgent focuses more
heavily on agent behavior (planning, tool use, recovery) while keeping
workflows as the durable, auditable substrate. Potential advantages include
faster builds from natural language, self-recovery at runtime, and local
execution without forced cloud dependence. Trade-offs include less
step-by-step predictability when agents act autonomously, and higher local
compute needs for capable models — which is why approvals, budgets, and the
human-readable execution log exist.

## Comparison With Traditional Automation (n8n-style)

| Capability | Traditional node automation (e.g. n8n) | OpenAgent |
|---|---|---|
| Visual workflows | Implemented, mature | Implemented (`apps/web` builder + versioned definitions) |
| AI agents | Add-on nodes | Implemented (first-class runtime, runs, budgets) |
| MCP | Varies by version | Implemented (servers, tools, resources, CLI mgmt) |
| Local-first execution | Usually server/cloud-oriented | Implemented (SQLite/JSON engine, no Docker needed) |
| CLI | Limited or none | Implemented (full `openagent` CLI, any directory) |
| Desktop app | Usually none | In Progress (controller + Windows installer; no Electron shell) |
| Browser automation | Varies | Implemented (Playwright engine, CLI-managed) |
| Memory | Varies | Implemented (scoped persistent memory + search) |
| Plugin system | Mature registries | Implemented (registry, `.oaext` packages, marketplace) |
| Deployment | Self-host/cloud | In Progress (installer + portable + Docker; cloud planned) |

Status labels above reflect this repository. OpenAgent is not claimed to
match any other product feature-for-feature.

## Core Capabilities

- **AI workflow automation** — versioned DAG definitions, schedules, approvals, quality gates; generate from prompts (`openagent workflow generate "…"`) or build visually.
- **AI agents** — `openagent agent create --name X`, `agent run <id> --input …`; models, system prompts, tools, memory, iteration budgets.
- **Autonomous execution** — `openagent autonomous "goal" --max-steps 10`: plan → act → observe → retry, ending with `FINAL:`.
- **MCP** — `openagent mcp {list,add,remove,test,doctor}` against local `.openagent/mcp.json` or server catalog.
- **Browser automation** — `openagent browser {doctor,install,update}`; Playwright Chromium managed for you.
- **Local AI** — `openagent model {detect,list,install,use,doctor}`; Ollama auto-detected, hardware profile (LOW/BALANCED/POWER) picks the default model; cloud via `OPENAI_API_KEY`, hybrid supported.
- **Cloud AI** — OpenAI-compatible endpoints through the model router; keys stay in local config, never in source.
- **Memory** — `openagent memory {get,set,search}`; scoped, persistent, file-backed.
- **Multi-agent architecture** — managers, delegation, handoffs, budgets (see `docs/multi-agent-architecture.md`).
- **Workflow engine** — `packages/workflow-engine`: validation, execution, retries, schedules, artifacts.
- **CLI** — full reference in [docs/CLI.md](docs/CLI.md); works from any directory.
- **Desktop application** — Node controller (`apps/desktop`: lifecycle, supervisor, health, updates, first-run) + Windows installer; opens the dashboard after health checks, shows diagnostics instead of a blank window on backend failure.
- **Plugin system** — `.oaext` deterministic packages (`openagent package`, `inspect`), local registry, marketplace listings.
- **Developer SDK** — TypeScript (`packages/sdk`), Python (`packages/python-sdk`), extension SDK builders, REST API + stable `api-client`.
- **API** — FastAPI (`apps/api`), versioned routes, auto docs at `/docs` in development.

## Security and Privacy

Local-first: workflows, agents, memory, and credentials live under
`%LOCALAPPDATA%\OpenAgent\data` (or `OPENAGENT_DATA_DIR`), never in the repo.
Secret scanning blocks publishes and auto-pushes; logs redact credentials;
`.gitignore` rules are generated by `openagent git --init`. See
[SECURITY.md](SECURITY.md) and [docs/GIT.md](docs/GIT.md).

## Installation

**Normal user:** download `OpenAgent-Setup.exe` from GitHub Releases →
install (per-user, no admin) → launch. First-run wizard: system check →
hardware → AI provider (Local / Cloud / Both / Skip) → workspace → browser →
optional Git → complete. Full guide: [docs/INSTALLATION.md](docs/INSTALLATION.md),
[docs/WINDOWS.md](docs/WINDOWS.md).

**Developer:**

```cmd
git clone https://github.com/mdsabibahamedsad/Open-Agent.git
cd Open-Agent
setup.cmd
openagent-dev.cmd doctor
```

**Portable:** extract `OpenAgent-Portable.zip`, run `bin\openagent.cmd start`.
No global installation of anything. The npm package (`@openagent/cli`) is
optional and developer-only — and only after it is actually published.

## First-Run Setup

`openagent setup` (flags: `--dev`, `--production`, `--minimal`, `--offline`,
`--yes`, `--ai-mode`, `--model`, `--start`) performs system check, port
selection, runtime layout, AI/browser configuration, and a success test
(a real `hello-ai` workflow execution). Re-run any time; `--offline` names
exactly what cannot be installed without internet.

## CLI Reference

```cmd
openagent setup | start | stop | restart | status
openagent doctor [--fix] | openagent repair
openagent logs [--tail [n]] [--open] | openagent config {list,get,set}
openagent workflow | agent | node | mcp | memory | schedule
openagent model {detect,list,install,use,doctor}
openagent browser {doctor,install,update}
openagent db {status,migrate,reset}
openagent backup create | openagent restore [id] | openagent reset
openagent update [--apply] | openagent version
openagent git {status,remote,connect,auth,enable-auto-sync,disable-auto-sync,sync}
```

Details: [docs/CLI.md](docs/CLI.md). Every command is real — anything not
implemented reports `NOT IMPLEMENTED` instead of faking success.

## Configuration

`.env.example` is committed; `.env` is generated by setup (never overwritten,
never committed). `OPENAGENT_DATA_DIR`, `OPENAGENT_PORT`, provider keys, and
per-project `.openagent/config.json` cover the rest. Ports roll forward
automatically when busy and persist to config.

## AI Model Setup

```cmd
openagent model detect    # Ollama / LM Studio / OPENAI_API_KEY, + HW profile
openagent model install   # pulls the recommended model (asks first for large ones)
openagent model use ollama:qwen2.5
openagent model doctor
```

## Browser Setup

```cmd
openagent browser doctor
openagent browser install   # Playwright Chromium, no manual steps
```

## MCP Setup

```cmd
openagent mcp add my-server --transport stdio --command my-mcp-server
openagent mcp test my-server
openagent mcp doctor
```

## Workflow Examples

```cmd
openagent init --yes --name demo --kind tool --language ts .
openagent workflow generate "when a webhook arrives, summarize with AI, save to file" --run
openagent workflow run daily-news-digest
openagent ask "run my daily-news-digest workflow" --run
```

## Agent Examples

```cmd
openagent agent create --name researcher --model ollama:qwen2.5
openagent agent run <id> --input '{"goal":"summarize today"}'
openagent autonomous "triage the inbox" --max-steps 10
openagent memory set tone concise
```

## Troubleshooting

Start with `openagent doctor` (repair with `--fix`), then `openagent repair`,
then `openagent logs --tail`. Common cases: CLI not found (restart terminal;
never install the `openagent` placeholder package), port busy (auto-rolls),
Ollama missing (`openagent model install`), browser missing
(`openagent browser install`). Full guide: [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md).

## Doctor, Repair, Update, Backup

- `openagent doctor` checks OS/CPU/RAM/runtime/Node/npm/Git/CLI/PATH/database/ports/filesystem/browser/AI/MCP/backend/frontend/engine/memory/plugins/GitHub-auth/disk with ✓/!/✗ and fixes.
- `openagent repair` recreates dirs, validates config (corrupt files preserved as `*.corrupt`), clears stale pids/cache — never deletes workflows without confirmation.
- `openagent update` compares against GitHub releases (npm only as fallback), snapshots data, verifies checksums, migrates, health-checks, rolls back on failure.
- `openagent backup create` / `openagent restore <id>` cover workflows, agents, settings, database, plugin config; secrets stay encrypted.

## Git and GitHub Integration

Optional, auto-sync OFF by default. `openagent git status` (read-only),
`--init`, `remote` (never overwrites), `connect <url>` (refuses overwrite
without `--force`), `auth` (gh/SSH/credential-manager guidance),
`enable-auto-sync` / `disable-auto-sync`, `sync` (secret scan → typecheck →
tests → build → commit generated from actual files → plain push, never
`--force`). Any failure stops before commit/push. Details: [docs/GIT.md](docs/GIT.md).

## Testing

```bash
pnpm typecheck        # all packages
pnpm lint
pnpm test             # unit (vitest) + API (pytest)
pnpm test:unit
pnpm test:integration
```

The CLI package adds `test` (vitest, incl. secret-scan/packaging/local-engine
suites) and the desktop package covers lifecycle + update-channel logic.
E2E paths exercised in CI and release validation: setup → doctor → workflow
run → agent run → backup/restore → update check → git sync gates.

## Repository Structure and Architecture

See [Project Structure](#project-structure) above and
[ARCHITECTURE.md](ARCHITECTURE.md). One core engine
(`packages/workflow-engine` + providers/tools/memory) serves the CLI, the
desktop controller, the FastAPI backend, and the Next.js frontend — no
parallel implementations.

## Release Process

`node scripts/version.mjs` (single version source) →
`scripts/release-check.mjs` → `npm run package:windows`
(`openagent-win-x64.zip` + `.sha256`, NSIS staging, `OpenAgent-Setup.exe` via
`makensis`) → GitHub release with checksums → `openagent update` serves it.
`npm pack` in `packages/cli` validates the optional npm artifact (bin + dist).

## FAQ

**Do I need Node.js?** Only for developer mode. Normal install bundles its runtime.
**Do I need Docker/PostgreSQL?** No — SQLite + embedded queue by default; Docker is for full-stack development.
**Which `openagent` npm package?** `@openagent/cli` (developers only, after publication). The bare `openagent` name is an unrelated placeholder — never install it.
**Where is my data?** `%LOCALAPPDATA%\OpenAgent\data` (preserved across updates/uninstalls).
**How do I update?** `openagent update --apply`, or re-run `OpenAgent-Setup.exe`.

## Roadmap

Phases 01–24 are implemented, including the full Developer Platform (MP28).
See [ROADMAP.md](ROADMAP.md) for the phase-by-phase breakdown. Next up: production reliability hardening, then a versioned production release.

## Contributing

We welcome contributions. Please read [CONTRIBUTING.md](CONTRIBUTING.md), then:

1. Fork the repository
2. Create a feature branch
3. Implement with tests
4. Run lint + typecheck + tests
5. Open a pull request using the template

Extension authors: start at [`docs/developers/`](docs/developers/) and the [security guide](docs/developers/security.md).

## Security

See [SECURITY.md](SECURITY.md) for supported versions and responsible disclosure.
Security-sensitive extension behavior (tool/MCP/sandbox policy, signing, supply chain) is documented in [`docs/developers/threat-model.md`](docs/developers/threat-model.md).
Never commit secrets — see `.env.example` for the full variable list.

## License

MIT — see [LICENSE](LICENSE).
