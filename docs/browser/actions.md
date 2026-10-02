# Browser Actions

Normalized actions (`NAVIGATE`, `CLICK`, `TYPE`, `FILL`, `SELECT`, `SCROLL`,
`SCREENSHOT`, `EXTRACT`, `UPLOAD`, `DOWNLOAD`, tabs/history…) are exposed as
`browser.*` tools and executed via Tool Runtime only.

## Risk model

| Level | Examples |
|---|---|
| LOW | scroll, read, screenshot, extract, wait |
| MEDIUM | navigate, click, fill, download |
| HIGH | upload, evaluate, set_input_files |
| CRITICAL | authenticate (credential changes) |

Actions at/above the task `maxRiskLevel`, or listed in
`requireApprovalFor`, return `{requiresApproval: true}` instead of executing.
Retry is only automatic for retry-safe reads; mutating actions are queued
`PENDING` for the browser worker and are **never auto-replayed after a crash**.

## Element targeting

Prefer, in order: `testId` → `role`+`name` → `label` → `placeholder` →
`text` → CSS → XPath → coordinates (last resort). Element IDs are
page-scoped and invalidated on DOM mutation.

## Observations

Strategies `minimal | standard | detailed | visual` map to token budgets
(~1.5k/6k/15k/6k chars) with dedup, pruning and truncation
(`compress_observation`). Untrusted page text is wrapped as
`[UNTRUSTED_WEB_CONTENT]` when injection signals are detected.
