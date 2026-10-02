# Architecture (Developer Pointer)

The canonical architecture document is [`ARCHITECTURE.md`](../../ARCHITECTURE.md) at the repository root. This file exists so `docs/development/` has a predictable entry point and to avoid duplicated, contradictory descriptions.

- Web: `apps/web` (Next.js 14 dashboard + developer portal).
- API: `apps/api` (FastAPI, `/api/v1`, Alembic migrations are authoritative).
- Worker: `apps/worker` (Redis-backed background jobs, scheduler).
- System of record: PostgreSQL 15+ (Alembic heads the schema).
- Queue/cache: Redis 7+.
- Optional local object storage: MinIO (S3-compatible, see `docker-compose.yml`).

Health endpoints (no secrets exposed):

- `GET /api/v1/health` — process alive.
- `GET /api/v1/health/ready` — readiness (database/Redis checks where configured).

Ports are configured centrally via `.env` (`API_URL`, `WEB_URL`, `DATABASE_URL`, `REDIS_URL`); see [environment guide](../getting-started/environment.md). `pnpm doctor` reports which ports answer.
