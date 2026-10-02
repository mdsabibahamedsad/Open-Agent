# Security Policy

## Supported Versions

We provide security updates for the following versions:

| Version | Supported |
|---------|-----------|
| 0.1.x (current development) | ✅ |
| < 0.1.0 | ❌ |

## Reporting a Vulnerability

We take security vulnerabilities seriously. If you discover a security issue, please report it responsibly:

### Private Disclosure

**Do not open a public GitHub issue for security vulnerabilities.**

Instead, please email us at **security@openagent.dev** with:

- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)
- Your contact information

We will:
1. Acknowledge receipt within 48 hours
2. Provide a preliminary assessment within 5 business days
3. Work on a fix and coordinate disclosure timeline
4. Credit you in the security advisory (unless you prefer anonymity)

### Extension Security Reporting

Vulnerabilities in extensions, the extension supply chain (manifest
validation, packaging, signing, registry), or published packages
(`marketplace/packages/*`, `examples/*`, `templates/*`) are in scope and
follow the same private-disclosure process. Please include:

- Extension slug + version (`openagent.yaml` `name:`/`version:`) or package digest
- Whether the issue is in the platform gate (validation/scan/signing) or in
  extension code, and steps to reproduce via `openagent validate`/`test`
- Suspected impact (credential theft, sandbox escape, SSRF, priv-esc,
  cross-tenant, signature compromise — see `docs/developers/threat-model.md`)

Do not publish a proof-of-concept extension to the public catalog to
demonstrate an issue — quarantine/revoke actions are audited and malicious
test packages may be removed without notice.

### Public Disclosure Timeline

- We aim to patch critical vulnerabilities within 7 days
- We aim to patch high-severity vulnerabilities within 14 days
- We will coordinate public disclosure after a fix is available
- We request 90 days before public disclosure for non-critical issues

## Security Measures

### Authentication & Authorization

- JWT-based authentication with short-lived access tokens
- Refresh token rotation
- API key management with scoping
- Role-based access control (RBAC) for organizations
- Password hashing with bcrypt (cost factor 12)

### Data Protection

- Encryption at rest for sensitive data (API keys, secrets)
- TLS 1.3 for all network communication
- PostgreSQL with row-level security policies
- Automatic secret redaction in logs
- Secure password reset flows

### Application Security

- Input validation with Pydantic/Zod at API boundaries
- CORS configured per environment
- Security headers (CSP, HSTS, X-Frame-Options, etc.)
- Rate limiting on authentication endpoints
- SQL injection prevention via parameterized queries
- XSS prevention via React's built-in escaping

### Code Agent & Repository Security

- Every coding task runs in an isolated workspace; the agent has no
  arbitrary host filesystem access and no host shell — execution flows only
  through gated profiles (`TEST/LINT/TYPECHECK/BUILD/…`) behind Tool Runtime
- Git credentials are stored in the credential system and referenced as
  `credential_ref` handles; raw tokens/keys never enter model context, logs,
  or events
- Pre-commit and pre-push secret scanning blocks (or routes to approval)
  suspected credential leaks
- Repository content (README, comments, `AGENTS.md`, fixtures) is untrusted
  data: injection detection + instruction filtering prevent it from
  overriding system/security policy
- Protected branches cannot be modified without authorization; force push is
  denied by default; high-risk git operations expose risk metadata and
  approval hooks
- User changes are detected via `git status` and never silently overwritten
- Full control matrix in `docs/code-agent/security.md`

### Sandbox & Secure Execution

- Untrusted code (AI-generated, repo, workflow, MCP, tool, user scripts)
  executes only inside isolated sandboxes — never on the host
- Docker transport: non-root user, dropped capabilities,
  `no-new-privileges`, read-only rootfs, PID/CPU/memory/disk/timeout caps,
  no Docker socket, no privileged mode, explicit mounts only
