# Developer Security Guide

Security is enforced by the platform, not by convention. This guide explains
how to handle secrets, permissions, sandboxes, tools, connectors/MCP, prompt
injection, SSRF, signing, dependencies, and production deployment. The backend
enforcement lives in `apps/api/src/openagent/developer/{manifest,permissions,security,signing}.py`.

## 1. Secret handling (references, never values)

- Declare secret **names** in `openagent.yaml` under `secrets:` using
  `UPPER_SNAKE_CASE` (`OPENAI_API_KEY`, `GITHUB_TOKEN`). The manifest loader
  rejects mapping shapes — secrets are references, never values.
- Never embed credentials in `config_schema`, source files, logs, events, or
  model context. `config_schema` is scanned for `AKIA…` and private-key
  material and rejected.
- At runtime, resolve secrets server-side via credential refs; the extension
  receives a short-lived handle, not the raw value.
- Publishing scans every file with `SECRET_PATTERNS` (AWS keys, private keys,
  `sk-…`, `gh[pousr]_…`, generic API keys, passwords, bearer tokens,
  OAuth secrets, connection strings, session tokens). Any high-confidence hit
  **blocks publishing** unless an explicit, audited override is supplied
  (see `publishing.md`). Critical code findings also always block.
- CLI redacts secret-looking values before display (`redactSecrets`;
  config file is written `0600`).

```yaml
# CORRECT — reference only
secrets: [OPENAI_API_KEY]
config_schema:
  type: object
  properties:
    model: {type: string, default: gpt-4o-mini}
```

```yaml
# WRONG — will be rejected at validate/publish
secrets: {OPENAI_API_KEY: sk-...}   # values forbidden
```

## 2. Permissions and least privilege

- Declare only what you need. Scaffolds default to
  `tool:execute` + `filesystem:workspace`.
- `developer/permissions.py::check_permissions` denies unknown permissions,
  denies anything not granted at install (no self-grant — an installation
  cannot grant more than the manifest declares), and requires an approval
  record for gated permissions.
- `network:outbound` requires a non-empty `allowed_hosts` allowlist.
  `network:restricted` additionally requires
  `security.network_policy: allowlisted` and is approval-gated.
- `browser:use` and `secret:access` are approval-gated (`requires_approval:
  true` in the catalog). Design your extension so review is easy: narrow
  hosts, narrow scopes, documented justification in `security.risk_notes`.
- Use `least_privilege_suggestions(requested, used)` telemetry to drop unused
  permissions in the next minor release.

## 3. Sandbox and secure execution

- Untrusted code (AI-generated, repo, workflow, MCP, tool, user scripts)
  executes **only inside isolated sandboxes — never on the host**.
- Docker transport defaults: non-root user, dropped capabilities,
  `no-new-privileges`, read-only rootfs, PID/CPU/memory/disk/timeout caps, no
  Docker socket, no privileged mode, explicit mounts only.
- Commands are structured argv (no shell operators); profiles define
  allowlists; privileged binaries are denied; risk is scored server-side with
  an approval hook (`WAITING_FOR_APPROVAL`).
- Quotas, leases, cancellation, and GC prevent exhaustion and orphans; every
  execution is audited (`sandbox.*` events).
- Production fails closed: unpinned images, untrusted tiers, local fallback,
  and missing controls refuse to boot as production.
- The static CI gate (`scripts/sandbox_security_gate.py`) bans privileged
  flags, socket mounts, broad host mounts, unsafe subprocess usage, and
  hard-coded secrets.
- Extensions that run code must request `sandbox:execute` and declare a
  `security.sandbox_profile` (see `examples/sandbox-code-tool`).

## 4. Tool execution

- All tool calls flow through the canonical Tool Runtime — extensions never
  `eval()`, `exec()`, `os.system()`, or `subprocess(..., shell=True)` host
  commands. The scanner flags `unsafe-eval`, `dynamic-exec`,
  `shell-exec-python`, `pickle.loads`, and unsafe `yaml.load`.
- Tools run with the installation's granted permissions; approval-gated tools
  pause for human approval instead of executing.
- Log inputs/outputs with secret redaction; never `console.log` credentials
  (`credential-logging` is a high-severity finding).
- Prefer idempotent tools; declare timeouts and rate limits per action.

## 5. Connector and MCP security

