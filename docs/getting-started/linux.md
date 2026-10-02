# Linux

Covers Ubuntu/Debian-based systems; other distros follow the same pattern with their package manager.

## Options

1. **Docker Engine** (recommended) — `docker compose up --build`.
2. **Native + Docker infra** — `pnpm infra:up`, then `pnpm dev:local`.
3. **Fully native** — local PostgreSQL 15+ and Redis 7+, then `pnpm dev:local`. See [non-docker](non-docker.md).

## Prerequisites

```bash
# Node.js 20 LTS (NodeSource) — or use nvm/fnm
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs git python3.11 python3.11-venv

# pnpm
corepack enable
corepack prepare pnpm@8.15.0 --activate

# Docker Engine + Compose plugin
# https://docs.docker.com/engine/install/ubuntu/
```

Add your user to the `docker` group to run Docker without sudo: `sudo usermod -aG docker $USER` (log out/in after). Without it, prefix docker commands with `sudo` — see [troubleshooting](troubleshooting.md).

Verify: `pnpm doctor`.
