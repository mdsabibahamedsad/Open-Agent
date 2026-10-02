# OpenAgent Release Readiness

Date: 2026-10-02 · Canonical platform version: **0.1.0** (pre-1.0, per root
`package.json`) · Branch: `main`

> Source of truth is the repository itself. Every status below was verified
> against implementation, not against roadmap claims or prior reports.

## Version story (read first)

The repository carries **two version lines** — this is intentional and
documented, not an accident:

| Line                                      | Version | Source                                                                                                                                                                                                                    |
| ----------------------------------------- | ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Platform (runtime, API, web, workers)     | `0.1.0` | root `package.json`, `apps/web/package.json`, `apps/api` (`openagent-api 0.1.0`, API root reports `"version": "0.1.0"`)                                                                                                   |
| Developer Platform 1.x compatibility line | `1.0.0` | `@openagent/cli`, `@openagent/api-client`, `@openagent/developer-tools`, `@openagent/extension-sdk`, `@openagent/sdk-types`, Python `openagent` SDK `1.0.0`; see `CHANGELOG.md` MP28 and `docs/developers/` compat matrix |

`openagent --version` reports the CLI line (`1.0.0`). `pnpm version` (new
root script) reports the canonical platform version (`0.1.0`). Do not unify
these by hand-editing versions — that is a maintainer release decision.

## Readiness matrix

Status values: `READY` · `BETA` · `EXPERIMENTAL` · `PLANNED`.

| Area                              | Status       | Verified                                                                                                                                                     | Documented                                                         | Notes / limitations                                                                                                                              |
| --------------------------------- | ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| Core (agents, tools, runs)        | BETA         | ✅ implementation + tests                                                                                                                                    | ✅                                                                 | API + SDK paths exercised by tests                                                                                                               |
| Frontend (`apps/web`)             | BETA         | ⚠️ partial                                                                                                                                                   | ✅                                                                 | `next lint` reports pre-existing errors (unescaped entities, conditional hooks in `workflows/[id]/edit`); `pnpm build` for web not verified here |
| Backend (`apps/api`)              | BETA         | ✅ startup guards, health `/health` + `/health/ready` (200 vs 503)                                                                                           | ✅                                                                 | Production disables `/docs` (`main.py`); startup refuses insecure MP19–22 config in production                                                   |
| Database (Alembic, 27 migrations) | BETA         | ✅ single head `027_add_developer_platform`, linear history                                                                                                  | ✅ `docs/development/database.md` + `docs/deployment/upgrading.md` | `upgrade head` needs live PostgreSQL; downgrade↔upgrade cycle not run here (no DB in this environment)                                           |
| Workers (`apps/worker`)           | BETA         | ✅ `cloud_worker`, `cloud_scheduler`, legacy `main`; fixed broken `pyproject.toml` (was npm JSON)                                                            | ✅                                                                 | Queue-recovery behavior covered by design docs; crash-recovery not chaos-tested                                                                  |
| Scheduler                         | BETA         | ✅ present, compose service                                                                                                                                  | ✅                                                                 | Same caveat as workers                                                                                                                           |
| CLI (`openagent`)                 | BETA         | ✅ `--version` (`1.0.0`), `--help`, `doctor` work offline                                                                                                    | ✅                                                                 | Server-dependent commands need a running API (expected)                                                                                          |
| TypeScript SDK + REST client      | BETA         | ✅ `sdk` tests pass (5/5)                                                                                                                                    | ✅                                                                 | No published npm package from this repo state (no registry publish step run)                                                                     |
| Python SDK                        | BETA         | ✅ metadata valid (`pyproject.toml`)                                                                                                                         | ✅ README                                                          | Not uploaded to PyPI from here                                                                                                                   |
| Docker (dev)                      | BETA         | ✅ compose audited (healthchecks, `service_healthy` ordering)                                                                                                | ✅                                                                 | Image builds not run here (no Docker daemon in this environment)                                                                                 |
| Local development                 | READY        | ✅ `setup` + `doctor` + `dev:local` verified on Windows; scripts cross-platform                                                                              | ✅                                                                 | PostgreSQL/Redis still required (local or `infra:up`)                                                                                            |
| Security                          | BETA         | ✅ secret scan clean, `.env` untracked, sandbox sec-gate script, fail-closed prod startup                                                                    | ✅ `SECURITY.md`, `docs/security/`                                 | Web runs as root in dev image; DB/Redis ports published in **dev** compose only (production compose does not)                                    |
| Observability                     | BETA         | ✅ health/readiness endpoints, structured logging                                                                                                            | ✅                                                                 | No hosted dashboard; OTel export optional/unconfigured by default                                                                                |
| Testing                           | BETA         | ✅ JS unit (sdk, connector-sdk pass); backend suite requires PG/Redis (CI provides)                                                                          | ✅                                                                 | Known red: web lint, `mcp` typecheck, `api-client` build — all pre-existing, unrelated to release tooling                                        |
| Documentation                     | BETA         | ✅ README, guides, `ARCHITECTURE.md`, deployment + release docs (this phase)                                                                                 | ✅                                                                 | Release docs describe actual behavior only                                                                                                       |
| CI/CD                             | BETA         | ✅ `ci.yml` (lint/typecheck/unit/integration/security/docker), `build.yml`, `security.yml`; new tag-gated `release.yml` validates only, never auto-publishes | ✅                                                                 | Release workflow not executed here (no tag push)                                                                                                 |
| Packaging                         | BETA         | ✅ `.oaext` deterministic archives + signing (extension system); SBOM via `scripts/sbom.py`                                                                  | ✅                                                                 | No registry binaries produced here                                                                                                               |
| Cloud runtime                     | EXPERIMENTAL | ✅ code + compose services                                                                                                                                   | ✅                                                                 | Self-hosted default (`OPENAGENT_RUNTIME_MODE=self_hosted`); cloud features behind flags                                                          |
| Marketplace                       | BETA         | ✅ listings/moderation present                                                                                                                               | ✅                                                                 | Billing provider `disabled` by default (safe)                                                                                                    |
| Enterprise (SSO/SCIM/RBAC/audit)  | BETA         | ✅ implementation present                                                                                                                                    | ✅                                                                 | No compliance certifications claimed                                                                                                             |

