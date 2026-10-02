# Browser Research Mode

Research is an evidence-first loop, not free browsing:

```text
Search → Open result → Inspect source → Extract → Follow relevant links
  → Cross-check → Store evidence (URL + timestamp) → Structured result
```

- Results preserve source URLs and access timestamps.
- Page content is untrusted: findings are labeled, injection-scanned, and
  never treated as instructions.
- `allowed_domains` scopes every run; cross-checking across ≥2 sources is
  recommended before facts enter memory or answers.
- TypeScript: `buildResearchPlan` / `compileResearchEvidence`
  (`@openagent/browser` `research/service`).
