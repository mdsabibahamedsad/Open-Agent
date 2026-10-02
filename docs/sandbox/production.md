# Sandbox — Production Deployment

## Requirements

- Docker with `--init` support; rootless preferred, else enforced
  non-root-in-container (uid 65532)
- Pinned image digests (`SANDBOX_IMAGE_DIGEST`); trust tier
  `CORE/VERIFIED/ORGANIZATION`; no `UNTRUSTED`
- `SANDBOX_NETWORK_MODE=NO_NETWORK` unless a filtered egress proxy is
  deployed (`SANDBOX_EGRESS_PROXY`)
- `SANDBOX_PROVIDER=docker`; local fallback disabled (refused anyway)
- Redis + Postgres (existing); storage backend for artifacts/logs
- Credential resolver wired (org-scoped, decrypt server-side)

## Startup check (`GET /api/v1/sandboxes/security/check`)

```text
Sandbox Security Check
Docker available: YES (server 26.x)
Provider: docker
Local fallback: disabled
Default network: NO_NETWORK
Limits: cpu=4 mem=8192MB disk=20480MB pids=1024 timeout=3600s
Image pinning: sha256:… (pinned)
Credential isolation: ENABLED (ref-only + redaction)
Artifact isolation: ENABLED (storage refs)
Audit logging: ENABLED
```

Critical failures raise at startup (fail-closed) — production never
boots into an unsafe mode that looks safe.

## Development vs production

Dev may use explicit `SANDBOX_PROVIDER=local` +
`SANDBOX_ALLOW_LOCAL_FALLBACK=true` with loud warnings; relaxed limits;
debug output. Production requires the checklist above. The mode comes
from `OPENAGENT_ENV` and is reported by every check — silent fallback
is a bug, tested as such.

## Deployment checklist

Daemon hardened (no TCP without TLS, user-namespaces where possible);
egress proxy allowlists mirror `PACKAGE` registries; image pull policy
pinned; log/metrics pipeline secret-safe; quotas sized per tenant;
sweep scheduled; backups exclude live container state (DB holds truth).
