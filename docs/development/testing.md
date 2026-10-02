# Testing

## Layout

- `apps/api/tests/` — backend pytest suite (68 files): unit, security, contract, and integration tests per domain.
- `apps/web` — `vitest run` (component + lib tests).
- `packages/*` — each package runs `vitest run`.
- `tests/` — cross-cutting suites (see that directory).

## Commands

```bash
pnpm test                # everything via Turborepo
pnpm test:unit
pnpm test:integration
cd apps/api && pytest -q            # backend
cd apps/web && pnpm test            # frontend
```

Backend integration tests need Postgres + Redis: `pnpm infra:up` first, with `DATABASE_URL`/`REDIS_URL` from `.env`.

## Conventions

- New behavior ships with tests; security-sensitive changes ship with adversarial tests.
- Never assert on secret values — use redacted/mocked credentials.
- Keep tests deterministic; no network calls in unit tests.
