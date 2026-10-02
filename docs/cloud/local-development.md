# Local development

```bash
cp .env.example .env
docker compose up -d postgres redis minio
# run API + worker + scheduler + web locally, or:
docker compose up -d
```

One command (`docker compose up`) bootstraps Postgres, Redis, MinIO,
API, cloud worker, scheduler and frontend. Self-hosted mode works with
`OPENAGENT_CLOUD_ENABLED=false` (default): local runtime handles
execution, no cloud credentials needed.

Environment variables are documented in `.env.example` (safe
placeholders only — never real credentials).
