# Enterprise Identity Architecture (Master Prompt 27)

## Existing systems reused (not rebuilt)

* Passwords: Argon2id (`core/security/password.py`); sessions + cookies
  (`services/auth.py`, `sessions` table); Master Account
  (`platform_owners` + step-up in `control/privileged.py`); RBAC +
  teams + permissions (`services/authorization.py`); API keys
  (hash/prefix/expiry/last-used); service accounts (scoped perms);
  OAuth PKCE/state (`connectors/oauth.py`); SSRF engine
  (`connectors/netsec.py`); audit logs + security events; IP policy +
  session/key/rotation policy (`control/enterprise.py`); approvals,
  evaluator, sandbox profiles, connector policies, commerce
  entitlements; credential encryption (`connectors/crypto.py`).

## New: `openagent/identity/`

| Module | Covers |
|---|---|
| `types` | 8 identity categories, lifecycle, IdP types, AAL, device trust, risk, SECRET classification |
| `lifecycle` | validated transitions, tombstones, deprovision-preserving registry |
| `providers` | `IdentityProvider` ABC + local provider (self-hosted, no IdP) |
| `oidc` | discovery, PKCE login, pinned-alg JWT validation (iss/aud/exp/skew/nonce) |
| `saml` | metadata, SSO, assertion checks (time/aud/recipient/replay/NameID/attrs), injected signature verifier (never skipped) |
| `sso` | config validation, DNS/file domain verification, single-claim registry, JIT (owner never auto), safe group mapping, test preview |
| `scim` | filter subset, pagination caps, closed PATCH vocab, privilege-attr rejection, rate buckets, credential model |
| `abac` | layered authorizer, RBAC adapter, ABAC rules, classification gate, deny-by-default |
| `trust` | devices, session risk, AAL step-up, prompt revocation registry |
| `mfa` | TOTP (RFC 6238 stdlib), WebAuthn hooks (maintained lib), recovery codes (Argon2id), org enforcement |
| `tokensvc` | exp/scope/issuer/audience/revocation/rotation, no perpetual admins |
| `workload` | workload identity, scoped single-use leases, model-secret boundary |
| `network` | workload→destination policy + local SSRF floor (full netsec engine when importable) |
| `ai_security` | untrusted-content hooks, delegation subsets, tool/MCP/memory gates |
| `dlp` | high-confidence patterns, classify/redact/allow |
| `secpolicies` | versioned policies, simulator, compliance controls, posture, drift |
| `notifications` | connector-framework payload builders |

## Boundaries

AuthN ≠ AuthZ ≠ Zero-Trust ≠ Compliance — separate modules, separate
decisions. Control plane (`control/`) governs; identity verifies.
Approval requirements survive SSO/SCIM/role mappings.
