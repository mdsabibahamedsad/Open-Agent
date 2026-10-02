# Building Connectors (`type: connector`)

Connectors integrate third-party APIs through one engine-owned pipeline:
manifest validation → credential crypto → SSRF-guarded HTTP → OAuth2/PKCE →
webhook verify/normalize → polling cursors → rate limits → mapping engine →
normalized resources. See `docs/integrations/*` for the runtime side.

## 1. Define

```typescript
// src/index.ts
import { defineConnector } from "@openagent/extension-sdk";

export default defineConnector({
  id: "github-custom",
  displayName: "GitHub (custom)",
  auth: { type: "oauth2", scopes: ["repo:read"], pkce: true },
  capabilities: [{ id: "github-custom.repos.read", risk: "LOW" }],
  actions: [
    {
      id: "github-custom.list_repos",
      inputSchema: {
        type: "object",
        properties: { org: { type: "string" } },
        required: ["org"],
      },
      requiredCapabilities: ["github-custom.repos.read"],
      idempotent: true,
      timeoutSeconds: 20,
      async run(ctx, args: { org: string }) {
        // ctx.http is the shared guarded client (retries, breaker, SSRF guard).
        const res = await ctx.http.get(`https://api.github.com/orgs/${args.org}/repos`, {
          credentialRef: ctx.credentials.github,
        });
        return { repos: (res as any[]).map((r) => ({ name: r.name, stars: r.stargazers_count })) };
      },
    },
  ],
  triggers: [{ id: "github-custom.push", kind: "webhook", eventTypes: ["push"] }],
});
```

## 2. Manifest

```yaml
manifest_version: "1"
name: my-org/github-custom
version: 1.0.0
display_name: GitHub custom
description: List org repos via the guarded connector pipeline.
author: {name: Your Name, email: you@example.com}
license: MIT
type: connector
runtime: {language: typescript, entrypoint: src/index.ts}
permissions: [network:outbound, connector:use, secret:access]
network: {allowed_hosts: [api.github.com]}
secrets: [GITHUB_CLIENT_SECRET]
required_services: [credential-store, http-egress]
capabilities: [github-custom.repos.read]
events: [connector.event.received.v1]
compatibility: {openagent: ">=1.0.0 <2.0.0", sdk: ">=1.0.0 <2.0.0",
  extension_api: "1.x", api_version: v1}
security:
  trust_level: COMMUNITY
  network_policy: allowlisted
  allowed_hosts: [api.github.com]
  risk_notes: Read-only repo listing; OAuth scopes limited to repo:read.
```

Rules that bite: `network:outbound` without `allowed_hosts` fails
validation; `secret:access` needs an approval record at install; keep
`scopes` ≤ 64 and namespaced (`<id>.*`).

OAuth notes: use the OAuth manager (PKCE); never store or log tokens —
reference `credential_ref` handles. Webhook triggers must verify signatures
before normalizing; declare `webhook:receive` when serving inbound hooks
(see `examples/telegram-connector`).

## 3. Test

```bash
openagent test   # contract: capabilities namespaced, actions reference known caps,
                # schemas are object schemas, offline MockConnector passes
```

## 4. Publish

```bash
openagent validate && openagent package && openagent publish
```

Official-provider reference: `apps/api/src/openagent/connectors/providers/`
(11 providers). Generator: `scripts/connector-new.py`. Examples:
`examples/github-connector`, `examples/telegram-connector`.
