# OpenAgent CLI Reference (`openagent`)

Binary: `openagent` (`@openagent/cli`). Config: `~/.config/openagent/config.json`
(`0600`), overridable with `OPENAGENT_CONFIG_DIR`. Env precedence:
`OPENAGENT_API_URL` / `OPENAGENT_API_KEY` / `OPENAGENT_ORG_ID` /
`OPENAGENT_PROFILE` win over the stored profile.

Global flags: `--profile <name>`, `--org <id>`, `--api-url <url>`,
`--json` (machine output), `--yes` (skip prompts), `-v/--verbose`.

Exit codes: `0` success · `1` general error · `2` validation/manifest error ·
`3` authentication/authorization · `4` publish blocked (security gate) ·
`5` network/timeout · `6` incompatible versions.

## Setup

| Command | Description | Example |
|---------|-------------|---------|
| `init [--type <t>] [--name <slug>] [--lang ts\|py] [--dir <d>]` | Scaffold `openagent.yaml` + `src/` + tests | `openagent init --type tool --name acme/calculator --lang ts` |
| `login [--api-url <u>]` | Store API URL + key, set active profile | `openagent login --api-url http://localhost:8000` |
| `logout [--profile <p>]` | Remove stored secrets for a profile | `openagent logout` |
| `whoami [--json]` | Show active profile, org, key tail | `openagent whoami` |
| `config list\|get <k>\|set <k> <v>` | Manage profiles / defaults | `openagent config set orgId org_123` |
| `doctor` | Check toolchain, auth, server reachability | `openagent doctor` |
| `upgrade` / `migrate` | Upgrade CLI / migrate project to SDK 1.x | `openagent migrate --from 0.x` |
| `generate <what>` | Scaffold manifest snippets, webhook handler | `openagent generate webhook-handler` |
| `docs <topic>` | Open local docs for a topic | `openagent docs publishing` |

## Lifecycle

| Command | Description |
|---------|-------------|
| `dev [--port 3939] [--mock]` | Local run with deterministic mocks (`developer/mocks.py`) |
| `validate [--manifest openagent.yaml]` | CREATE→VALIDATE gate: manifest, schemas, deps, perms, compat, secrets |
| `test [--filter <t>] [--seed <s>]` | Standard harness: per-type contract checks, sandboxed; seeded mocks |
| `build [--out dist/]` | Compile/bundle sources |
| `package [--out dist/*.oaext]` | Deterministic `.oaext` + checksums + SBOM + provenance; refuses host install hooks |
| `publish [--allow-secret-override --override-reason "..."]` | Security-gated publish (secret hits block; critical findings always block) |
| `deploy [--env staging\|production] [--version x.y.z]` | Walk deployment stages to activation |
| `rollback --installation <id>` | Restore last known-good verified version |

```bash
openagent init --type agent --name acme/greeter --lang ts
cd acme-greeter
openagent dev & openagent test
openagent validate && openagent build && openagent package
openagent publish --version 1.0.0
openagent deploy --env staging && openagent deploy --env production
```

## Resource commands

Each group supports `list/get/create/update/delete` (plus noted verbs) with
`--page/--page-size`, `--json`, and idempotency flags on mutating calls
(`--idempotency-key`):

- `agents` — `list/create/run/logs` (run an agent, tail logs)
- `tools` — `list/invoke` (`invoke <name> --arg k=v --arg-json data='{}'`)
- `workflows` — `list/create/execute/runs`
- `connectors` — `list/connect/invoke/webhooks` (OAuth connect, invoke action)
- `mcp` — `list/connect/call-tool/read-resource/get-prompt/servers`
- `skills` — `list/install`
- `runs` — `list/get/logs/cancel`
- `deployments` — `list/get/logs`
- `registry` — `list/search/pull/push` (local + cloud registries)
- `marketplace` — `search/install/publish` ; `publisher` — `profile/listings`
- `projects` — `list/create/members/envs`
- `logs` — `tail [--follow] [--run <id>]`

## CI / JSON usage

```bash
export OPENAGENT_API_URL=http://localhost:8000
export OPENAGENT_API_KEY="$OA_KEY" OPENAGENT_ORG_ID="$OA_ORG"

openagent validate --json > validate.json
openagent test --json | tee test.json
openagent package --json | tee package.json
openagent publish --json || exit $?
```

`--json` prints a single JSON object (`{ok, data|error, request_id}`) and
never colorizes; secrets are redacted. In CI, fail the job on non-zero exit;
archive `validate.json`/`test.json`/SBOM for audit.

## Environment variables

| Variable | Purpose |
|----------|---------|
| `OPENAGENT_API_URL` | API base (default `http://localhost:8000`) |
| `OPENAGENT_API_KEY` | Bearer token (never commit) |
| `OPENAGENT_ORG_ID` | Default organization scope |
| `OPENAGENT_PROFILE` | Config profile name |
| `OPENAGENT_CONFIG_DIR` | Config dir override |
| `OPENAGENT_DEV_ALLOW_SECRET_OVERRIDE` | Server-side; must be `false` in production |
