# Hybrid

Code runs natively (fast reload, debugger-friendly); Postgres and Redis run in Docker.

```bash
pnpm setup
pnpm infra:up     # starts ONLY postgres + redis in Docker
pnpm db:setup     # migrate + seed against them
pnpm dev:local    # web + api + worker locally
```

Stop infrastructure without deleting data: `pnpm infra:down` (`docker compose stop postgres redis`).
Your `.env` defaults (`localhost:5432`, `localhost:6379`) already match the published container ports, so no extra configuration is needed.
