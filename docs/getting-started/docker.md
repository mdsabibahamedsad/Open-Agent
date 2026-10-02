# Docker

Full-stack local environment: `web`, `api`, `postgres`, `redis` (plus `worker` — see `docker-compose.yml` service list).

## Run

```bash
cp .env.example .env     # first time only (or `pnpm setup`)
docker compose up --build
```

Useful commands (also available as `pnpm docker:*`):

| Command | Effect |
| ------- | ------ |
| `docker compose up --build` | Build + start everything (foreground) |
| `docker compose up -d` / `pnpm docker:up` | Start detached |
| `docker compose logs -f [service]` / `pnpm docker:logs` | Follow logs |
| `docker compose restart [service]` / `pnpm docker:restart` | Restart |
| `docker compose down` / `pnpm docker:down` | Stop + remove containers (data volumes kept) |
| `docker compose down -v` | Stop + **delete data volumes** (destroys local DB) |

Requires Docker Engine 24+ / Desktop 4+ with Compose v2 (`docker compose`, not `docker-compose`).

## Health and ordering

`postgres` and `redis` define health checks; `api` waits for `service_healthy` before starting. At runtime:

- API liveness: `GET http://localhost:8000/api/v1/health`
- Readiness (app + DB + Redis): `GET http://localhost:8000/api/v1/health/ready`

## Data

Postgres and Redis persist in named volumes (`postgres_data`, `redis_data`). To wipe local data deliberately, use `docker compose down -v`.
