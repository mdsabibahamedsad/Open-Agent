# Changelog

All notable changes to this project are documented here. We follow
[Semantic Versioning](https://semver.org/) and
[Conventional Commits](https://www.conventionalcommits.org/).

## [Unreleased] — Release hardening (MP30)

No application behavior changed. All entries are developer-experience,
packaging, deployment, documentation, or release-engineering work.

### Added

- `docker-compose.production.yml`: production overlay (required secrets via
  environment, DB/Redis on an internal network with no published ports,
  healthchecks, restart policies, loopback-only web/API bindings).
- `.env.production.example`: production template, placeholders only, with
  required-vs-optional grouping.
- `pnpm version` (`pnpm run version` — bare `pnpm version` prints the
  toolchain, a pnpm behavior): reports canonical platform version plus
  web/CLI/API/Python-SDK component versions from metadata, never hard-coded.
- `pnpm release:check`: read-only release gate (branch, clean tree, version
  agreement, required files, secret scan, single Alembic head, changelog
  entry, prod-config agreement, CLI dist present). Validates only; never
  publishes, pushes, or tags.
- `.github/workflows/release.yml`: tag-gated (`v*`) validation pipeline
  (install, lint, typecheck, unit, backend, docker build, migration check,
  SBOM, SHA-256 checksums). No registry publish step (no registry
  configured).
- `.github/ISSUE_TEMPLATE/security_report.yml`: private-report template
  pointing to `SECURITY.md`; no public vulnerability details.
- `docs/release/`: `release-readiness.md` (evidence-based READY/BETA/
  EXPERIMENTAL/PLANNED matrix), `release-notes.md`,
  `final-release-report.md`.
- `docs/deployment/`: `self-hosted.md`, `production-checklist.md`,
  `upgrading.md` (with rollback procedure: app/config rollback safe,
  database via tested backup/forward-fix, never blind downgrade).
- `docs/security/data-flow.md` (trust boundaries, where data may leave
  operator infra) and `docs/security/privacy.md` (self-hosted privacy).
- `THIRD_PARTY_NOTICES.md`: generated from installed dependency metadata.

### Fixed

- `apps/worker/pyproject.toml` contained npm JSON — replaced with valid
  Python packaging metadata (worker install/build/CI un-broken).
- All `clean` scripts were Unix-only (`rm -rf`) — now cross-platform
  Node `fs.rmSync`.
- Per-package `lint` ran ESLint with no config (always failed); now a real
  `prettier --check`. Added `apps/web/.eslintrc.json` so `next lint` runs
  non-interactively and reports genuine findings.
- `apps/web/Dockerfile` ran `pnpm install --frozen-lockfile` with no
  lockfile in build context — now `--no-frozen-lockfile`.
- Package sources formatted to the repo's declared prettier standard
  (formatting only, no semantic changes).

### Known Issues

- `next lint` (web): pre-existing errors (unescaped entities, conditional
  hooks in `workflows/[id]/edit`).
- `typecheck` (`@openagent/mcp`): pre-existing unused-import/missing-export
  errors.
- `build` (`@openagent/api-client`): pre-existing type error in test file.
- Web dev image runs as root; production multi-stage/non-root web image is
  documented future work. No release tag created (gates not all green).

## [1.0.0] - 2026-10-02 — Developer Platform (MP28)

First stable developer platform: one canonical extension architecture (single
type registry, permission catalog, and trust model — never parallel plugin
systems).

### Added

- Extension registry with 20 types (`agent`, `agent-team`, `tool`,
  `workflow-node`, `workflow-template`, `connector`, `mcp-server`,
  `mcp-tool`, `mcp-resource`, `mcp-prompt`, `skill`, `evaluator`,
  `memory-provider`, `model-provider`, `model-adapter`, `browser-extension`,
  `sandbox-profile`, `integration`, `ui-extension`, `automation-pack`).
- Strict `openagent.yaml` manifest schema (`manifest_version: "1"`) with
  cross-field rules (allowlisted egress, secret references only, no embedded
  credential material).
- Lifecycle pipeline: validate → test → build → package → security scan →
  compatibility check → sign → deploy → health check → activate, with
  quarantine and rollback to last known-good verified version.
- Permission enforcement (`check_permissions`): no self-grant, human approval
  for high-risk permissions (`network:restricted`, `browser:use`,
  `secret:access`), least-privilege defaults.
- Static security gates: secret detection blocks publishing (audited override
  only, forbidden in production); critical findings block publish and install;
  host install hooks refused.
- Ed25519 offline package signing (private keys never leave the publisher),
  `key_id` rotation, revocation enforced at verify time; deterministic
  `.oaext` archives with checksums, SBOM, and provenance.
- TypeScript SDK (`@openagent/sdk`) and Python SDK (`openagent-sdk`):
  agents, tools, workflows, connectors, MCP, memory, evaluations, extensions,
  events — Bearer auth, org scoping, idempotency keys, versioned events.
- CLI (`openagent`): `init/login/logout/whoami/dev/validate/test/
build/package/publish/deploy/rollback` plus `agents/tools/workflows/
connectors/mcp/skills/registry/marketplace/logs/runs/deployments/projects/
config/doctor/upgrade/generate/docs/migrate`; JSON/CI mode with exit codes.
- REST API: developer projects/environments, extension lifecycle
  (`validate/test/package/publish/sign/install/quarantine/rollback`),
  registry/webhooks/events/usage, public `sdk/errors/events` metadata;
  versioned developer events with HMAC-SHA256 webhook verification.
- Docs: `docs/developers/` (platform, SDK, CLI, 7 extension guides,
  publishing, versioning, migrations, API, security, threat model).
- Examples (14): `hello-agent`, `research-agent`, `calculator-tool`
  (safe parser, no `eval`), `custom-workflow-node`, `github-connector`,
  `telegram-connector`, `mcp-server`, `custom-skill`, `evaluator`,
  `multi-agent-workforce`, `browser-agent`, `sandbox-code-tool`,
  `enterprise-private-extension`, `python-tool`.
- Starter templates (10) under `templates/`: TypeScript/Python
  agent/tool, workflow-node, connector, mcp-server, skill, evaluator,
  full-extension — each with manifest, hello-world source, tests, README,
  packaging metadata, `.gitignore`.
- Compatibility matrix 1.x (`openagent >=1.0.0 <2.0.0`, `sdk >=1.0.0 <2.0.0`,
  extension API `1.x`, manifest `1`, API `v1`) with deprecation metadata and
  an SDK 0.x → 1.x migration guide.

### Security

- Extension threat model (`docs/developers/threat-model.md`) mapping 14
  threats (malicious package, dependency confusion, credential theft/leakage,
  prompt injection, tool/MCP abuse, sandbox escape, SSRF, priv-esc,
  cross-tenant, takeover, signature/registry/CI compromise) to platform
  controls.
- Secret-override policy: overrides require explicit reason, emit critical
  audited events, and are refused in production.
