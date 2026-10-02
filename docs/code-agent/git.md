# Git — Branches, Commits, Push Policy, PR Drafts

## Safe git abstraction

`openagent/code/git.py` wraps `clone fetch checkout create_branch
switch_branch status diff log show add commit push pull merge rebase tag`.
Destructive operations (force push, branch delete, reset) are
policy-controlled and surface `CRITICAL` risk. Supported remotes: GitHub,
GitLab, Bitbucket, generic git, local — via provider adapters.

## Branch management

One isolated branch per coding task, default `openagent/task/<task-id>`
(configurable strategies). The agent **never silently modifies the user's
default branch**.

```bash
POST /api/v1/code/workspaces/{id}/branches   # {name}
POST /api/v1/code/tasks/{id}/commit          # {message}
POST /api/v1/code/tasks/{id}/push            # {approved?, force?}
POST /api/v1/code/pr                         # {task_id, title, summary?, open?}
```

## Commit safety (in order)

1. Inspect diff. 2. Run validation. 3. Run secret scan. 4. Check changed
files. 5. Verify branch (protected branches blocked). 6. Generate summary.
7. Apply commit policy. Unrelated user changes are never committed.
Commits record `task_id, agent_id, workspace_id, repository_id,
base_revision, new_revision, changed_files, validation_status` + audit log.

## Push policy & branch protection

Before push: inspect changes → secret scan → credential check → branch
policy → repository policy → approval requirement. Suspicious secrets ⇒
`BLOCKED` or `WAITING_FOR_APPROVAL` per policy. Remote branch protection
(required reviews/checks, signed commits) is respected and reported — never
circumvented. Force push is `CRITICAL` and denied by default.

## PR drafts

`PullRequestDraft`: `title, summary, motivation, changes, tests, risks,
screenshots, reviewers`. `open: true` opens the PR on the forge; the agent
**never merges** unless explicitly permitted by policy.
