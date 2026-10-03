# OpenAgent Development

## Bootstrap

```cmd
git clone https://github.com/mdsabibahamedsad/Open-Agent.git
cd Open-Agent
setup.cmd
```

`setup.cmd` (or `setup.ps1`) performs: OS/arch detection, Node 20+ check,
Git/pnpm detection (corepack/npm fallback), hardware probe, per-user local
directories, `pnpm install`, `@openagent/cli` build, `.env` generation
(never overwrites), `openagent setup --yes`, `openagent doctor`,
`openagent-dev.cmd` launcher creation, CLI smoke tests. Ends with
`OPENAGENT SETUP COMPLETE` or a `SETUP FAILED` reason + repair hint.

## Daily commands (repo root)

| Command            | Purpose                              |
| ------------------ | ------------------------------------ |
| `npm run dev`      | full stack via Docker                |
| `npm run build`    | build all packages (turbo)           |
| `npm run test`     | run all tests (turbo)                |
| `npm run typecheck`| typecheck all packages               |
| `npm run lint`     | lint all packages                    |
| `node scripts/doctor.mjs` | repo environment diagnostics |

## OpenAgent commands (any directory)

```cmd
openagent setup [--dev|--production|--minimal|--offline] [--yes]
openagent start | openagent stop | openagent status
openagent doctor [--fix]
openagent repair
openagent update | openagent backup | openagent restore
```

## Layout

```text
openagent/
  apps/       web, api, desktop (Electron controller), worker
  packages/   cli, workflow-engine, desktop, tool-system, ...
  tools/installer/windows/  Install/Uninstall PS1 + installer.nsi
  scripts/    setup.mjs, doctor.mjs, package-windows.mjs, ...
  docs/       user + developer guides
```

## Local runtime (no Docker needed)

Default database is SQLite and the queue is embedded — PostgreSQL/Redis/Docker
are only for advanced deployments (`pnpm infra:up`, `docker compose up`).
User data lives in `%LOCALAPPDATA%\OpenAgent\data` (override with
`OPENAGENT_DATA_DIR`); `.env.local` values are generated, secrets are never
committed (see [GIT.md](GIT.md)).