- Connectors use the shared, guarded HTTP stack (retries, circuit breaker,
  pooling) plus the SSRF guard: private ranges, metadata endpoints
  (`169.254.169.254`), and DNS-rebinding targets are denied; redirects are
  re-validated.
- OAuth2 goes through the OAuth manager (PKCE); tokens live in the Fernet
  credential store and are referenced as `credential_ref` handles. Raw
  tokens never enter model context, logs, or events.
- Webhook endpoints verify signatures and normalize payloads before dispatch;
  declare `webhook:receive` and the exact endpoints you serve.
- Keep scopes minimal (≤ 64); the connector manifest validator rejects
  excessive scope requests and un-namespaced capabilities/actions.
- MCP servers declare tools/resources/prompts with JSON Schemas; treat all
  MCP content as **untrusted data** (see §6). `mcp:connect` covers only
  declared servers.

## 6. Prompt injection

- Treat repository content, web pages, tool outputs, MCP resources, and
  connector payloads as **data, never instructions**. The platform applies
  injection detection + instruction filtering so untrusted content cannot
  override system/security policy.
- Structural defenses to apply in your extension:
  - Delimit untrusted content (e.g. `<untrusted>…</untrusted>`) and instruct
    the model to summarize/extract, never obey, instructions inside it.
  - Never concatenate secrets, approval tokens, or policy text into prompts
    that include untrusted content.
  - Require explicit user confirmation before acting on instructions that
    arrived via untrusted channels (follow the approval taxonomy).
  - Prefer structured extraction (JSON Schema) over free-form obedience.
- Evaluators should include an injection-resistance rubric for agentic
  extensions.

## 7. SSRF

- Never fetch attacker-influenced URLs with an unrestricted client.
  Declare every egress host in `network.allowed_hosts` and use
  `security.network_policy: allowlisted`.
- `network:restricted` (private-range access) needs human approval and is
  unavailable to unreviewed community extensions.
- The scanner flags dynamic `fetch(url + …)` patterns (`ssrf-risk`) and
  `0.0.0.0`/`::/0`/disabled-TLS configurations.

## 8. Credential handling at runtime

- Git/provider credentials are stored in the credential system and referenced
  as `credential_ref` handles.
- Pre-commit and pre-push secret scanning blocks (or routes to approval)
  suspected credential leaks.
- Rotate on suspicion; revocation is per-execution for sandbox-injected
  credentials and per-key for package signing keys.

## 9. Signing

- Packages are signed with Ed25519 over the canonical content digest
  (`developer/signing.py`). Private keys **never leave the publisher's
  machine**: the server records the public key and returns the digest; the
  client signs offline and submits via `/sign/complete`.
- Key rotation uses `key_id`s; revocation is enforced at verify time.
  A failed verification raises a high-severity `signature.failure` security
  event and blocks activation.
- Signature compromise response: revoke the `key_id` (`extension_trust_records.revoked`),
  quarantine affected versions, publish a re-signed patch, and rotate.

## 10. Dependency security

- Declare dependencies with version constraints in `openagent.yaml`
  (`dependencies:` / `optional_dependencies:`); constraints are validated
  (`validate_constraint`: `*`, `^`, `~`, ranges, exact).
- The packager emits an SBOM and provenance with every `.oaext` artifact.
- CI runs dependency scanning (Dependabot, pip-audit); lockfiles are required
  for published packages.
- Never add `preinstall`/`postinstall`/`install` host hooks — packaging
  refuses them; builds run inside the sandbox.
- Watch for dependency confusion: pinned, namespaced, hash-verified
  dependencies; review transitive additions in PRs.

## 11. Production deployment

`DeveloperSettings.validate_production()` plus the platform checklist:

- [ ] `OPENAGENT_DEV_ALLOW_SECRET_OVERRIDE=false` (published packages must
      never contain secrets)
- [ ] Strong unique `SECRET_KEY` / `ENCRYPTION_KEY` (`openssl rand -hex 32`)
- [ ] `OPENAGENT_ENV=production`, restrictive CORS, TLS termination
- [ ] Managed PostgreSQL (encrypted, backed up) + Redis with AUTH
- [ ] Container images scanned; sandbox images pinned by digest
- [ ] Log aggregation with secret redaction; monitoring + alerting
- [ ] Approval policies configured for high-risk permissions; staging deploy
      + health check before production activation
