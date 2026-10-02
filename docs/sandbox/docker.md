# Sandbox — Docker Provider

## Hardened `docker create` (see `providers.docker_create_argv`)

- `--user 65532:65532` (non-root), `--cap-drop ALL`,
  `--security-opt no-new-privileges:true`, `--init` (reaping)
- `--pids-limit`, `--cpus`, `--memory` + `--memory-swap` (equal),
  `--stop-timeout`
- `--read-only` rootfs + `tmpfs /tmp` (`rw,noexec,nosuid`) where profiles allow
- `--network none` default; `sandbox-egress` bridge only with a
  configured egress filter (else fail-closed)
- Explicit `--volume` mounts only, each passing `validate_mount`
- Labels for org/sandbox traceability; image recorded with digest

Never: `--privileged`, added capabilities (`SYS_ADMIN`, `NET_ADMIN`,
`SYS_PTRACE`, …), socket mounts, broad host mounts. The CI static gate
fails on these patterns.

## Images (`infrastructure/docker/sandbox/`)

- `openagent-sandbox-base`: python + node + git + minimal utils, non-root
  `sandbox` user (uid 65532), pinned digests in production
- Language variants (`-python`, `-node`, `-go`, `-rust`, `-java`) extend
  base; no kitchen-sink tooling per image
- Trust tiers: `CORE` (platform) / `VERIFIED` (scanned+signed) /
  `ORGANIZATION` / `CUSTOM` (digest-pinned) / `UNTRUSTED` (LEVEL_4 only)
- Hooks (provider-neutral): vulnerability scan, malware scan, signature
  verification — no single-vendor dependency

## Rootless & daemon

Prefer rootless Docker where supported; otherwise non-root-in-container
is mandatory. Document host requirements (`docker.md` deployment
checklist). Daemon restart: sandboxes are reaped/recreated by the
manager; executions are re-runnable from persisted requests, never
resumed mid-stream.

## Kubernetes / stronger isolation (future)

`KubernetesSandboxProvider` exists as a fail-closed stub — same
`SandboxProvider` protocol for Docker, Kubernetes, Firecracker, gVisor,
microVM, WASM, cloud execution. No full orchestration in MP18 (non-goal).
