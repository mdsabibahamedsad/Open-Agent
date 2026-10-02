# Sandbox — Threat Model

## Untrusted inputs (all treated as potentially malicious)

AI-generated code, repository code, `pip/npm` install scripts, cloned
repos, workflow definitions, uploaded files, MCP-provided code,
tool-provided code, user scripts, generated shell, build/test scripts,
Dockerfiles, Makefiles, CI config, downloaded artifacts,
browser-downloaded files.

## Adversary capabilities (assumed)

- Executes arbitrary commands permitted by the profile allowlist
- Attempts path traversal, symlink/hardlink escapes, mount tricks
- Probes localhost, private IPs, cloud metadata (`169.254.169.254`),
  internal DNS; attempts DNS rebinding
- Fork-bombs, exhausts CPU/memory/disk/output, spawns daemons
- Hunts env vars, `/proc`, sockets, other tenants' mounts
- Exfiltrates via any permitted network path

## Controls (each mapped to code)

| Capability | Control |
|---|---|
| Host shell | No shell path exists: structured argv only (`security.parse_argv`), Tool Runtime mediation |
| Filesystem escape | Workspace jail + realpath containment + forbidden mounts incl. `docker.sock` (`validate_sandbox_path`, `validate_mount`) |
| Container escape | Non-root user, `--cap-drop ALL`, `no-new-privileges`, read-only rootfs, no socket mounts; CI gate bans `--privileged`/socket mounts |
| Network escape | `NO_NETWORK` default; allowlist needs deployment egress filter or fail-closed; literal + resolved IPs validated (loopback/private/link-local/metadata rejected) |
| DNS rebinding | Resolve-then-validate every answer (`validate_network_destination`) |
| Resource exhaustion | Mandatory CPU/memory/disk/PID/timeout/output caps; OOM → `RESOURCE_LIMIT` |
| Orphans/daemons | `--init` reaping, cancel → graceful stop → kill, GC sweep |
| Credential theft | Ref-only injection, minimal base env, redaction everywhere, revocation events, nothing persisted |
| Cross-tenant | Org-scoped queries, workspace-root containment, scoped caches, per-org quotas |
| Supply chain | Pinned digests (required in prod), trust tiers, scanner/signature hooks |
| Silent downgrade | Fail-closed config; production refuses local fallback/unpinned/untrusted |

## Residual risks (stated honestly, §112)

1. **Docker is not a perfect boundary.** Kernel exploits, misconfigured
   daemons, or privileged helpers can break containment. Stronger
   isolation (gVisor/Firecracker/microVM) is a designed future provider,
   not a current claim.
2. **Side channels** (timing, cache) are out of scope for containers.
3. **Egress filtering** for `ALLOWLIST`/`RESTRICTED` modes depends on the
   deployment proxy; without it those modes refuse to run (fail-closed).
4. **Image contents** are trusted per tier; scanning hooks exist but no
   bundled vulnerability database (non-goal).
5. **Local provider** (`SANDBOX_PROVIDER=local`) is explicitly NOT a
   boundary — dev-only, refused in production.
