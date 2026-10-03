# OpenAgent Installation

Two official channels. Both run the same OpenAgent core engine. npm global
install is **never** required.

## Mode A — Normal user (no Node/npm/Git needed)

1. Download `OpenAgent-Setup.exe` from the GitHub Releases page.
2. Run it (per-user install into `%LOCALAPPDATA%\OpenAgent`, no admin needed).
3. Launch OpenAgent from the Desktop / Start Menu shortcut.
4. First-run setup runs automatically (`openagent setup --yes`), then the
   dashboard opens.

What the installer does for you: hardware detection, local runtime layout,
`%LOCALAPPDATA%\OpenAgent\data` directory, shortcuts, optional
start-with-Windows, and the engine health check.

Portable alternative: download `OpenAgent-Portable.zip` (built as
`dist/openagent-win-x64.zip` by `npm run package:windows`), extract, and run
`bin\openagent.cmd start`. Nothing is installed globally.

## Mode B — Developer (one command)

```cmd
git clone https://github.com/mdsabibahamedsad/Open-Agent.git
cd Open-Agent
setup.cmd
```

or:

```powershell
powershell -ExecutionPolicy Bypass -File setup.ps1
```

Then:

```cmd
openagent-dev.cmd doctor
openagent-dev.cmd start
```

`setup.cmd` detects OS/arch/Node/Git/pnpm/RAM/CPU, creates per-user local
directories, installs dependencies, builds the CLI, generates `.env` (never
overwrites), runs `openagent setup --yes`, runs `openagent doctor`, creates
the repo-local `openagent-dev.cmd` launcher, and runs CLI smoke tests.

## Optional: npm CLI for developers

```bash
npm install -g @openagent/cli
```

> The bare name `openagent` on npm is an unrelated placeholder package — do
> not install it. The official CLI package is `@openagent/cli` and provides
> the `openagent` command. npm is optional; prefer Mode A or B.

Verify any install with: `openagent --version`, `openagent --help`,
`openagent doctor` — all work from any directory (e.g. your Desktop).

See also: [WINDOWS.md](WINDOWS.md), [DEVELOPMENT.md](DEVELOPMENT.md),
[CLI.md](CLI.md), [TROUBLESHOOTING.md](TROUBLESHOOTING.md).
