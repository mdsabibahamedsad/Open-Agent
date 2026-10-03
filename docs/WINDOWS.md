# OpenAgent on Windows

## One-click installer

`OpenAgent-Setup.exe` is an NSIS wrapper (`tools/installer/windows/installer.nsi`)
around a PowerShell installer (`tools/installer/windows/Install-OpenAgent.ps1`):

Welcome → installation directory (`%LOCALAPPDATA%\OpenAgent`) → hardware
detection → file install → runtime init → data directory → Desktop + Start
Menu shortcuts → optional startup → launch.

- Per-user install: no Administrator privileges required.
- Bundled/shimmed Node is used first (`runtime\node\node.exe`), system Node
  only as fallback — you never need to install Node.js yourself.
- Uninstall preserves `%LOCALAPPDATA%\OpenAgent\data` (workflows, agents,
  memory, settings). Use the uninstaller's Full option only to wipe data.
- Build it: `npm run package:windows` produces `dist/openagent-win-x64.zip`
  (+ `.sha256`), NSIS staging, and `dist/OpenAgent-Setup.exe` when `makensis`
  is available.

## Command-line tools (opt-in)

The installer appends `%LOCALAPPDATA%\OpenAgent\bin` (containing
`openagent.cmd`) to the **user** PATH — never system-wide. The shim launches
the bundled runtime, so it does not depend on npm's global bin mechanism.

## Portable mode

`OpenAgent-Portable.zip` layout after extraction:

```text
OpenAgent/
  bin/OpenAgent.cmd   shim: bundled runtime -> CLI -> engine
  app/cli/            self-contained CLI tree
  runtime/            embedded Node (when bundled)
  data/               your workflows/agents/memory (preserved on update)
  logs/ models/ browsers/ config/
```

## Developer bootstrap

`setup.cmd` / `setup.ps1` from the repo root. Details in
[DEVELOPMENT.md](DEVELOPMENT.md). The repo-local `openagent-dev.cmd` launcher
needs no PATH change.

Detailed guides: [getting-started/windows](getting-started/windows.md),
[getting-started/windows-one-click](getting-started/windows-one-click.md).
