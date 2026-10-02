## What changed?

<!-- Describe the change and the problem it solves. Link related issues: Fixes #123 -->

## Why?

<!-- Motivation and context. What happens without this change? -->

## Testing

<!-- Commands run and results. Be specific. -->

- [ ] Backend: `cd apps/api && pytest -q` — result:
- [ ] Web typecheck: `cd apps/web && npx tsc --noEmit` — result:
- [ ] Affected package tests (`vitest run`) — result:
- [ ] Manual verification steps:

## Security considerations

<!-- Permissions, secrets, sandboxing, SSRF, injection, tenant isolation.
     Confirm: no secrets committed, no `console.log` of credentials,
     new endpoints enforce org scope + RBAC, validation at API boundary. -->

- [ ] No secrets, credentials, or tokens committed
- [ ] New API routes are org-scoped and permission-checked
- [ ] User input is validated server-side (Pydantic/Zod)
- [ ] Sensitive values are redacted in logs and API responses

## Breaking changes

<!-- None expected. If any: migration path, affected SDK/CLI surfaces. -->

## Screenshots

<!-- UI changes only. Omit for backend-only changes. -->

## Checklist

- [ ] Follows repo architecture (`ARCHITECTURE.md`) — no parallel systems
- [ ] Database changes use Alembic migrations (additive, reversible where practical)
- [ ] Public API changes are versioned (`/api/v1`) with typed errors
- [ ] SDK/CLI updated if public behavior changed
- [ ] Docs updated (`docs/`, examples if applicable)
- [ ] `CHANGELOG.md` entry added under Unreleased
