# Connector Versioning & Migration

Connector versions are `major.minor.patch` snapshots. Connections pin the
version they were created against (`connector_version`); workflows keep
working because execution enforces the pin.

## Rules

- `major` change → breaking: execution with a stale pin fails with
  `VERSION_MISMATCH`. Migrate explicitly (new connection or version bump).
- `minor/patch` drift → allowed, logged as `connector version drift` for
  review. No silent behavior change for majors.
- Snapshots are immutable: `connector_versions` rows store the manifest +
  `content_hash` at sync time. `manifest_hash` dedupes identical content.

## Migrate a connection

1. Check drift: `GET .../connectors/{id}` (current) vs connection's
   `connector_version`.
2. Review the new manifest: capabilities, action schemas, risk levels,
   required scopes.
3. Create a new connection on the new version with narrowed capabilities,
   attach credential, `POST .../test` (non-mutating).
4. Point workflows at the new connection; keep the old one until verified.
5. Export without secrets for review:

```json
{ "connector": "github", "version": "1.1.0", "capabilities": [], "credential": null }
```

Secrets are never exported — reconnect after import.

## Contract drift

Provider APIs change. Detect with contract tests
(`tests/test_connector_providers.py` + `validate_manifest_contract`):
manifest validity, schema conformance, auth, triggers, error mapping,
pagination caps, rate limits. Failures mean the provider changed, not the
framework — pin, then update the manifest + migration note.
