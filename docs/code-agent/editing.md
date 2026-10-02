# Editing — Patch-First Changes

## Principle

Prefer patches over blind file replacement. Every modification produces a
structured change record (`code_patches`: `PROPOSED → VALIDATED → APPLIED /
REJECTED`).

```bash
POST /api/v1/code/tasks/{id}/patch   # {diff, approved?}
GET  /api/v1/code/tasks/{id}/diff
```

```diff
--- a/src/auth.py
+++ b/src/auth.py
@@
- old implementation
+ new implementation
```

## Validation before apply

1. File exists inside the workspace (no traversal).
2. Expected base content matches (stale-context detection).
3. Patch applies cleanly (no conflicts, well-formed).
4. Path stays inside workspace; file-size limits hold.
5. Patch metadata recorded (task, agent, base revision).

Rejects: wrong file/line, stale context, conflicting modifications,
malformed patches, `../../` escapes.

## Multi-file change sets

Coordinate `source + tests + config + docs + types + schemas + migrations`
as one atomic task-level change set where possible. The agent inspects its
own diff before declaring completion (self-review loop):

```text
Edit → Diff → Review → Fix → Test → Review again
```

checking correctness, regressions, security, style, typing, coverage,
unnecessary changes, API compatibility.

## Tool surface

`code.file.list · code.file.read · code.search · code.symbol.find ·
code.reference.find · code.diff · code.patch.apply` — all through Tool
Runtime with RBAC, policy, risk, credential, audit, rate-limit, and
observability gates. Risk: reads are `LOW`; edits are `MEDIUM`.
