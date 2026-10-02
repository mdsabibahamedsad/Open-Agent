# Non-Docker

Run everything from source without Docker. You still need real PostgreSQL 15+ and Redis 7+ — OpenAgent depends on PostgreSQL-specific functionality (async SQLAlchemy, JSONB, Alembic migrations), so SQLite is not a substitute.

## Steps

```bash
pnpm setup          # deps + .env
pnpm doctor         # confirm Postgres/Redis reachable

# Backend virtualenv (once)
python -m venv apps/api/.venv
apps/api/.venv/Scripts/python -m pip install -e "apps/api[dev]"   # Windows
# source apps/api/.venv/bin/activate && pip install -e "apps/api[dev]"  # macOS/Linux

pnpm db:setup       # migrate + seed dev data
pnpm dev:local      # web + api + worker with one banner, Ctrl+C stops all
```

Individual services: `pnpm dev:web`, `pnpm dev:api`, `pnpm dev:worker`.

## If Postgres/Redis are missing

`pnpm doctor` tells you exactly that, with options:

1. Install locally (PostgreSQL 15+, Redis 7+)
2. Infrastructure-only Docker: `pnpm infra:up` (keeps code native — see [hybrid](hybrid.md))
3. Full Docker: `docker compose up --build`

## Environment

Point `.env` at your local services (defaults already do):

```text
DATABASE_URL=postgresql+asyncpg://openagent:openagent@localhost:5432/openagent
REDIS_URL=redis://localhost:6379/0
```
