# Sandbox — Security Controls

Fail-closed everywhere: unknown modes, missing egress, over-cap profiles,
unresolvable credentials, and invalid config deny rather than degrade.

## Filesystem

- Workspace jail: relative paths only, `..` rejected, string containment +
  realpath containment for existing paths (symlink-escape defense)
- Forbidden mounts: `/`, home dirs, `/etc`, `/var`, `/proc`, `/sys`,
  `/dev`, and every socket name (`docker.sock`, `containerd.sock`, …)
- Writable targets limited to `/workspace`, `/tmp` (tmpfs
  `noexec,nosuid`), `/artifacts`; system targets forced read-only
- Workdir must sit inside the mounted workspace (or `/tmp` when allowed)

## Network

- Modes: `NO_NETWORK` (default) / `ALLOWLIST` / `RESTRICTED` / `FULL_OUTBOUND`
- Blocked always: loopback, private ranges, link-local, multicast,
  metadata IPs (`169.254.169.254`, …) and hosts
  (`metadata.google.internal`, …), `localhost*`, `*.docker.internal`
- `ALLOWLIST` enforces domain (+optional port) lists with subdomain
  matching; deny-lists override; every DNS answer revalidated
- Non-`NO_NETWORK` modes require `SANDBOX_EGRESS_PROXY` or refuse

## Processes & resources

- Mandatory CPU / memory (+swap cap) / disk / PID / timeout / output caps;
  server caps clamp profiles (excess = deny, not silent trim)
- `TIMED_OUT` → kill + `RESOURCE_LIMIT` events; OOM → `RESOURCE_LIMIT`
  with `oom_killed` + peak memory recorded
- Cancel: graceful stop → kill → provider restart hygiene; GC sweep
  removes expired sandboxes/leases/artifacts/old executions

## Credentials & secrets

- Ref-only: API takes `credential_refs`, never values; server-side
  resolver injects short-lived env; minimal base env (no host inherit)
- `FORBIDDEN_ENV_NAMES` can never be plain values or inherited
- Redaction (`redact_text/redact_dict`, reused) on stdout/stderr/logs/
  events/audit/artifacts; revocation event per execution; nothing
  credential-valued persisted

## Commands

- Structured argv; shell operators rejected unless the profile grants
  shell (LEVEL_3+); interactive shells need explicit grants
- Categories (`read/build/test/package/network/filesystem/process/system/
  privileged`) + per-profile allowlists; `privileged` binaries
  (`sudo/docker/kubectl/mount/…`) denied by default
- Package installs (`pip/npm/cargo`) treated as unsafe: need network
  policy + resource limits + approval policy

## Risk & approval

Server-side scoring over command, network, filesystem, credentials,
target env (production = CRITICAL + deny), agent identity. High-risk
without `approved: true` persists `WAITING` and returns
`WAITING_FOR_APPROVAL` — MP19 owns the UX; policy is never downgraded.

## Audit

`sandbox.created/destroyed`, `execution.requested/allowed/denied/
completed`, `network.denied`, `credential.injected/revoked`,
`artifact.created`, `approval.required`, `resource_limit` — tenant-scoped,
secret-free. Metrics mirror §71 names on the shared collector.