- Network denied by default; allowlists need filtered egress or fail closed;
  localhost/private ranges/metadata endpoints/DNS-rebinding defended
- Commands are structured argv (no shell operators); profiles define
  allowlists; privileged binaries denied; risk scored server-side with an
  approval hook (`WAITING_FOR_APPROVAL`)
- Credentials are ref-only with server-side injection, redaction on every
  surface, and revocation per execution; never in model context
- Artifacts export through scanned, tenant-scoped storage refs —
  container paths never exposed
- Quotas, leases, cancellation, and GC prevent exhaustion and orphans;
  every execution is audited (`sandbox.*` events)
- Production fails closed: unpinned images, untrusted tiers, local
  fallback, and missing controls refuse to boot as production
- Static CI gate (`scripts/sandbox_security_gate.py`) bans privileged
  flags, socket mounts, broad host mounts, unsafe subprocess, and
  hard-coded secrets; full threat model in `docs/sandbox/threat-model.md`

### Infrastructure

- Docker images scanned for vulnerabilities
- Dependency scanning in CI/CD (Dependabot, pip-audit)
- Secrets only in environment variables, never in code
- Principle of least privilege for service accounts
- Regular security updates for base images

### Development Practices

- Mandatory code review for all changes
- Static analysis (TypeScript strict mode, mypy, ruff)
- Automated security testing in CI
- Pre-commit hooks for secret detection
- Regular penetration testing (planned)

## Threat Model

### Assets to Protect

1. **User credentials** - Password hashes, API keys, session tokens
2. **Organization data** - Agents, workflows, executions, secrets
3. **Model provider credentials** - API keys for OpenAI, Anthropic, etc.
4. **Execution logs** - May contain sensitive data
5. **Audit logs** - Security-relevant events

### Threat Actors

- External attackers (unauthenticated)
- Compromised user accounts
- Malicious insiders
- Supply chain attacks (dependencies)
- Malicious repository content (prompt injection, malicious build/test
  scripts, dependency confusion via cloned repos)

### Mitigations

| Threat | Mitigation |
|--------|------------|
| Credential theft | Short-lived tokens, rotation, encryption |
| Unauthorized access | RBAC, org-scoped resources, audit logs |
| Data exfiltration | Encryption, access controls, monitoring |
| Injection attacks | Parameterized queries, input validation |
| Supply chain | Dependency scanning, lockfiles, review |

## Secure Configuration

### Environment Variables

Never commit `.env` files. Use `.env.example` as template:

```bash
# Generate secure keys
openssl rand -hex 32  # For SECRET_KEY
openssl rand -hex 32  # For ENCRYPTION_KEY
```

### Production Checklist

- [ ] Use strong, unique `SECRET_KEY` and `ENCRYPTION_KEY`
- [ ] Enable HTTPS/TLS termination (reverse proxy)
- [ ] Configure restrictive CORS origins
- [ ] Set `OPENAGENT_ENV=production`
- [ ] Use managed PostgreSQL with encryption
- [ ] Use managed Redis with AUTH
- [ ] Enable database backups
- [ ] Configure log aggregation
- [ ] Set up monitoring and alerting
- [ ] Run security scanning on container images

## Vulnerability Disclosure History

| Date | CVE | Severity | Component | Status |
|------|-----|----------|-----------|--------|
| - | - | - | - | No known vulnerabilities |

## Security Contacts

- **Security Team**: security@openagent.dev
- **Maintainers**: maintainers@openagent.dev
- **PGP Key**: Available on request

## Bug Bounty

We do not currently offer a formal bug bounty program. However, we recognize and credit responsible disclosure in our security advisories and release notes.

## Compliance

OpenAgent is designed to support:
- SOC 2 Type II (planned)
- GDPR compliance (data portability, deletion)
- HIPAA considerations (no PHI by default)
- ISO 27001 alignment (planned)

For enterprise compliance requirements, contact enterprise@openagent.dev.