# Windows

## Options

1. **Docker Desktop** (recommended) — `docker compose up --build` just works.
2. **Native + Docker infra** — `pnpm infra:up`, then `pnpm dev:local`.
3. **Fully native** — local PostgreSQL 15+ and Redis 7+, then `pnpm dev:local`. See [non-docker](non-docker.md).

WSL2 (Ubuntu) is a supported alternative: follow [Linux](linux.md) inside WSL2. Native PowerShell is fully supported — all repo scripts are cross-platform Node.js (`scripts/*.mjs`); no Bash, `grep`, or `chmod` required.

## Prerequisites

- Git for Windows: https://git-scm.com/download/win
- Node.js 20 LTS: https://nodejs.org/en/download
- pnpm 8.15+: `corepack enable` (then `corepack prepare pnpm@8.15.0 --activate`), or https://pnpm.io/installation
- Python 3.11+: https://www.python.org/downloads/windows/ — check **"Add python.exe to PATH"** during install
- Docker Desktop (for Docker/hybrid modes): https://docs.docker.com/desktop/install/windows-install/

Verify: `pnpm doctor`.

## PowerShell notes

- Use PowerShell 5.1+ or Windows Terminal. CMD works for most commands.
- If scripts are blocked: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` (see [troubleshooting](troubleshooting.md)).
- Copy `.env.example` with: `Copy-Item .env.example .env` (or let `pnpm setup` do it).
- Line endings: the repo uses LF; Git on Windows may warn about CRLF — harmless.

## Ports

Web `3000`, API `8000`, Postgres `5432`, Redis `6379`. `pnpm doctor` reports which are occupied.
