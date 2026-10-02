# Production readiness

Gate every production deploy on these checks. Each maps to something the
repository actually enforces or measures — nothing here is aspirational.

## Configuration gates (startup refuses to boot when violated)

| Check | Enforced by |
| ----- | ----------- |
| `OPENAGENT_ENV=production` + all module production validators (approvals, evaluator, connectors, packages, commerce, cloud) | `apps/api/src/openagent/main.py` lifespan |
| `SECRET_KEY`, `ENCRYPTION_KEY` present and ≥ 32 chars | lifespan pre-check (actionable message on top of Settings validation) |
| `DATABASE_URL`, `REDIS_URL` present | lifespan pre-check |
| PostgreSQL + Redis reachable within 10s each | `_probe_dependencies(fail_fast=True)` in lifespan |
| Alembic at a single head | `pnpm db:migrate` before deploy; never hand-edit applied migrations |

In non-production, unreachable dependencies only warn (so `pnpm dev` works
before `pnpm infra:up`).

## Runtime gates

| Check | What good looks like |
| ----- | -------------------- |
| `GET /health/ready` | `200 {status: ok}` on every instance; see [health checks](./health-checks.md) |
| Queue depth | Below `CLOUD_QUEUE_MAX_DEPTH` (100k); sustained growth pages per [alerts](./alerts.md) |
| Dead-letter queues | Near zero; every DLQ entry has an owner and a requeue/discard decision |
| Worker heartbeats | No `UNHEALTHY` workers in `sweep_stale_heartbeats`; heartbeats every 30s, TTL 90s |
| DB pool | `pool_size=10/max_overflow=20` with `pool_recycle=3600` + 30s `pool_timeout`; pool-exhaustion surfaces as fast `503`, never hung requests |
| Logs | JSON in production, secrets redacted at the logging pipeline (`redact_sensitive`), never credentials/tokens in any environment |
| Errors | Standard `ApiError{code,message,request_id,status_code}` envelope on every failure path, request id === `X-Request-ID` response header |

## Pre-deploy command sequence

```bash
git status && git diff --cached   # know exactly what ships
pnpm lint
pnpm typecheck
pnpm test
pnpm build
pnpm doctor
pnpm db:migrate                   # against a backup-verified database
```

CI additionally runs backend/frontend/worker tests, security suites
(IDOR/SSRF/auth/connector-adversarial), Docker builds, and secret scanning.

## What remains deployment-specific (not claimed)

RPO/RTO numbers, TLS termination, replica counts, backup schedules, and
alert destinations depend on your environment. Set them, measure them with
restore tests and load tests, and record the measured values — see
[disaster recovery](./disaster-recovery.md) and
[backup & restore](./backup-restore.md).
