# Dependencies

## Declaration

```json
{
  "dependencies": [
    { "type": "skill", "package": "web-research", "version": "^1.2.0" },
    { "type": "connector", "package": "github", "version": "^2.0.0" },
    { "type": "tool", "package": "browser-search", "version": "^1.4.0", "optional": true }
  ]
}
```

Supported: exact versions, `^`/`~` ranges, `>=`/`<=`/`>`/`<`, wildcards,
unions (`||`), `optional` and `peer` flags. Unknown future types are kept
and flagged for review instead of breaking.

## Resolution

Depth-first against a live registry snapshot (published package/skill/
preset/connector versions). The resolver reports:

- `MISSING_DEPENDENCY` / `UNSATISFIABLE_CONSTRAINT`
- `DEPENDENCY_CONFLICT` (two dependents pin disjoint ranges)
- `CIRCULAR_DEPENDENCY` (full path included)
- `POLICY_DENIED` (organization policy forbids the dependency — never auto-installed)
- `REVOKED_DEPENDENCY` (revoked versions never install)

Tool/model/memory/MCP misses are downgraded to install-preview warnings and
surfaced as `required_tools` / `required_models` instead of hard failures —
they are runtime requirements, not versioned packages.

## Install order

Dependencies install before dependents (topological order from the resource
graph). Requirement conflicts (same key, different values across deps) are
reported by `detect_requirement_conflicts`.
