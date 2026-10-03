# OpenAgent CLI (`@openagent/cli`)

Production-grade CLI for OpenAgent extension development and lifecycle management.

## Install (official package)

```bash
npm i -g @openagent/cli
openagent --version
```

> **WARNING: do NOT `npm install -g openagent`.** The unscoped name
> `openagent` on the public registry is an unrelated 212-byte placeholder
> owned by a third party — it installs successfully but provides no
> executable, which is exactly the `'openagent' is not recognized`
> symptom. The official package is **`@openagent/cli`** (binary name
> `openagent`). No global install? Use `npx @openagent/cli --help`.

## Quickstart (local automation, no server needed)

```bash
openagent setup --yes   # zero-config: runtime, AI, browser, health
openagent start         # dashboard opens automatically
openagent workflow run hello-ai
```

## Quickstart

```bash
export OPENAGENT_API_URL=http://localhost:8000
export OPENAGENT_API_KEY=<key>
export OPENAGENT_ORG_ID=<org>

openagent init ./my-ext --kind tool --language ts --name my-tool --yes
cd my-ext
openagent validate
openagent package --inspect
openagent publish --id <extensionId> --version 0.1.0
openagent deploy --id <extensionId> --version 0.1.0 --env production
```

## Auth

```bash
openagent login --api-key $OPENAGENT_API_KEY
echo $TOKEN | openagent login --token
openagent login                 # device flow (browser)
openagent whoami
openagent auth status
openagent logout
```

Secrets are never printed; `auth status` shows only the last 4 characters.

## Core lifecycle

| Command                         | Description                                                                                                                                  |
| ------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| `init [dir]`                    | Scaffold agent\|tool\|workflow-node\|connector\|mcp-server\|skill\|workflow-template\|evaluator\|model-provider\|full-extension (ts\|python) |
| `validate`                      | Offline manifest validation                                                                                                                  |
| `test [--id]`                   | Offline checks + `POST .../extensions/{id}/test`                                                                                             |
| `build`                         | `tsc --noEmit` / `compileall` presence check                                                                                                 |
| `package [--out] [--server-id]` | Deterministic `.oaext` + optional server packaging                                                                                           |
| `inspect <archive>`             | Verify checksums + list entries                                                                                                              |
| `publish --id --version`        | Secret-scan gate + `POST .../publish`                                                                                                        |
| `deploy --id --version`         | `POST .../deploy`                                                                                                                            |
| `rollback --id [--version]`     | `POST .../rollback`                                                                                                                          |
| `dev [--port 8899]`             | DEVELOPMENT MODE local server (`/manifest`, `/health`, `/mock/run`) with hot-reload                                                          |

## Developer API

```bash
openagent extensions list|get|create|validate|version|sign|sign-complete|install|disable|quarantine
openagent projects list|create|get|set-env
openagent webhooks list|create
openagent events|usage|deployments
openagent sdk
```

## Platform resources

```bash
openagent agents list|create|get|run
openagent tools list|get|test
openagent workflows list|create|get|run
openagent connectors list|get|test
openagent mcp list|get|create|test
openagent skills list|get|create|test
openagent registry search|install|update|remove|publish
openagent marketplace search|publish
openagent logs|runs list|runs get
openagent config list|get|set
```

## Utilities

```bash
openagent doctor
openagent upgrade
openagent generate <agent|tool|connector|node|mcp|skill|evaluator> <Name>
openagent docs [--out README.generated.md]
openagent migrate [--write]
```

## Environment variables

- `OPENAGENT_API_URL` (default `http://localhost:8000`)
- `OPENAGENT_API_KEY`
- `OPENAGENT_ORG_ID`
- `OPENAGENT_PROFILE` (default `default`)
- `OPENAGENT_CONFIG_DIR` (default `~/.config/openagent`)
- `NO_COLOR` disables colors; `--no-color` also works.

Config file: `~/.config/openagent/config.json` (mode 0600).

## CI usage

```bash
openagent validate --dir ./ext
openagent package --dir ./ext --out ./dist/ext.oaext
openagent publish --id $EXT_ID --version $VERSION --dir ./ext
```

Use `--json` for machine-readable output in CI.

## Exit codes

- `0` ok
- `1` error (incl. server errors; 404 surfaces the server message honestly)
- `2` validation / blocked publish
- `3` auth (missing org/key, 401/403)
- `4` network/timeout

## Deterministic packaging

`.oaext` is a deterministic zip (sorted entries, fixed mtime 2019-01-01, deflate-9, no extra fields) containing `manifest.json`, `files/**`, `SBOM.json`, `provenance.json`, `signatures.json` (empty), and `CHECKSUMS.sha256`. `inspect` verifies SHA-256 per file and rejects zip-slip paths.
