# Database

PostgreSQL 15+ is required (async SQLAlchemy, JSONB, Alembic-managed schema). SQLite is not a substitute.

## Toolchain

- **Alembic** (`apps/api/alembic`, 27 revisions, single head) — the authoritative migration path. All schema changes go through `alembic revision --autogenerate -m "description"` + `alembic upgrade head`.
- **Prisma** (`packages/database/prisma/schema.prisma`) — companion model for foundational entities and JS-side type tooling.

## Commands

```bash
pnpm db:setup      # upgrade head + seed
pnpm db:migrate    # upgrade head
pnpm db:rollback   # downgrade -1
pnpm db:seed       # scripts/seed_dev.py (dev data only)
pnpm db:reset      # confirm-gated; refused when OPENAGENT_ENV=production
```

## Migration rules

- Additive and reversible where practical; never delete production data implicitly.
- One head only — verify with `alembic heads`.
- Seed scripts are idempotent and development-only.
