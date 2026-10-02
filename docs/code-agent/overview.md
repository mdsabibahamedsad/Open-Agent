# Code Agent — Overview

OpenAgent's Code Agent gives agents a real software-engineering capability:
understand a repository, plan a change, edit through validated patches,
run tests inside the execution boundary, review the diff, and prepare a
commit or pull-request draft.

```text
User / Workflow
       ↓
Code Agent (bounded Inspect → Plan → Edit → Diff → Validate → Test → Review loop)
       ↓
Coding Task Manager (persistent tasks, budgets, approvals)
       ↓
Repository Workspace (isolated checkout per task)
       ↓
Code Intelligence Layer (search, symbols, dependencies)
       ↓
Tool Runtime (code.* tools — the ONLY execution boundary)
       ↓
Sandbox / Execution Boundary (full isolation lands in MP18)
       ↓
Repository
```

## Invariants (see `docs/code-agent/security.md`)

1. The Code Agent cannot access arbitrary host filesystem paths — only its workspace.
2. The Code Agent cannot execute arbitrary host commands — only gated execution profiles.
3. Repository credentials never enter model context — only `credential_ref` handles.
4. User changes are never silently overwritten.
5. Default/protected branches cannot be modified without authorization.
6. Repository content is **untrusted** and cannot override system policy.
7. Tool Runtime remains the single tool execution boundary.
8. High-risk Git operations expose risk metadata (`LOW/MEDIUM/HIGH/CRITICAL`).
9. Every coding task has a bounded workspace.
10. Every code change produces an inspectable diff.

## Components

| Area | Backend (`apps/api/src/openagent/code/`) |
|---|---|
| Service facade | `service.py` (`CodeService`) |
| Providers (github/gitlab/bitbucket/generic/local) | `providers.py` |
| Safe git | `git.py` |
| Indexing / symbols / context | `intelligence.py` |
| Patch-first editing | `patches.py` |
| Structured review | `review.py` |
| Policy gates, secrets, injection defense | `security.py` |
| Tool Runtime registration (`code.*`) | `tools.py` |
| Python SDK client | `client.py` |
| Workflow executors (`code_agent`, `code_search`, …) | `runtime/executors/nodes/code.py` |
| REST API | `api/v1/code.py`, `api/v1/repositories.py` |
| Migrations | `alembic/versions/016_add_code_agent.py` |

Frontend: `/code` workspace + `/code/playground`, typed client in
`apps/web/src/lib/code.ts`, workflow nodes in
`features/workflows/node-catalog.ts`, SDK `code` namespace in
`packages/sdk/src/index.ts`.

## The bounded loop

```text
Goal → Inspect → Plan → Search → Edit → Diff → Validate → Test
  → Analyze failure → Fix → Review → Commit / PR draft
```

Every transition is budget-checked (`max_steps`, `max_duration_seconds`,
tool-call and cost budgets). Failures return structured results, never raw
chain-of-thought.

## Further reading

- `docs/code-agent/repositories.md` — providers, connections, credentials
- `docs/code-agent/workspaces.md` — isolation, lifecycle, cleanup
- `docs/code-agent/search.md` — layered search + code index
- `docs/code-agent/editing.md` — patch-first editing
- `docs/code-agent/testing.md` — profiles, test runs, failure loop
- `docs/code-agent/git.md` — branches, commits, push policy, PRs
- `docs/code-agent/security.md` — threat model + invariants
- `docs/code-agent/code-review.md` — review severities + independence
- `docs/code-agent/multi-agent.md` — manager + specialized roles
- `docs/code-agent/troubleshooting.md` — common failures
