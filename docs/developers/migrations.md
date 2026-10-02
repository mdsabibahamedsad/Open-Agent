# Migrations

## SDK 0.x → 1.x (extension API 1.x)

`openagent migrate --from 0.x` rewrites scaffolds; the table below covers the
breaking changes by hand.

### Deprecated API table

| 0.x (removed/changed) | 1.x replacement | Notes |
|------------------------|-----------------|-------|
| `client.agents.create(name, opts)` positional | `client.agents.create({name, …})` | announced in `DEPRECATIONS`; old form rejected |
| `client.runs.*` ad-hoc run helpers | `client.workflows.execute()` / `client.orchestrations.*` | runs are workflow/orchestration executions |
| Unversioned `/api/…` paths | `/api/v1/…` | no unversioned endpoints in 1.x |
| `manifest.json` connector manifests | `openagent.yaml` (`manifest_version: "1"`) | single canonical manifest for all types |
| `type: integration` (new code) | `type: connector` | `integration` kept as alias for old rows only |
| `permissions: ["*"]` / omitted allowlists | explicit catalog permissions + `allowed_hosts` | validation fails closed |
| Inline secrets in config/manifest | `secrets:` reference names | publish gate blocks values |
| Sync webhook handlers without verification | `verify_webhook()` (v1 header, 300s window) | see `api.md` |
| `extension_api: "0.x"` | `extension_api: "1.x"` | `check_compatibility` rejects others |

### Steps

1. `openagent migrate --from 0.x --dir .` (rewrites manifest + imports).
2. Rename `manifest.json` → `openagent.yaml` with `manifest_version: "1"`;
   move connector `id` → `name`, `auth.type` stays under manifest `secrets:` +
   `required_services:`.
3. Replace positional SDK calls with object args; add `Idempotency-Key` to
   mutating calls.
4. Declare explicit `permissions:` (start from the scaffold default
   `tool:execute` + `filesystem:workspace` and add only what scans/tests
   prove you need); add `network.allowed_hosts` if you egress.
5. Move secrets to refs; delete embedded values; run `openagent validate`
   until clean, then `openagent test --seed stable`.
6. Re-package, re-sign with a new `key_id`, publish as a `MAJOR`-or-`MINOR`
   bump with migration notes in the version changelog.

### Before / after

```yaml
# 0.x manifest.json (connector)
{"id": "myconn", "version": "0.9.0", "auth": {"type": "api_key", "key": "sk-live-..."},
 "permissions": ["*"]}
```

```yaml
# 1.x openagent.yaml
manifest_version: "1"
name: my-org/myconn
version: 1.0.0
type: connector
permissions: [network:outbound, connector:use]
network: {allowed_hosts: [api.example.com]}
secrets: [MYCONN_API_KEY]
compatibility: {openagent: ">=1.0.0 <2.0.0", sdk: ">=1.0.0 <2.0.0",
  extension_api: "1.x", api_version: v1}
security: {trust_level: COMMUNITY, network_policy: allowlisted,
  allowed_hosts: [api.example.com]}
```

```typescript
// 0.x
await client.agents.create("researcher", { model: "gpt-4o-mini" });
// 1.x
await client.agents.create({ name: "researcher", model: "gpt-4o-mini" });
```
