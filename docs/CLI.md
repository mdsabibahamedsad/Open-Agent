# OpenAgent CLI

Works from any directory (e.g. `C:\Users\User\Desktop`). After the Windows
installer, `openagent` resolves via `%LOCALAPPDATA%\OpenAgent\bin`; for
developers via `npm install -g @openagent/cli` or repo-local
`openagent-dev.cmd`.

## Core

```cmd
openagent                  # welcome (outside a project) or help
openagent setup [--dev|--production|--minimal|--offline] [--yes] [--start]
openagent start [--port N] [--no-open] [--safe] [--daemon] [--supervise]
openagent stop | openagent restart | openagent status
openagent doctor [--fix]   # environment, auth, project, npm bin/PATH, AI, browser
openagent repair           # fix dirs, cache, stale pid, corrupt config (keeps workflows)
openagent update [--apply] | openagent version
openagent reset [--settings|--ai|--cache|--all] [--yes]
openagent logs [--limit N] | openagent config <list|get|set>
```

## Data & runtime

```cmd
openagent db <status|migrate|reset>        # local SQLite layout
openagent model <detect|list|install [id]|use <id>|doctor>
openagent browser <doctor|install|update>
openagent backup <create|list|restore> | openagent workflow ... | openagent agent ...
openagent node <list|install|create> | openagent mcp ... | openagent memory ...
openagent git [--init] | openagent git <status|remote|connect|auth|enable-auto-sync|sync>
```

## Notes

- `openagent setup` is the primary setup command; `--minimal` skips
  runtime/AI/model/browser; `--offline` skips everything needing internet.
- Ports are automatic: if the preferred port is busy the engine picks the
  next free one and saves it to local config.
- Every command is real. Anything not yet implemented reports
  `NOT IMPLEMENTED` instead of faking success.
