# Code Review — Structured Findings + Independence

```bash
POST /api/v1/code/review   # {task_id} or {filename, content}
```

## What the reviewer checks

Correctness, security, performance, maintainability, tests, API
compatibility, error handling, edge cases.

## Finding shape

```text
severity (INFO LOW MEDIUM HIGH CRITICAL — issue severities, not agent ranks)
file, line, category, finding, evidence, suggested_fix
```

Chain-of-thought stays hidden; structured findings are exposed and stored
(`code_reviews`, `code_review_findings`).

## Reviewer independence

Where configured, an independent Review Agent re-inspects the diff through
Multi-Agent Orchestration instead of trusting the coding agent's summary:

```text
Coding Agent → Independent Review Agent → Findings → Coding Agent (fix loop)
```

High/critical findings gate `COMMITTING` and `READY_FOR_PR` transitions;
`WAITING_FOR_APPROVAL` routes to a human under the MP19 approval system.

## Specialized coding roles

Capability profiles on the same Agent Runtime (not separate runtimes):
`Backend, Frontend, Database, DevOps, Security, Testing, Documentation,
Code Review, Research` agents. See `docs/code-agent/multi-agent.md`.
