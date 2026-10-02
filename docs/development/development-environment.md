# Development Environment

Canonical toolchain: **pnpm 8.15** (workspaces + lockfile), **Node.js ≥ 20**, **Python ≥ 3.11**, **PostgreSQL 15+**, **Redis 7+**, **Docker 24+ / Compose v2** for containerized runs.

## Daily commands

```bash
pnpm setup          # deps + .env (idempotent, never overwrites .env)
pnpm doctor         # environment diagnostics (read-only)
pnpm dev            # full stack via Docker
pnpm dev:local      # web + api + worker natively (needs Postgres/Redis)
pnpm dev:web | pnpm dev:api | pnpm dev:worker
pnpm infra:up       # Postgres + Redis in Docker only (hybrid)
pnpm build | pnpm test | pnpm lint | pnpm typecheck
pnpm format | pnpm format:check
pnpm clean          # generated outputs (safe); pnpm clean:all for full reset
```

`turbo run dev` is the underlying runner; the `dev:*` scripts select services. `node scripts/*.mjs` are dependency-free and cross-platform (Windows/macOS/Linux).

## Database

Alembic (in `apps/api/alembic`) is authoritative for the backend schema (27 migrations, single head). The `prisma/schema.prisma` in `packages/database` is companion tooling for the foundational entities, not the migration path.

```bash
pnpm db:setup      # migrate + seed dev data
pnpm db:migrate    # upgrade to head
pnpm db:rollback   # downgrade one revision
pnpm db:seed       # re-run scripts/seed_dev.py
pnpm db:reset      # downgrade base + upgrade + seed (asks first; refused in production)
```

See [database](database.md).

## Backend venv

```bash
python -m venv apps/api/.venv
apps/api/.venv/Scripts/python -m pip install -e "apps/api[dev]"   # Windows
```

macOS/Linux: `source apps/api/.venv/bin/activate`, then `pip install -e "apps/api[dev]"`.
