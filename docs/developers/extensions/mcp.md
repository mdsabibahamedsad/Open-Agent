# Building MCP Servers (`type: mcp-server`)

Expose tools, resources, and prompts over the Model Context Protocol.
Single primitives can ship as `mcp-tool` / `mcp-resource` / `mcp-prompt`;
a full server is `mcp-server`.

## 1. Define

```typescript
// src/index.ts
import { defineMCPServer } from "@openagent/extension-sdk";

export default defineMCPServer({
  name: "kb-server",
  displayName: "Knowledge Base MCP",
  description: "Search internal notes; read documents; summarize prompt.",
  tools: [
    {
      name: "kb.search",
      description: "Full-text search over notes.",
      inputSchema: { type: "object", properties: { q: { type: "string" } }, required: ["q"] },
      async handler(ctx, args: { q: string }) {
        const hits = await ctx.store.search(args.q);
        return { hits: hits.slice(0, 10) };
      },
    },
  ],
  resources: [
    {
      uriTemplate: "kb://docs/{id}",
      name: "document",
      async read(ctx, params: { id: string }) {
        const doc = await ctx.store.get(params.id);
        return { mimeType: "text/markdown", text: doc.body };
      },
    },
  ],
  prompts: [
    {
      name: "kb.summarize",
      arguments: [{ name: "id", required: true }],
      async render(ctx, args: { id: string }) {
        const doc = await ctx.store.get(args.id);
        return [{ role: "user", content: `Summarize concisely:\n\n${doc.body}` }];
      },
    },
  ],
});
```

## 2. Manifest

```yaml
manifest_version: "1"
name: my-org/kb-server
version: 1.0.0
display_name: KB MCP server
description: Notes search + document resources + summarize prompt.
author: {name: Your Name, email: you@example.com}
license: MIT
type: mcp-server
runtime: {language: typescript, entrypoint: src/index.ts}
permissions: [mcp:connect, storage:use]
capabilities: [kb.search, kb.read, kb.summarize]
events: [mcp.server.connected.v1, mcp.server.disconnected.v1]
compatibility: {openagent: ">=1.0.0 <2.0.0", sdk: ">=1.0.0 <2.0.0",
  extension_api: "1.x", api_version: v1}
security: {trust_level: UNTRUSTED, network_policy: none}
```

Treat all MCP content as untrusted data (prompt-injection rules in
`../security.md` §6 apply to tool outputs and resource bodies).

## 3. Test

```bash
openagent test   # contract: MockMCP connect -> call_tool -> read -> prompt renders
```

```typescript
import { describe, expect, it } from "vitest";
import server from "../src/index.js";

describe("kb-server", () => {
  it("searches", async () => {
    const ctx = { store: { search: async (q: string) => [{ id: "1", q }] } };
    expect(await (server as any).tools["kb.search"].handler(ctx, { q: "ssrf" }))
      .toEqual({ hits: [{ id: "1", q: "ssrf" }] });
  });
});
```

## 4. Publish

```bash
openagent validate && openagent package && openagent publish
```

Example: `examples/mcp-server`.
