# Repository Workspaces — Isolation, Lifecycle, Cleanup

## Model

```text
RepositoryWorkspace: workspace_id, organization_id, repository_id, task_id,
  branch, base_revision, current_revision, filesystem_root, status,
  created_at, updated_at
```

`status`: `CREATING READY BUSY DIRTY CHECKING TESTING COMMITTING ERROR
CLEANING DELETED`. `filesystem_root` is server-side only — **host paths are
never returned by the API** (`_ws_out` strips them).

## Isolation

```text
Code Agent → Workspace → Sandbox boundary → Repository
```

Every coding task operates inside its own workspace (default branch
`openagent/task/<task-id>`, configurable). Path validation
(`validate_workspace_path`) rejects `../../etc/passwd`-style traversal and
any path escaping the workspace root. The full container sandbox lands in
MP18; the interfaces it needs (`CodeExecutionProvider`, execution profiles,
artifact refs) already exist — see `docs/code-agent/testing.md`.

## Lifecycle

```bash
POST   /api/v1/code/workspaces                 # {repository_id, task_id?, branch?}
GET    /api/v1/code/workspaces?status=READY
GET    /api/v1/code/workspaces/{id}
GET    /api/v1/code/workspaces/{id}/status     # dirty flag, change count
POST   /api/v1/code/workspaces/{id}/branches   # {name}
DELETE /api/v1/code/workspaces/{id}?force=…
```

`GET .../status` inspects `git status` first: pre-existing user changes are
reported and the agent must distinguish `user changes / agent changes /
unknown changes` — it never overwrites unrelated work.

## Resource limits

Workspaces enforce `max repository size, max file size, max indexed files,
max context size, max patch size, max output size, max test duration, max
workspace count`. Binary, generated, vendor, `node_modules`, and build
output are excluded from indexing and context.

## Cleanup

After completion a workspace is `retain | archive | delete` per policy
(`sweep_workspaces` worker job). Temporary workspaces auto-clean. A
workspace holding uncommitted user changes is never deleted without
explicit policy.
