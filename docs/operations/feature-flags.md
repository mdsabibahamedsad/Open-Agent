# Feature flags

Scopes PLATFORM → ORGANIZATION → PROJECT → ENVIRONMENT → USER
(narrowest wins). Strategies: boolean, percentage (deterministic
`hash(feature + subject)` buckets — stable per subject, no per-request
randomness), allowlist, denylist. **Flags cannot bypass security**:
`security.*` keys evaluate security-guarded (advisory only).
Kill switches (`connector`, `model_provider`, `tool`, `workflow_node`,
`browser`, `code_execution`, `region`, `worker_pool`) are audited,
permission-gated, labeled, reversible. Config changes support preview
and dry-run; important config is versioned with rollback references.
