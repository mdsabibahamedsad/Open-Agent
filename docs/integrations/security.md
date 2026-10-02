# Integration Security (MP21)

## Boundaries

- **No secret leakage**: encrypted storage, masked reads, redacted logs,
  `credential_id` handles for models, capability-scoped resolution.
- **No unrestricted egress**: SSRF gate on every destination (schemes,
  localhost/private/link-local/metadata, DNS-rebinding via resolution
  checks, shorthand-IP normalization, redirect-chain validation).
- **No cross-tenant credentials**: org check on every connection/credential/
  webhook row; IDOR probes emit security events.
- **No unsafe custom code**: community connectors are data + declarative
  HTTP; custom code execution requires opt-in + Sandbox.
- **No policy/approval bypass**: engine gate is the only execution path;
  `approved=true` booleans are never proof (MP19).
- **No unbounded retrieval**: pagination caps, payload caps, quotas,
  circuit breakers, bulkheads via shared client.
- **No exfiltration**: scoped data access, PII redaction, retention
  policies, unusual-usage monitoring.

## Threat coverage

OAuth CSRF/replay, token replay, webhook forgery/replay, invalid
signatures, SSRF (incl. obfuscated IPs), credential leakage, malicious
connectors/responses, prompt injection in provider content, unsafe
redirects, upload abuse (type/size/name caps), oversized payloads,
rate-limit abuse, trust escalation, privilege escalation.

## Monitoring

Metrics (`connector_*`), health states, audit trail
(`connector.connected/disconnected/credential_rotated/action_executed/
action_failed/webhook_received/permission_changed/shared/revoked`),
security events for forgeries, replays, cross-tenant attempts, refresh
anomalies, and unusual usage.
