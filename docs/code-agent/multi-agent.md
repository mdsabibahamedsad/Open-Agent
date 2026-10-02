# Multi-Agent Software Engineering

Code work reuses the existing orchestration and management layers — no
second orchestration engine.

## Engineering manager shape

```text
Engineering Manager
├── Research Agent (docs, API references via Browser Engine)
├── Backend Agent
├── Frontend Agent
├── Testing Agent
├── Security Agent
└── Review Agent (independent; see code-review.md)
```

Manager responsibilities: task decomposition, assignment, dependency
management, result aggregation, conflict handling, review, final status —
via `orchestration_runs/tasks/dependencies`, delegation lifecycle, handoff
packages, and review gates.

## Parallel development

Independent tasks (frontend / backend / tests / docs) run in **separate
workspaces/branches**. Simultaneous conflicting writes to one workspace are
prevented. Task dependencies reuse the orchestration graph:

```text
Task A → Task B → Task C        Task A ─┐
                                        ├── Task C
                                Task B ─┘
```

## Memory & repository knowledge

The Memory Engine stores repository conventions, user coding preferences,
debugging findings, architecture decisions, successful fixes, task history —
repository-scoped where appropriate, and **never secrets**. A knowledge
layer (`remember_knowledge`) captures architecture, standards, build/test
commands, deployment, directory conventions, important modules, known
issues from `AGENTS.md, CONTRIBUTING.md, README.md, ARCHITECTURE.md,
DEVELOPMENT.md`:

```text
root instructions → directory instructions → file-specific context
```

…with system/platform/organization/security/tool/approval policy always
winning. Repository instructions are untrusted data.

## MCP & browser

Code-related MCP servers are reached only as `Code Agent → Tool Runtime →
MCP Adapter → MCP Server`. The Browser Engine is used for docs research, CI
dashboards, and issue trackers under its own security policies.
