# Publishing Extensions

Pipeline (orchestrated by `developer/service.py`):
`validate → test → build → package → security_scan → compatibility_check →
sign → deploy → health_check → activate`. Every transition is audited; deploys
record per-stage status on `extension_deployments`.

## 1. Validate

```bash
openagent validate
# POST /organizations/{id}/extensions/{eid}/validate
```

Runs the CREATE→VALIDATE gate: manifest schema, config JSON Schema,
dependency constraints, permission catalog membership, compatibility matrix,
and the static scan. Fix all errors; address warnings (missing `repository`,
undeclared events for connectors/MCP servers).

## 2. Scan

`developer/security.py::scan_files` checks every submitted file:

- high-confidence secrets (`SECRET_PATTERNS`) → **blocks publish**
- `critical` code findings (e.g. `docker-socket`) → blocks publish *and* install
- `high`/`medium` findings → warnings surfaced in the scan report stored on
  `extension_versions.scan_report`

## 3. Package

```bash
openagent build && openagent package
# POST .../extensions/{eid}/package  { files: {path: content} }
```

Produces a deterministic `.oaext` archive: sorted entries, stable
checksums, SBOM, and provenance (`built.filename`, `content_digest`,
`checksums`, `provenance`, `sbom`). Packaging **refuses host install hooks**
(`preinstall`/`postinstall`/`install` in `package.json`): builds must run
inside the sandbox (§87). The digest + size are stored on the version row and
the definition moves to `PACKAGED`.

## 4. Sign

Two-step offline signing — private keys never leave your machine:

```bash
openagent publish --sign
# 1) POST .../sign { key_id, public_key } -> { digest_sha256, key_id }
# 2) sign digest locally (Ed25519), then:
#    POST .../sign/complete { key_id, signature_b64 }
```

Verification failures raise a high-severity `signature.failure` security
event. Rotate via new `key_id`s; revocation is enforced at verify time
(`extension_trust_records.revoked`).

## 5. Publish

```bash
openagent publish
# POST .../extensions/{eid}/publish { files, allow_secret_override, override_reason }
```

### Secret-override policy

- Default: any secret hit → `422` + `credential.leakage_blocked` event.
  Remove the secrets and use `secrets:` references.
- Override (non-production only): pass `allow_secret_override: true` **with**
  a non-empty `override_reason`. This emits a `credential.override`
  **critical** event with actor + reason and is fully audited.
- Production: `OPENAGENT_DEV_ALLOW_SECRET_OVERRIDE` **must be `false`**
  (`DeveloperSettings.validate_production` refuses otherwise). Published
  packages must never contain secrets.
- Overrides never excuse `critical` code findings — those always block.

## 6. Review gates

After the automated gates, listings pass policy + review before appearing in
the catalog/marketplace: license compatibility, content sanitization + URL
safety, publisher verification tier, and trust-level assignment
(`CORE | VERIFIED | ORGANIZATION | COMMUNITY | UNTRUSTED`). Trust affects
review priority and default sandbox profile — never authorization.

## 7. Install & deploy

```bash
openagent deploy --env staging && openagent deploy --env production
```

Install (`POST .../install { version, environment, granted_permissions,
config_values }`) enforces: not `QUARANTINED`/`REVOKED`, version exists,
permissions known **and** ⊆ manifest declarations, approval records present
for gated permissions. Deploy walks
`validate,test,build,package,security_scan,compatibility_check,sign,deploy,health_check,activate`
with `deployment_health_timeout_s` (default 120s); on failure the deployment
is marked `FAILED` and `openagent rollback --installation <id>` restores the
last known-good verified version.
