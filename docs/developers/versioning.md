# Versioning (semver + 1.x compatibility + deprecations)

Enforcement: `apps/api/src/openagent/developer/versioning.py`
(`validate_semver`, `validate_constraint`, `satisfies`, `bump`,
`is_breaking_change`, `check_compatibility`, `DEPRECATIONS`).

## Semver

`version:` in `openagent.yaml` must be `MAJOR.MINOR.PATCH` with optional
`-prerelease`/`+build` (leading `v` accepted):

- `MAJOR` — breaking extension-API or config changes (requires migration
  notes + new compat entry).
- `MINOR` — backwards-compatible capabilities (new actions, optional config).
- `PATCH` — bug fixes, no schema change.

Bump with `openagent version [major|minor|patch]` (same rules as `bump()`).

## Constraints

Dependencies and `compatibility.sdk` use constraints:
`*`, `^1.2.3`, `~1.2.3`, `>=1.0.0 <2.0.0` (range), exact `1.2.3` / `=1.2.3` /
`==1.2.3`. Invalid constraints fail validation; `0.x` ranges treat any
change as potentially breaking (`is_breaking_change`).

## Compatibility matrix (1.x)

From `developer/types.py::COMPATIBILITY_MATRIX` (the only known-good
generation today):

| Slot | Value | Declared in |
|------|-------|-------------|
| `openagent` | `>=1.0.0 <2.0.0` | `compatibility.openagent` |
| `sdk` | `>=1.0.0 <2.0.0` | `compatibility.sdk` |
| `extension_api` | `1.x` | `compatibility.extension_api` |
| `manifest` | `1` | `manifest_version` |
| `api_version` | `v1` | `compatibility.api_version` |

`check_compatibility(openagent_version, sdk_constraint, extension_api)`
returns human-readable problems (empty = OK); `validate`/`test` surface them
before anything executes. Declare conservatively: if you only tested
`1.0.x`, say so in metadata — the matrix is a floor, not a promise.

## Deprecation metadata

Versions carry `deprecated: bool` (`extension_versions.deprecated`); the
code-level registry is `versioning.DEPRECATIONS`:

| Name | Status | Replacement |
|------|--------|-------------|
| `client.runs` | not deprecated | — |
| `client.agents.create` legacy positional args | **deprecated** | `client.agents.create({name, …})` → `docs/developers/migrations.md` |

Rule: deprecations are announced with `sunset_at`, `replacement`, and
`migration_guide` — never silent. Deprecated versions stay installable until
sunset, then move to `DEPRECATED` lifecycle (install refused, existing
installs keep running until redeployed).
