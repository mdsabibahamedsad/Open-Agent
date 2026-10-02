# Environment

Copy `.env.example` to `.env` (or run `pnpm setup`, which generates fresh dev secrets). Never commit `.env` — it is git-ignored.

## Ports (central configuration)

| Variable | Default | Service |
| -------- | ------- | ------- |
| `WEB_URL` | `http://localhost:3000` | Web dashboard |
| `API_URL` | `http://localhost:8000` | Backend API |
| `DATABASE_URL` host port | `5432` | PostgreSQL 15+ |
| `REDIS_URL` host port | `6379` | Redis 7+ |

`pnpm doctor` detects occupied ports. Change the port inside `WEB_URL`/`API_URL` (and `CORS_ORIGINS` accordingly).

## Required variables

| Variable | Purpose | Rule |
| -------- | ------- | ---- |
| `DATABASE_URL` | Postgres connection (`postgresql+asyncpg://…`) | reachable host |
| `REDIS_URL` | Redis connection | reachable host |
| `SECRET_KEY` | JWT/session signing | ≥ 32 chars, `openssl rand -hex 32` |
| `ENCRYPTION_KEY` | Stored credential encryption | ≥ 32 chars |

## Model providers (all optional)

The backend Model Router supports `openai`, `anthropic`, `google`, `ollama` (local, no key), and `openai-compatible` endpoints. Configure with the matching variables from `.env.example`:

```text
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
GOOGLE_API_KEY=
```

No provider is required to boot the platform. See [local-ai](local-ai.md).

## Subsystem toggles (safe defaults)

Sandbox (`SANDBOX_*`), approvals (`APPROVALS_*`), evaluator (`EVALUATION_*`), connectors (`CONNECTOR_*`), billing (`BILLING_MODE=disabled`), and cloud runtime (`OPENAGENT_RUNTIME_MODE=self_hosted`) all ship fail-closed: local development works out of the box, and production refuses silently-unsafe settings at startup. Read the comments in `.env.example` before changing them.
