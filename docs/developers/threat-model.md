# Developer Threat Model

Scope: the extension supply chain — from author workstation to registry to
tenant runtime. Each threat lists platform controls (with backend pointers)
and what the extension author must still do.

## T1. Malicious extension / package

_Author ships code that exfiltrates data, mines crypto, or attacks tenants._

- Controls: strict manifest validation (`manifest.py`); static scan gate
  (`security.py::scan_files`, `blocks_publish`/`blocks_install`); sandboxed
  execution only (`sandbox:execute` boundary); least-privilege permissions
  with no self-grant (`permissions.py`); approval gates for high-risk
  permissions; quarantine + revoke (`service.py::quarantine_extension`);
  audit of every lifecycle transition; security events
  (`credential.leakage_blocked`, `signature.failure`).
- Author duty: request minimal permissions; document risk in
  `security.risk_notes`; keep dependencies pinned.

## T2. Dependency attack / dependency confusion

_Attacker publishes a same-named package or compromises an upstream dep._

- Controls: validated version constraints (`versioning.py`); SBOM +
  provenance per artifact (`packaging.py`); lockfiles required; CI
  scanning (Dependabot, pip-audit); no host install hooks (packaging
  refuses `preinstall`/`postinstall`); builds run in sandbox.
- Author duty: pin with `^`/`~`/exact ranges, review transitive adds, use
  namespaced package names.

## T3. Credential theft

_Extension or attacker reads tokens, keys, connection strings._

- Controls: secrets are server-side refs, never values (`manifest.py`
  cross-field rules); Fernet credential crypto; `secret:access` is
  approval-gated; secret redaction in logs/CLI (`redactSecrets`, 0600
  config); pre-commit/pre-push secret scanning.
- Author duty: declare `secrets:` names only; never log or return secrets;
  never put them in prompts or events.

## T4. Secret leakage (accidental publish)

_Author commits a key and publishes it._

- Controls: high-confidence secret patterns block publish
  (`SECRET_PATTERNS`); `config_schema` credential-material check; secret
  override requires explicit reason, is audited, emits a
  `credential.override` critical event, and is **forbidden in production**
  (`DeveloperSettings.validate_production`).
- Author duty: use `.env` + secret refs; run `openagent validate` before
  every publish.

## T5. Prompt injection (direct and indirect)

_Untrusted content (repo files, web pages, tool/MCP output) hijacks the agent._

- Controls: injection detection + instruction filtering at the runtime
  boundary; repository content treated as untrusted data; approval taxonomy
  for high-risk actions; evaluator rubrics for injection resistance.
- Author duty: delimit untrusted content, extract-don't-obey, confirm before
  acting on third-party instructions (see `security.md` §6).

## T6. Tool / MCP / connector abuse

_Confused-deputy calls: extension tricks the runtime into privileged actions._

- Controls: single engine-owned gates (Tool Runtime delegation for
  `connector:*` tools); capability-namespaced actions; `check_permissions`
  on every call; approval-bound resume for `WAITING` executions;
  `approval_id` verification in tool/browser/code/sandbox paths (client
  `approved` booleans are never proof).
- Author duty: declare exact capabilities; make mutating actions idempotent
  with timeouts and rate limits.

## T7. Sandbox escape

_Code breaks isolation to reach the host or other tenants._

- Controls: Docker hardening (non-root, dropped caps, `no-new-privileges`,
  read-only rootfs, caps on PID/CPU/mem/disk/time, no socket, explicit
  mounts); structured argv (no shell); allowlisted profiles; server-side
  risk scoring + approval hook; tenant-scoped artifact export; static CI
  gate banning privileged flags/socket mounts/unsafe subprocess.
- Author duty: stay inside the profile; never probe host paths, sockets, or
  metadata endpoints.

## T8. SSRF (server-side request forgery)

_Extension fetches internal/metadata targets via the platform network._