## Overall release status: **BETA**

The platform is a serious, self-hostable beta. It is **not** declared
production-`READY` / `1.0.0`-platform because: the canonical platform version
is `0.1.0`; three static gates are red on pre-existing app-source issues; and
Docker/production paths were audited but not executed in this environment.

## Dependency security review (2026-10-02, `pnpm audit --audit-level=high`)

37 advisories (3 critical, 12 high). No silent upgrades were performed —
major bumps would change runtime behavior. Findings are disclosed, not hidden:

| Package                                     | Severity                                                     | Advisory                                                        | Mitigation / planned action                                                                                                                                                           |
| ------------------------------------------- | ------------------------------------------------------------ | --------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `next` 14.x (web)                           | critical/high (RCE incl. Windows-hosted, SSRF, DoS families) | patched in `>=15.5.24` etc.                                     | **Planned: Next.js 14→15 upgrade as its own tested change.** Mitigations now: dev-only exposure, loopback binding in production compose, WAF/reverse-proxy in front, track advisories |
| `vitest` 1.x (dev only)                     | critical (UI server file read/exec)                          | patched `>=3.2.6`                                               | Dev-only, never ships; UI server not used in CI (`vitest run`). Planned: vitest 3 upgrade with the Next 15 pass                                                                       |
| `vite` / `glob` / `postcss` (dev toolchain) | high                                                         | patched versions available                                      | Build-time only; upgrade with the toolchain pass above                                                                                                                                |
| Python (`apps/api`, `apps/worker`)          | not scanned locally                                          | `pip-audit` not installed; no scanner added to avoid venv churn | Direct deps current-generation (FastAPI 0.142, SQLAlchemy 2.1, cryptography 50, httpx 0.28); CI security workflow + lockfiles apply; run `pip-audit` before any release tag           |

## What was NOT done (explicitly out of scope)

- No release tag created (gates are not all green — see §58 rule).
- No images published, no packages uploaded to npm/PyPI, no binaries built.
- No license change (MIT everywhere, verified consistent).
- No new features; no architecture rewrites.
