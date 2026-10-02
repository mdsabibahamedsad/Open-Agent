# OpenAgent Release Notes — v0.1.0 (Platform Beta)

> These notes describe what is actually in the repository on `main`.
> No marketing claims, no planned features presented as done.

## What is available

- **AI Workforce OS core (BETA):** agents, visual workflows, model routing
  (multi-provider + local Ollama adapters), typed tool runtime with policies,
  MCP servers/tools/resources/prompts, multi-agent orchestration with budgets,
  persistent memory, browser automation, coding agent, Docker-isolated sandbox
  execution, human approval guardrails, evaluation/self-correction gates.
- **Integrations (Available):** 11 official connectors (Gmail, Slack, Discord,
  Telegram, GitHub, GitLab, Calendar, Drive, Notion, HubSpot, Postgres) plus
  generic HTTP, with health checks and rate limits.
- **Developer Platform (1.x line, Available):** `openagent` CLI (scaffold,
  validate, test, package, publish, deploy), TypeScript + Python SDKs, 20
  extension types, manifest signing (Ed25519), versioned marketplace packages,
  14 examples, 10 starter templates.
- **Cloud runtime (Experimental):** workers, queues, placements, artifacts,
  scheduler — self-hosted by default, cloud behind feature flags.
- **Billing (Beta):** provider-neutral interfaces; provider `disabled` by
  default so self-hosting always works.
- **Desktop app (Planned):** `apps/desktop/` is an empty placeholder.

## Important changes in this hardening pass

1. `apps/worker/pyproject.toml` was npm JSON — replaced with valid Python
   packaging metadata (worker now installable/buildable).
2. All `clean` scripts are cross-platform (Node `fs.rmSync`, no `rm -rf`).
3. Per-package `lint` now runs a real check (`prettier --check`); package
   sources formatted to the repo's own declared standard; added
   `apps/web/.eslintrc.json` so `next lint` runs non-interactively.
4. New: `docker-compose.production.yml`, `.env.production.example`,
   `pnpm version`, `pnpm release:check`, tag-gated `release.yml` (validate
   only), deployment docs, data-flow + privacy docs, `THIRD_PARTY_NOTICES.md`.
5. No application behavior was changed.

## Breaking changes

None. All changes are additive (new files, new scripts) except
formatting-only source normalization and the worker packaging fix
(which un-breaks something that could never have worked).

## Migration requirements

- None for developers (`pnpm install` unchanged; no new dependencies —
  `pnpm-lock.yaml` untouched).
- Self-hosters: compare your `.env` against the updated `.env.example`
  (no new _required_ variables); back up PostgreSQL before running
  `pnpm db:migrate` (see `docs/deployment/upgrading.md`).

## Installation

```bash
git clone https://github.com/mdsabibahamedsad/Open-Agent.git
cd Open-Agent
pnpm setup
pnpm doctor
pnpm dev            # Docker path, or:
pnpm infra:up && pnpm dev:local   # hybrid path
```

Production self-hosting: `docs/deployment/self-hosted.md`.

## Known limitations

- `pnpm lint`: web has pre-existing errors (see release-readiness).
- `pnpm typecheck`: `@openagent/mcp` has pre-existing errors.
- `pnpm build`: `@openagent/api-client` build has a pre-existing type error.
- Web dev image runs as root; production hardening of the web image
  (multi-stage, non-root, `next start`) is documented future work.
- Backend integration tests and Docker builds require infrastructure
  (provided in CI, not in a bare checkout).

## Security notes

- Never commit `.env`; production requires 32+ char `SECRET_KEY` /
  `ENCRYPTION_KEY` (enforced at startup); production refuses insecure
  sandbox/approval/evaluator/connector settings (fail-closed, verified in
  `apps/api/src/openagent/main.py`).
- Report vulnerabilities privately per `SECURITY.md` (do not open public
  issues).

## Upgrade instructions

See `docs/deployment/upgrading.md` (backup → pull → changelog → env →
migrate → restart → health-check → verify; rollback via backup/forward-fix,
never blind downgrade).
