# typescript-tool

Minimal but complete `tool` starter, synced with extension API 1.x.

```bash
openagent dev
openagent test
openagent validate && openagent build && openagent package
openagent publish && openagent deploy --env staging
```

- Manifest: `openagent.yaml` (field names match `ExtensionManifest` exactly)
- Source: `src/` hello-world against the extension-sdk builder API
- Tests: `test/` standard-harness sketch (seeded, offline)
