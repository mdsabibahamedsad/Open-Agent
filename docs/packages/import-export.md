# Import / Export

## Export

```bash
python scripts/openagent_package.py export ./my-workforce -o ./dist
# or POST /packages/{id}/versions/{version}/export
```

Produces a portable file map (`manifest.json`, `resources/…`,
`schemas/…`, `assets/…`, `integrity.json`). Export **aborts** when raw
secrets are detected — convert them to `credential_reference` /
`connection_reference` entries first. Asset uploads are validated (type,
MIME, size, no executables, no path traversal).

## Import

1. Parse bundle, require `manifest.json` + `integrity.json`.
2. Reject path traversal and unsafe filenames.
3. Verify per-file hashes + manifest content hash.
4. Check detached signatures when present (`verified` / `mismatch` / `absent`).
5. Re-run validation + security scan.
6. Preview changes (resources, dependencies, required configuration, risk) —
   no writes.
7. Create an org-scoped `DRAFT` package (`UNTRUSTED`, never implicitly PUBLIC).

```bash
python scripts/openagent_package.py import ./dist/acme.pkg-1.0.0.openagent-package.json
# or POST /packages/import
```

Import works fully offline — no cloud marketplace required (local-first).
