# @openagent/desktop

Desktop controller for OpenAgent: the native-feeling launcher layer that owns
the local engine lifecycle so users never touch a terminal.

- `lifecycle.ts` — PID/port files, alive + `/health` probing, process-tree
  stop, dashboard auto-open.
- `supervisor.ts` — one supervised engine child, `/health` polling with
  HEALTHY/STARTING/DEGRADED/FAILED/RESTARTING states, backoff restarts,
  crash-counter recovery (safe) mode.
- `firstrun.ts` — first-run wizard state plus the Hello AI success test
  (Core, Database, AI, Workflow Engine, Browser).
- `updates.ts` — update check, snapshot-then-install with automatic rollback.

Used by the CLI (`openagent start/stop/restart/status`, `update --apply`)
and by the Windows installer (`tools/installer/windows/`).
