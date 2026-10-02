# Threat Model

## In scope

Account takeover, privilege escalation, tenant escape, malicious agent,
prompt injection, malicious tool/MCP, compromised connector, worker
compromise, sandbox escape, credential theft, insider threat,
supply-chain attack, data exfiltration.

## Boundaries & controls

User → Browser → API → Control Plane → Execution Plane → Worker →
Sandbox → External Service. Every boundary authenticates +
authorizes: sessions/MFA at login, RBAC+ABAC server-side, scoped
worker credentials, sandbox profiles + network policy, SSRF guards,
secret references only, redaction before logs/telemetry/models.

## Key guarantees (tested)

Deny-by-default; SSO/SCIM cannot create platform owners; IdP groups
cannot silently escalate; agents delegate subsets only; external
content never overrides policy/approval/limits; secrets never reach
models or logs; cross-tenant always denied; critical changes need
step-up; audit is append-only and hash-chained.

## Assumptions (explicit)

We trust: the host kernel/container runtime, TLS PKI, the IdP's own
authentication, and operators' Master credentials. We do NOT trust:
frontends, hidden URLs, obscure IDs, client roles, worker honesty,
external content, geolocation alone, or any single abuse signal.
