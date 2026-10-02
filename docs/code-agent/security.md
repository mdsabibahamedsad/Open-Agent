# Code Agent — Security

Repository content is **untrusted data**. It must never override system,
organization, tool, credential, sandbox, or approval policy.

## Threats & controls

| Threat | Control |
|---|---|
| Path traversal (`../../etc/passwd`) | `validate_workspace_path` jail; host paths never leave the server |
| Arbitrary file access | workspace-scoped reads; size + binary limits |
| Git credential leakage | `credential_ref` handles only; `redact_text/redact_dict`; secrets never in prompts, logs, events |
| Secret leakage in code | pre-commit + pre-push secret scan (`scan_text_for_secrets`); block or `WAITING_FOR_APPROVAL` |
| Repository isolation breach | per-task workspace; tenant-scoped queries; `cross-tenant` tests |
| Branch protection bypass | protected-branch list + remote policy respected; force push denied |
| Command injection | no host shell; allow-listed profiles; `command_allowed_by_profile` |
| Malicious repo content (README/`"ignore previous instructions"`, postinstall hooks, Makefiles, fixtures) | injection detection (`detect_repo_injection`), untrusted labeling, no host execution |
| Prompt injection | `filter_repo_instructions`: repository `AGENTS.md`/comments apply only when compatible with system policy |
| Dependency attacks | manifest/lockfile diffing; risky dependency changes flagged; scanner hooks |
| Supply-chain (malicious build scripts) | nothing executes outside the sandbox boundary (MP18 hardens it) |
| Artifact access | storage abstraction with tenant isolation, retention, access control |
| Unauthorized / force push | approval gates + `CRITICAL` risk metadata |
| Destructive git ops | policy-controlled; audit-logged |

## Tool risk classification

- `LOW`: read file, search, git history, diff, symbol lookup
- `MEDIUM`: edit code, create branch, run tests/lint
- `HIGH`: push branch, modify CI/infra, change dependencies, run migrations
- `CRITICAL`: force push, delete branch, production deploy, destructive infra, credential changes

Risk is surfaced to the approval system (`tool_requires_approval`); retry
safety is classified per tool (`is_retry_safe_tool`).

## Audit events

`repository.connected, repository.accessed, workspace.created/deleted,
branch.created/modified, code.patch.applied, code.execution.requested/blocked,
secret.detected, commit.created, push.requested/completed/blocked, pr.created`
— all tenant-scoped, all secret-free.

## Metrics

`code_tasks_total/success/failed, workspace_creation_duration,
repository_clone_duration, index_duration, search_latency,
patch_apply_latency, test_duration, test_failure_rate, review_duration,
commit_count, pr_count` + existing tracing.
