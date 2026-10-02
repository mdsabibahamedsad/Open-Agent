# Quick Start

Get OpenAgent running in about five minutes. Pick the path that fits you:

| Path | Command | Best for |
| ---- | ------- | -------- |
| Docker (recommended) | `docker compose up --build` | First-time users, exact parity |
| Guided setup | `pnpm setup` then `pnpm dev` | Contributors, everyday development |
| Non-Docker | `pnpm setup` then `pnpm dev:local` | No Docker available |
| Hybrid | `pnpm infra:up` then `pnpm dev:local` | Fast iteration, real Postgres/Redis |

Prerequisites: Git, Node.js 20+, pnpm 8.15+. Run `pnpm doctor` at any time to verify your machine.

## Docker (recommended)

```bash
git clone https://github.com/mdsabibahamedsad/Open-Agent.git
cd Open-Agent
cp .env.example .env   # Windows PowerShell: Copy-Item .env.example .env
docker compose up --build
```

Open:

- Web: http://localhost:3000
- API: http://localhost:8000
- API docs: http://localhost:8000/docs
- Health: http://localhost:8000/api/v1/health

Stop with `Ctrl+C`, or `docker compose down` to remove containers.

## Guided setup (pnpm)

```bash
git clone https://github.com/mdsabibahamedsad/Open-Agent.git
cd Open-Agent
pnpm setup     # installs deps, creates .env with fresh dev secrets
pnpm doctor    # verify everything
pnpm dev       # full stack (Docker)
```

`pnpm setup` never overwrites an existing `.env` (use `--force` to regenerate) and never prints secret values.

## npm users

pnpm is canonical (workspace + lockfile). npm can still run the root scripts after dependencies are installed with pnpm:

```bash
pnpm install
npm run doctor
npm run dev
```

`npm install` alone does not link pnpm workspaces — always install with `pnpm install`.

## Next steps

- [Windows](windows.md) · [macOS](macos.md) · [Linux](linux.md) — platform specifics
- [Docker](docker.md) · [Non-Docker](non-docker.md) · [Hybrid](hybrid.md) — run modes
- [Environment](environment.md) — every variable, explained
- [Local AI](local-ai.md) — Ollama and cloud providers
- [Troubleshooting](troubleshooting.md) — fixes for common errors
