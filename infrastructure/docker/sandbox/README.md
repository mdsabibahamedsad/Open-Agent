# Sandbox image build & deployment notes (see docs/sandbox/docker.md).

## Build (versioned, then pin)

```bash
docker build -t openagent-sandbox-base:0.1.0 -f Dockerfile.base .
docker build -t openagent-sandbox-python:0.1.0 -f Dockerfile.languages --target python .
docker images --digests openagent-sandbox-base
```

Record the digest in production:

```bash
SANDBOX_IMAGE=openagent-sandbox-base
SANDBOX_IMAGE_DIGEST=sha256:<digest>
```

## Egress network for filtered modes (optional)

Only needed when profiles use ALLOWLIST/RESTRICTED with a filtering proxy.
Without it those modes fail closed (by design).

```bash
docker network create sandbox-egress
```

## Rootless (preferred where supported)

```bash
dockerd-rootless-setuptool.sh install
export DOCKER_HOST=unix://$XDG_RUNTIME_DIR/docker.sock
```

The API host still talks to its own daemon socket; sandboxes never do.

## Hardening checklist

- [ ] No `--privileged` anywhere (CI gate enforces)
- [ ] No socket mounts (CI gate enforces)
- [ ] Digests pinned in production (startup check enforces)
- [ ] Egress proxy allowlists mirror PACKAGE registries
- [ ] Images scanned + signed before VERIFIED tier
- [ ] `GET /api/v1/sandboxes/security/check` reports ok
