# Health checks

Canonical endpoints (implemented in `apps/api/src/openagent/api/health.py`):

| Endpoint | Auth | Semantics |
| -------- | ---- | --------- |
| `GET /api/v1/health` | No | Liveness: process alive. Always `200` with `{status, service, environment}`. |
| `GET /api/v1/health/ready` | No | Readiness: `SELECT 1` on PostgreSQL + Redis `PING`. `200 {status: ok}` when all checks pass, **`503 {status: degraded, checks: {...}}`** otherwise. |

Rules:

- Load balancers and orchestrators must use `/health/ready` for routing decisions. A `503` means "do not send traffic here". `/health` only tells you the process hasn't crashed.
- The body shape is identical for `200` and `503` so monitors can parse both.
- Checks never expose secrets, versions, or connection strings — only boolean results.
- Authenticated, org-scoped rollups live at `GET /api/v1/operations/health` (maintenance windows, SLOs); the operations dashboard surfaces them at `/operations/health`.

Expected values in each run mode:

| Mode | `/health` | `/health/ready` |
| ---- | --------- | --------------- |
| `docker compose up` (all healthy) | 200 | 200 |
| `pnpm dev:local` before `pnpm infra:up` | 200 | 503 (Postgres/Redis unreachable) |
| Production with a DB outage | 200 | 503 (stop routing, page per runbook) |

`pnpm doctor` reports the same dependency state from the operator side (`PostgreSQL :5432`, `Redis :6379`, API health body).
