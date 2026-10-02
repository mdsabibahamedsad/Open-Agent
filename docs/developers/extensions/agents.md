# Building Agents (`type: agent`)

## 1. Define

```bash
openagent init --type agent --name my-org/hello-agent --lang ts
```

```typescript
// src/index.ts
import { defineAgent } from "@openagent/extension-sdk";

export default defineAgent({
  name: "hello-agent",
  displayName: "Hello Agent",
  description: "Greets the user and summarizes input.",
  model: { default: "gpt-4o-mini", allowlist: ["gpt-4o-mini", "claude-3-5-sonnet"] },
  systemPrompt: "You are a concise assistant. Greet the user, then summarize their request in one line.",
  tools: ["calculator.evaluate"],
  memory: { scope: "agent:hello-agent", read: true, write: true },
  guardrails: { requireApprovalFor: ["browser:use", "network:restricted"] },
  async onRun(ctx, input: { name?: string }) {
    const name = input.name?.trim() || "world";
    const summary = await ctx.model.complete(`Summarize this request: hello ${name}`);
    return { greeting: `Hello, ${name}!`, summary: summary.text };
  },
});
```

Python equivalent (`openagent_extension` package):

```python
from openagent_extension import define_agent

agent = define_agent(
    name="hello-agent",
    description="Greets the user and summarizes input.",
    model={"default": "gpt-4o-mini"},
    system_prompt="You are a concise assistant.",
    tools=["calculator.evaluate"],
)

@agent.on_run
def run(ctx, input: dict) -> dict:
    name = (input.get("name") or "world").strip()
    summary = ctx.model.complete(f"Summarize this request: hello {name}")
    return {"greeting": f"Hello, {name}!", "summary": summary["text"]}
```

## 2. Manifest

```yaml
manifest_version: "1"
name: my-org/hello-agent
version: 1.0.0
display_name: Hello Agent
description: Greets the user and summarizes input.
author: {name: Your Name, email: you@example.com}
license: MIT
repository: https://github.com/my-org/hello-agent
type: agent
runtime: {language: typescript, entrypoint: src/index.ts}
permissions: [tool:execute, model:invoke, memory:read, memory:write]
capabilities: [greet, summarize]
events: [agent.run.completed.v1, agent.run.failed.v1]
config_schema:
  type: object
  properties:
    greeting: {type: string, default: Hello}
compatibility: {openagent: ">=1.0.0 <2.0.0", sdk: ">=1.0.0 <2.0.0",
  extension_api: "1.x", api_version: v1}
security: {trust_level: UNTRUSTED, network_policy: none}
```

Needs `model:invoke` to call the Model Router, `memory:read/write` for scoped
memory. No `network:*` — agents egress only through tools/connectors.

## 3. Test

```bash
openagent dev --mock        # local run with MockLLM/MockToolRuntime (seeded)
openagent test              # contract: manifest valid, onRun returns schema, compat OK
```

```typescript
// test/agent.test.ts
import { describe, expect, it } from "vitest";
import agent from "../src/index.js";

describe("hello-agent", () => {
  it("greets by name", async () => {
    const ctx = { model: { complete: async (p: string) => ({ text: `[mock:${p.slice(0, 8)}]` }) } };
    const out: any = await (agent as any).run(ctx, { name: "Ada" });
    expect(out.greeting).toBe("Hello, Ada!");
  });
});
```

## 4. Publish

```bash
openagent validate && openagent build && openagent package
openagent publish   # then deploy: openagent deploy --env staging
```

See also: [`../publishing.md`](../publishing.md), `examples/hello-agent`,
`examples/research-agent`, `examples/multi-agent-workforce`.
