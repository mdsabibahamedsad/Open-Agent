# One-Click Windows Install

> Install once. Open once. Start automating.

No Node.js, npm, Python, Git, Docker, Ollama, or database setup required.
The installer and the built-in `openagent setup` flow handle everything.

## Option A — Installer (recommended for most users)

1. Download `OpenAgent-Setup.exe` from
   [releases](https://github.com/mdsabibahamedsad/Open-Agent/releases).
2. Double-click it, then click **Install OpenAgent**.
3. Wait for automatic configuration (runtime, database, AI, browser,
   health check), then click **Launch OpenAgent**.

What the installer does (per-user, no admin needed):

- Installs into `%LOCALAPPDATA%\OpenAgent` with separated application
  (`app/`, `runtime/`, `browser/`, `models/`) and user-data (`data/`)
  directories. Updates and uninstalls never touch `data/`.
- Creates Start Menu entries, a Desktop shortcut, an `openagent` command
  shim, optional start-with-Windows, an Add/Remove-Programs entry, and a
  `.openagent-workflow.json` file association (all under HKCU).
- Runs `openagent setup --yes` (system check, hardware profile,
  embedded Node.js, Ollama, model, browser, database, port, health check
  incl. the built-in **Hello AI** workflow) and starts the engine.

Uninstall: Start Menu → **OpenAgent Uninstall** removes the application
only. Pass `-Full` (with confirmation) to also remove user data.

## Option B — Zero-config setup from a shell

```powershell
npm install -g @openagent/cli   # or use the bundled runtime after install
openagent setup --yes           # fully automatic; add --offline to skip downloads
openagent start                 # dashboard opens automatically
```

Useful flags: `--skip-model` (finish AI later from the dashboard),
`--model <id>`, `--profile LOW|BALANCED|POWER`, `--ai-mode local|cloud|hybrid`,
`--data-dir <dir>`, `--offline`, `--start` (launch detached afterwards).

## After install

```powershell
openagent status     # running, port, health
openagent doctor     # full environment + AI + browser diagnostics
openagent workflow list
openagent workflow run hello-ai
openagent stop       # stop the background engine
openagent backup create / openagent backup list
openagent update --apply   # snapshot first, automatic rollback on failure
```

## Hardware profiles

Setup auto-detects RAM/CPU and picks `LOW` (<8 GB), `BALANCED` (8–16 GB),
or `POWER` (16 GB+) — controlling the recommended model (`qwen2.5:1.5b`
→ `7b` → `14b`), workers, and browser concurrency. Override with
`--profile`.

## Safe mode & recovery

- `openagent start --safe` runs core + database + UI only.
- The desktop supervisor (`openagent start --supervise`, used by the
  installer service path) restarts crashed engines with backoff and drops
  into recovery (safe) mode after repeated crashes instead of loop-crashing.
- `openagent reset --settings|--ai|--cache|--all` repairs bad state.

## Building the installer (maintainers)

```powershell
npm run package:windows   # portable zip + NSIS staging; builds Setup.exe if makensis exists
```

`tools/installer/windows/installer.nsi` wraps the PowerShell installer
(single source of truth) into `OpenAgent-Setup.exe`. Sign the output
before publishing. AI models ship as separate downloads (size) and are
pulled resumably by `openagent setup`.
