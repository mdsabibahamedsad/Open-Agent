# macOS

Supports Apple Silicon and Intel Macs. No mandatory Homebrew dependency — it is one option below.

## Options

1. **Docker Desktop** (recommended) — `docker compose up --build`.
2. **Native + Docker infra** — `pnpm infra:up`, then `pnpm dev:local`.
3. **Fully native** — local PostgreSQL 15+ and Redis 7+, then `pnpm dev:local`. See [non-docker](non-docker.md).

## Prerequisites

- Git: `xcode-select --install`, or https://git-scm.com/download/mac
- Node.js 20 LTS: https://nodejs.org/en/download, or `brew install node@20`
- pnpm 8.15+: `corepack enable`, or `brew install pnpm`
- Python 3.11+: https://www.python.org/downloads/macos/, or `brew install python@3.11`
- Docker Desktop (for Docker/hybrid modes): https://docs.docker.com/desktop/install/mac-install/

Verify: `pnpm doctor`.

## Notes

- Apple Silicon: all images used are multi-arch (`postgres:15-alpine`, `redis:7-alpine`, `python:3.11-slim`, `node:20-alpine`).
- If port 3000/8000 is taken by AirPlay or another service, stop it or override `WEB_URL`/`API_URL` in `.env` (see [environment](environment.md)).
