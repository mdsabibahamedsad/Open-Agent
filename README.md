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

Prerequisites: Git, Node.js 20+, pnpm 8.15+, Python 3.11+, Docker & Docker Compose.
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
npm install -g openagent

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

`apps/desktop/` and `apps/docs/` exist as empty placeholders for planned work.

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
