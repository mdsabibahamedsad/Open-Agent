# Sandbox — Network Policy

Default: `NO_NETWORK` (`--network none`). Anything else must be explicit
at platform → org → task → sandbox scope.

## Modes

- `NO_NETWORK` — no egress, full stop.
- `ALLOWLIST` — named domains (+optional ports); subdomain matching;
  deny-list wins; every resolved IP revalidated.
- `RESTRICTED` — deployment-defined filtered egress (proxy rules).
- `FULL_OUTBOUND` — LEVEL_4 + approval only; still blocks metadata/private.

## SSRF / metadata / DNS defenses (`sandbox/security.py`)

1. Reject local names (`localhost`, `*.docker.internal`, …) and metadata
   hosts before DNS.
2. Validate scheme (`http/https` only for URL checks) and ports.
3. Resolve, then validate **every** answer IP: loopback, private,
   link-local, multicast, reserved, unspecified, and metadata IPs
   (`169.254.169.254`, `169.254.169.123`, `fd00:ec2::254`) all denied.
4. Without `SANDBOX_EGRESS_PROXY`, non-`NO_NETWORK` execution fails
   closed (`sandbox.network.denied`).

## Operator setup

```bash
SANDBOX_NETWORK_MODE=NO_NETWORK
SANDBOX_EGRESS_PROXY=http://egress-filter:8080  # allowlist-enforcing proxy
```

The proxy (squid/tinyproxy/iptables set) must enforce the same domain
lists; the sandbox passes `HTTP(S)_PROXY` into the container and the
manager refuses to run filtered modes without it.

## What to test

`curl http://169.254.169.254/` → denied. `curl http://127.0.0.1/` →
denied. Unlisted domain under `ALLOWLIST` → denied with event. DNS that
resolves private → denied after resolution.
