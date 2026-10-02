# OpenAgent Packages, Templates & Skills

MP22 foundation for reusable intelligence: agents, agent teams, workforces,
workflows, skills, prompts, tool/connector bundles, model/agent/workflow/
memory presets, automation recipes and template packages.

## Concepts

| Layer | Meaning |
|---|---|
| Definition | What the reusable object is (`reusable_packages`, `skills`, `presets`) |
| Version | Immutable snapshot (`package_versions`, `skill_versions`, `preset_versions`) |
| Package | Portable bundle (`openagent-package/` file map + `integrity.json`) |
| Installation | Tenant-scoped copy (`package_installations` + `installation_resources`) |
| Configuration | Reference-only values (credential/connection IDs, never secrets) |
| Execution | Existing runtimes (Agent, Workflow, Tools, Model Router, Memory, …) |
| Publication | Validated, signed, published version |
| Marketplace | Discovery over the catalog (commerce deferred to MP23) |

## Lifecycle

```
DRAFT → VALIDATING → VALIDATED → PUBLISHED → DEPRECATED → REVOKED → ARCHIVED
```

Published versions are immutable. Changes produce new versions
(`major.minor.patch[-prerelease]`, semver-compatible constraints with
`^ ~ >= <= = x ||` unions).

## Installation lifecycle

```
REQUESTED → RESOLVING → VALIDATING → AWAITING_CONFIGURATION →
INSTALLING → VERIFYING → INSTALLED (or FAILED)
```

Updates are planned first (`update-plan` → impact analysis → approval →
apply), with the previous version retained for rollback.

## Security invariants

1. Packages never bypass authentication, RBAC, organization/tool/connector/
   sandbox/approval policy, Tool Runtime, Sandbox, Human Approval or Model Router.
2. Packages never see secrets: only `credential_reference` / `connection_reference` IDs.
3. Imports are untrusted by default (`UNTRUSTED` trust, restricted network, sandbox required).
4. Trust tunes warnings — never permissions.
5. Published versions immutable; revoked versions cannot install or execute.
6. Prompt/skill/manifest text is untrusted data: it cannot override platform policy.

## Contents

- `manifest-spec.md` — stable bundle + manifest format
- `template-development.md` — building agent/workflow/workforce templates
- `skill-development.md` — building and composing skills
- `preset-development.md` — model/agent/workflow/memory presets
- `dependencies.md` — declarations, resolution, conflicts
- `publishing.md` — validation, signing, publication, sharing
- `import-export.md` — portable bundles, integrity, secret exclusion
- `security-model.md` — scanner, trust model, tenant isolation, RBAC
- `installation.md` — preview, install, update, rollback, uninstall
- `marketplace-architecture.md` — catalog, core/registry/marketplace/commerce separation

## API

Versioned under `/api/v1/organizations/{id}/`:

- `/packages` — CRUD, versions, validate/publish/deprecate/revoke, diff, security report, preview/install, fork, export/import
- `/skills` — CRUD, versions, publish, validate, attach to agent/workflow
- `/presets` — CRUD, versions, publish
- `/catalog/search`, `/catalog/categories` — provider-neutral discovery
- `/installations` — list/detail, update-plan/apply, rollback, uninstall

## UI

- `/templates` — Template Center (search, filters, grid/list, trust + installed badges)
- `/templates/[slug]` — overview, resources, workforce graph, security report, versions + diff, install wizard, fork, export
- `/skills`, `/skills/[id]` — browse, attach to agent/workflow
- `/presets` — model/agent/workflow/memory tabs
- `/settings/packages` — installed packages, updates, rollback, uninstall
- `/marketplace` — live catalog discovery (reviews/payments deferred)

## CLI / SDK

- `python scripts/openagent_package.py init|validate|build|export|import|inspect|install|publish|skill-init|template validate`
- TypeScript SDK: `createSDK(...).packages` (packages, skills, presets, catalog, installations)
- Python builders: `openagent.packages.builder` (`PackageDefinition`, `SkillDefinition`, `PresetDefinition`, `TemplateDefinition`, `Dependency`, validators, exporter/importer/installer facades)
