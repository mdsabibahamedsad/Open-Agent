# Troubleshooting

Each entry: Problem → Cause → Fix → Verification.

## `pnpm doctor` shows pnpm's own check instead of OpenAgent's

- **Problem:** `pnpm doctor` prints pnpm installation diagnostics, not "OpenAgent Doctor".
- **Cause:** pnpm 10+ ships a built-in `doctor` command that shadows the workspace script.
- **Fix:** Use `pnpm run doctor` (always runs the OpenAgent diagnostics), or use the canonical pnpm 8.15 (`packageManager` field) where `pnpm doctor` runs the workspace script.
- **Verification:** Output starts with "OpenAgent Doctor".

## Port already in use

- **Problem:** `EADDRINUSE` / "port is already allocated".
- **Cause:** Another service (or a previous OpenAgent run) holds 3000/8000/5432/6379.
- **Fix:** `pnpm doctor` shows which ports answer; stop the other process, or change `WEB_URL`/`API_URL` ports in `.env`.
- **Verification:** `pnpm doctor` reports the port free.

## Node version mismatch

- **Problem:** install or build fails with `EBADENGINE`.
- **Cause:** Node < 20.
- **Fix:** Install Node.js 20 LTS (https://nodejs.org/en/download).
- **Verification:** `node --version` → v20+.

## pnpm/npm missing

- **Problem:** `pnpm: command not found`.
- **Cause:** pnpm not installed.
- **Fix:** `corepack enable` (+ `corepack prepare pnpm@8.15.0 --activate`), or https://pnpm.io/installation.
- **Verification:** `pnpm --version` → 8.15.x.

## Python missing

- **Problem:** backend steps fail; `pnpm doctor` reports no Python.
- **Cause:** No Python 3.11+ on PATH.
- **Fix:** https://www.python.org/downloads/ (Windows: tick "Add python.exe to PATH").
- **Verification:** `python --version` → 3.11+.

## Docker missing / daemon not running

- **Problem:** `docker: command not found` or "cannot connect to the Docker daemon".
- **Cause:** Docker Desktop not installed or not started.
- **Fix:** Install/start Docker Desktop (https://docs.docker.com/get-docker/), or use [non-docker](non-docker.md).
- **Verification:** `docker info` succeeds.

## PostgreSQL / Redis unavailable

- **Problem:** API fails to start; `/health/ready` reports not ready.
- **Cause:** No database/cache reachable at `DATABASE_URL`/`REDIS_URL`.
- **Fix:** `pnpm infra:up`, or install Postgres 15+ / Redis 7+ locally.
- **Verification:** `pnpm doctor` shows both reachable.

## Migration failure

- **Problem:** `pnpm db:migrate` errors.
- **Cause:** Wrong database (empty credentials), concurrent migrators, or edited migration history.
- **Fix:** Confirm `DATABASE_URL`, ensure a single migrator, check `alembic history`. Never hand-edit applied migrations.
- **Verification:** `pnpm db:migrate` reports "at the latest migration".

## Permission errors (Linux)

- **Problem:** `permission denied` on `/var/run/docker.sock`.
- **Cause:** User not in the `docker` group.
- **Fix:** `sudo usermod -aG docker $USER`, then log out/in.
- **Verification:** `docker ps` without sudo.

## PowerShell policy (Windows)

- **Problem:** "running scripts is disabled on this system".
- **Cause:** Restrictive execution policy blocks `.ps1` shims (pnpm/npm).
- **Fix:** `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.
- **Verification:** `pnpm --version` works in a new terminal.

## WSL issues

- **Problem:** Docker or networking unreachable inside WSL2.
- **Cause:** WSL integration disabled, or project lives on `/mnt/c` (slow).
- **Fix:** Enable WSL integration in Docker Desktop; keep the repo inside the Linux filesystem (`~/Open-Agent`).
- **Verification:** `docker ps` works inside WSL.

## Environment variable errors

- **Problem:** API refuses to start: `SECRET_KEY ... at least 32 characters`.
- **Cause:** Placeholder or short secrets in `.env`.
- **Fix:** Run `pnpm setup --force` to regenerate, or paste 64-hex-char values.
- **Verification:** `pnpm doctor` → `.env` pass (values are never printed).

## Dependency installation failure

- **Problem:** `pnpm install` fails.
- **Cause:** Network restrictions, Node/pnpm mismatch, or lockfile drift.
- **Fix:** Check versions (`pnpm doctor`), retry with network access, avoid editing `pnpm-lock.yaml` by hand.
- **Verification:** `node_modules` present and `pnpm doctor` passes.

## Frontend cannot reach API

- **Problem:** Web UI shows network errors.
- **Cause:** API not running, or `NEXT_PUBLIC_API_URL` points elsewhere.
- **Fix:** Start the API (`pnpm dev` / `pnpm dev:api`); default `http://localhost:8000/api/v1` needs no override locally.
- **Verification:** `curl http://localhost:8000/api/v1/health` → 200.

## Worker unavailable

- **Problem:** Background jobs never complete.
- **Cause:** Worker not running or Redis unreachable.
- **Fix:** `pnpm dev:worker` (or full `pnpm dev`); confirm Redis via `pnpm doctor`.
- **Verification:** worker logs show startup without connection errors.

## Model unavailable / Ollama unavailable

- **Problem:** Agent runs fail with provider errors.
- **Cause:** No provider key configured, or `ollama serve` not running.
- **Fix:** Set the provider key in `.env`, or start Ollama (`ollama serve` + `ollama pull llama3`).
- **Verification:** provider-specific health per [local-ai](local-ai.md); platform boots fine without any model.