- Controls: SSRF guard (private ranges, metadata IP, DNS-rebinding
  defense); redirect re-validation; `network:outbound` allowlist
  requirement; `network:restricted` approval gate; scanner `ssrf-risk` rule.
- Author duty: allowlist explicit hosts; never fetch user-supplied URLs
  with a privileged client.

## T9. Privilege escalation (priv-esc)

_Extension gains permissions beyond what was granted._

- Controls: install cannot grant beyond manifest declaration (§86.10);
  `check_permissions` denies ungranted/unknown; trust never bypasses
  authorization (CORE == COMMUNITY at the policy gate); RBAC/ABAC + human
  approval cannot be bypassed by extensions (§86.1–4).
- Author duty: don't request broad permissions "just in case"; split
  privileged features into separate optional extensions.

## T10. Cross-tenant access

_Extension in org A reads org B's data._

- Controls: every row is organization-scoped; tenant isolation enforced at
  the DB/repository layer; global rows readable cross-tenant only via the
  catalog path with visibility checks; org-scoped install grants.
- Author duty: always pass the caller's org context; never cache across
  tenants; scope memory/storage per tenant.

## T11. Malicious maintainer / account takeover / package takeover

_Attacker takes over a publisher account or a popular package._

- Controls: publisher verification; offline Ed25519 signing (private keys
  never on server); `key_id` rotation + revocation enforced at verify;
  version pinning + digest checks on install; quarantine/revoke lifecycle;
  review gates on publish; audit trail per actor.
- Author duty: protect signing keys (hardware/secret store); rotate
  promptly; monitor `extension.quarantined` / `package.published` events.

## T12. Signature compromise

_Stolen signing key used to ship trojaned versions._

- Controls: `signature.failure` high-severity events; revocation lists
  checked at verify/install; rollback to last known-good verified version.
- Response: revoke `key_id`, quarantine versions, re-sign + publish patch,
  rotate keys, notify consumers via security advisory.

## T13. Registry compromise

_Attacker tampers with registry metadata or artifacts._

- Controls: content-addressed distribution (sha256 digests); archive
  traversal + bomb guards; signature verification independent of transport;
  transparency via audit chain and analytics; trust records per publisher.
- Author duty: verify digests on install; pin versions in production.

## T14. CI/CD compromise

_Attacker injects code via build pipeline or malicious PR._

- Controls: mandatory code review; static analysis (strict TS, mypy, ruff);
  secret detection pre-commit; sandbox security gate in CI; provenance
  attestation on artifacts; no host execution in builds.
- Author duty: branch protection, signed commits, minimal CI secrets,
  review dependency diffs.

## Control matrix (summary)

| Threat | Prevent | Detect | Respond |
|--------|---------|--------|---------|
| Malicious extension | manifest+scan+sandbox+perms | security events, analytics | quarantine/revoke/rollback |
| Dependency attack | pins+SBOM+no hooks | CI scanning | advisory + patched release |
| Credential theft | ref-only+redaction+approvals | leakage_blocked events | rotation + revocation |
| Secret leakage | publish gate | scan report | override audit / block in prod |
| Prompt injection | filtering+approvals | evaluator rubrics | human review, policy update |
| Tool/MCP abuse | engine gates+perms | audit log | disable, quarantine |
| Sandbox escape | hardening+argv+profiles | execution audit | lease kill, GC, advisory |
| SSRF | guard+allowlist+gates | scan + logs | block host, revoke perm |
| Priv-esc | no self-grant+policy gates | permission decisions | deny, disable |
| Cross-tenant | org scoping+visibility | audit | revoke install |
| Takeover | verification+signing | publish events | revoke keys, quarantine |
| Sig compromise | offline keys+rotation | signature.failure | revoke, re-sign, advisory |
| Registry compromise | digests+traversal guards | digest mismatch | rollback, advisory |
| CI/CD compromise | review+gates+provenance | CI failures | revert, rotate CI secrets |
