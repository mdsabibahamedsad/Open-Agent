# Agent Handoff

## Protocol

Handoff is the primary responsibility-transfer mechanism
(`handoff_packages`, never overwriting previous attempts):

```
PREPARE → VALIDATE → TRANSFER → TARGET ACCEPTS → EXECUTES → SOURCE RELEASES → COMPLETE
```

The source task is not marked complete before acceptance. Modes:
`full | partial | review | escalation | specialist | failure`.

## Package

Source/target agent, task, objective, completed + pending work, decisions,
assumptions, constraints, artifacts (references, never binary blobs),
references, warnings, known failures, acceptance criteria, next action.

## Context policy

Rules: `public | task_only | team_only | authorized_shared | private |
redacted`. Transfer inspects classification, checks permissions, removes
secrets, drops unauthorized private context, enforces size limits, and writes
a `ContextManifest` (included/excluded/redacted items, source, target,
policy) — fully auditable.

## Secrets and artifacts

API keys, passwords, session tokens, credentials, encryption keys, and raw
cookies never transfer. Agents needing credentials request them through
credential/tool authorization. Large data moves by reference (50MB budget).

## Acceptance criteria and review

Delegated work carries verifiable criteria (`output_contains`,
`field_present`, or explicit reviewer approval — never "agent says done").
Reviews yield `approved | revision_required | rejected | escalate` with
criteria results, issues, required changes, and evidence. Revision loops are
capped (`max_revisions`, default 3); the `QualityGate` defaults to
pass/revision/fail and is MP20-extensible via
`ReviewProvider`/`QualityGate`/`EvaluationHook`.
