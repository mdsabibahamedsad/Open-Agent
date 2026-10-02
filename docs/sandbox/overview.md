# Sandbox — Overview

OpenAgent's Sandbox is the **single execution boundary** for untrusted
work: AI-generated code, repository code, workflow steps, tool calls, MCP
output, uploads, and user-provided commands never receive unrestricted
access to the OpenAgent host.

```text
User / Agent
      ↓
Authorization (RBAC, tenant context)
      ↓
Policy Engine (profiles, network, filesystem, env, command, risk)
      ↓
Execution Request (canonical, no hidden fields)
      ↓
Sandbox Manager (lifecycle, leases, quotas, artifacts, audit)
      ↓
Execution Profile (TEST, BUILD, …)
      ↓
Isolation Provider (Docker today; Kubernetes/Firecracker/gVisor tomorrow)
      ↓
Sandbox → Process
```

Never: `Agent → Host Shell`, `LLM → subprocess()`, `Workflow → arbitrary
host command`.

## Invariants (§97)

1. No agent directly executes host commands. 2. No workflow bypasses the
Sandbox. 3. No tool bypasses it when its capability needs execution.
4. Containers cannot reach the Docker socket. 5. Nor host credentials.
6. Nor other tenants' workspaces. 7. Network denied by default. 8. CPU /
memory / disk / PID limits mandatory. 9. Every execution authenticated +
authorized. 10. Every execution auditable. 11. Secrets never enter model
context. 12. Model instructions cannot override policy. 13. High-risk runs
hit the approval hook. 14. Production never silently uses dev settings.

## Components

| Area | Location |
|---|---|
| Policy engine | `apps/api/src/openagent/sandbox/security.py` |
| Profiles | `.../sandbox/profiles.py` |
| Providers (docker/local/k8s-stub) | `.../sandbox/providers.py` |
| Manager | `.../sandbox/service.py` |
| Tools (`sandbox.*`) | `.../sandbox/tools.py` |
| Python client | `.../sandbox/client.py` |
| Code Agent adapter | `.../sandbox/code_adapter.py` |
| Settings + prod checks | `.../sandbox/config.py` |
| Models / migration `017` | `db/models/sandbox.py` |
| API | `api/v1/sandboxes.py` (`/sandboxes`, `/sandbox-profiles`, `/sandbox-executions`) |
| Console + playground | `apps/web/src/app/sandbox/*`, `lib/sandbox.ts` |
| SDK | `sdk.sandbox` (`packages/sdk`), `SandboxClient` (Python) |

Isolation claim: Docker with non-root, dropped capabilities,
`no-new-privileges`, read-only rootfs, PID/CPU/memory limits, and no
socket mounts. Docker is **not** a perfect boundary — see
`docs/sandbox/threat-model.md` and `docs/sandbox/production.md`.

## Further reading

- `security.md` — controls matrix · `threat-model.md` — assumptions + residual risk
- `profiles.md` — the 9 profiles + levels · `network.md` — modes, allowlists, SSRF/DNS
- `filesystem.md` — jail, mounts, symlinks · `credentials.md` — ref-only injection
- `docker.md` — images, flags, rootless · `operations.md` — lifecycle, quotas, GC, config
- `production.md` — hardening + startup checks · `troubleshooting.md` — failure table
