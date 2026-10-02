# Code Agent — Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `workspace CREATING` never becomes `READY` | clone URL unreachable; bad `credential_ref`; oversized repo | check `repository.status`, credential ref, size limits |
| `CodePolicyDenied` on push | unapproved push / protected branch / secret detected | approve explicitly, use task branch, remove secret |
| Patch `REJECTED` (stale context) | base changed since diff was generated | re-read file, regenerate patch against current content |
| Secret scan blocks commit | key/token-like string in diff | remove secret or route through `WAITING_FOR_APPROVAL` |
| Search returns nothing | workspace not indexed yet | run indexing; check `code_index_jobs` status |
| Semantic search weak | embeddings missing for language | falls back to text/symbol search (graceful degradation) |
| Test run `BLOCKED` | command not in profile allow-list | use a permitted profile command or extend the profile |
| Task `TIMED_OUT` | `max_duration_seconds` / step budget exhausted | raise budgets or split the objective |
| Task stuck `WAITING_FOR_APPROVAL` | high-risk op needs human (MP19) | approve / reject in the workspace UI |
| Cross-tenant `404` on valid id | tenant isolation working as designed | verify `organization_id` context |
| Events show `code.execution.blocked` | sandbox policy denied the command | inspect profile, network/filesystem policy |
| Review gates commit | HIGH/CRITICAL findings open | fix findings, re-review |

## Debugging checklist

1. `GET /api/v1/code/tasks/{id}` — status, step, risk.
2. `GET /api/v1/code/tasks/{id}/events?limit=100` — what actually happened.
3. `GET /api/v1/code/tasks/{id}/diff` — what changed.
4. `GET /api/v1/code/workspaces/{id}/status` — dirty? whose changes?
5. `POST /api/v1/code/review` — independent findings.
