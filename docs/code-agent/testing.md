# Testing — Profiles, Runs, Failure Loop

## Execution boundary

The agent never calls `subprocess / shell / os.system` on the host. All
execution goes through `CodeExecutionProvider.execute(...)` behind an
execution **profile**:

```text
TEST LINT TYPECHECK BUILD PACKAGE DEV_SERVER MIGRATION CUSTOM
```

Each profile defines allowed commands, environment, network policy,
filesystem access, CPU/memory limits, timeout. MP18 implements the full
container sandbox behind this same interface.

```bash
POST /api/v1/code/execute                       # {workspace_id?, task_id?, profile, command}
POST /api/v1/code/tasks/{id}/tests/plan         # targeted + regression sets
```

## Discovery & planning

The agent inspects `package.json, pyproject.toml, pytest.ini, tox.ini,
Makefile, Cargo.toml, go.mod, pom.xml, gradle files, CI config` to discover
unit / integration / E2E tests, type checks, lint, build, static analysis.
`plan_tests` returns targeted tests first, then broader regression sets per
policy. Adapters: npm/pnpm/yarn, pytest, mypy, ruff, eslint, tsc, cargo,
`go test/vet`, gradle, maven, dotnet — via repository-aware profiles, never
hard-coded agent commands.

## Result model

`TestRun`: `id, task_id, command, status, exit_code, duration, passed,
failed, skipped, stdout_ref, stderr_ref, diagnostics`. Terminal output is
stored via the storage abstraction (tenant-isolated, retained, cleaned up)
— **never** unbounded blobs in Postgres, **never** secrets in the stream.

## Failure loop (bounded)

```text
Test failure → Parse error → Locate file/symbol → Inspect → Hypothesis
  → Patch → Retest → Pass (or exhaust retry budget → FAILED + findings)
```

Retry budgets are enforced; loops cannot run forever.
