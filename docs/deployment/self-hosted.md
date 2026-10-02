# Self-Hosted Deployment

Deploy OpenAgent on your own infrastructure with Docker Compose. This guide
covers the production overlay only; for local development see
`docs/getting-started/`.

## Prerequisites

- Linux host (or VM) with Docker Engine 24+ and Compose v2
- A domain with DNS pointing at the host (e.g. `app.example.com`,
  `api.example.com`)
- PostgreSQL 15+ and Redis 7+ — either the bundled services in
  `docker-compose.production.yml` or managed instances
- S3-compatible storage for artifacts (bundled MinIO works for small
  deployments; use S3/R2 for anything serious)
- A reverse proxy with TLS (Caddy, Nginx, Traefik — your choice; see
  “HTTPS / reverse proxy” below). Never expose the app over plain HTTP.

## 1. Configure environment

```bash
cp .env.production.example .env
# Edit .env — fill EVERY required value. Placeholders will refuse to boot.
openssl rand -hex 32   # SECRET_KEY
openssl rand -hex 32   # ENCRYPTION_KEY
openssl rand -hex 32   # WORKER_SERVICE_TOKEN
```

If you use the bundled postgres/redis services, `POSTGRES_PASSWORD` must
match the password inside `DATABASE_URL`, and `REDIS_PASSWORD` must match
`REDIS_URL`. Managed instances: set `DATABASE_URL`/`REDIS_URL` to them and
you may still keep the bundled services stopped (see step 3).

## 2. Build images

```bash
docker compose -f docker-compose.production.yml build
```

Important: the `web` service runs `pnpm start` and therefore needs a
production Next.js build (`.next`) inside its image. If your web image does
not contain one yet, build it in CI (`pnpm --filter @openagent/web build`)
and adapt `apps/web/Dockerfile` to a multi-stage build — the current
Dockerfile is development-oriented (documented limitation).

## 3. Start data services first, then migrate

```bash
docker compose -f docker-compose.production.yml up -d postgres redis
# Wait for healthy:
docker compose -f docker-compose.production.yml ps

# Back up first if this database already holds data (see upgrading.md).
docker compose -f docker-compose.production.yml run --rm api \
  python -m alembic upgrade head
```

The API image contains the Alembic tree (`alembic.ini` + `alembic/`), so
migrations run from the `api` service. There is exactly one migration head
(`027_add_developer_platform`); if `alembic heads` ever shows more than one,
STOP and resolve before deploying.

## 4. Start everything

```bash
docker compose -f docker-compose.production.yml up -d
docker compose -f docker-compose.production.yml ps
curl -sf http://127.0.0.1:8000/api/v1/health && echo API-LIVE
curl -sf http://127.0.0.1:8000/api/v1/health/ready && echo API-READY
```

`/health` = process alive. `/health/ready` = 200 only when PostgreSQL **and**
Redis both answer; otherwise 503 (keep it behind your load balancer's
readiness probe, not the liveness probe).

## 5. HTTPS / reverse proxy

Terminate TLS at the proxy and forward to loopback only (`127.0.0.1:3000`
web, `127.0.0.1:8000` api — the production compose never binds `0.0.0.0`).

Caddy example (automatic certificates):

```text
app.example.com {
    reverse_proxy 127.0.0.1:3000
}
api.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

Set `HSTS`, redirect HTTP→HTTPS, and configure `CORS_ORIGINS` to exactly
your web origin (no wildcards, no localhost). Cookies are secure by default
in production (`OPENAGENT_ENV=production`); the API serves no `/docs` in
production.

## 6. Backups

- **PostgreSQL:** `pg_dump` on a schedule; test restores, not just dumps.
  OpenAgent does **not** back up your database for you.
- **Redis:** persistence is queue state, not source of truth — RDB/AOF per
  your tolerance for re-queued jobs.
- **MinIO/S3:** versioned bucket or scheduled sync for artifacts.

## 7. Logs, health, monitoring

- `docker compose -f docker-compose.production.yml logs -f [service]`
- Alert on: `/health/ready` non-200, worker heartbeat gaps
  (`WORKER_HEARTBEAT_TTL_SECONDS=90`), queue depth (`CLOUD_QUEUE_MAX_DEPTH`),
  5xx rate on the proxy.
- Optional: `SENTRY_DSN`, `OTEL_EXPORTER_OTLP_ENDPOINT`, `OPS_ALERT_WEBHOOKS`.

## Troubleshooting

| Symptom                                           | Likely cause                   | Fix                                                                                                    |
| ------------------------------------------------- | ------------------------------ | ------------------------------------------------------------------------------------------------------ |
| api exits, “SECRET_KEY … required”                | placeholder `.env`             | fill `.env.production.example` values                                                                  |
| api refuses to start mentioning approvals/sandbox | insecure prod defaults         | keep `APPROVALS_ENABLED=true`, `SANDBOX_PROVIDER=docker`, pin `SANDBOX_IMAGE_DIGEST`                   |
| `ready` returns 503                               | PG/Redis unreachable           | check service health, `DATABASE_URL`/`REDIS_URL` hostnames (`postgres`/`redis` inside compose network) |
| web shows API errors                              | `NEXT_PUBLIC_API_URL` mismatch | must equal public `API_URL` + `/api/v1`                                                                |
| worker idle, jobs stuck                           | token mismatch                 | `WORKER_SERVICE_TOKEN` identical across api/worker/scheduler                                           |
