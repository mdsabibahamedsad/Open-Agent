# Building Workflow Nodes (`type: workflow-node`)

Custom nodes plug into the workflow engine (validator + executors + frontend
catalog). Nodes are pure transforms: `(inputs, ctx) → outputs`.

## 1. Define

```typescript
// src/index.ts
import { defineWorkflowNode } from "@openagent/extension-sdk";

export default defineWorkflowNode({
  kind: "text.uppercase",
  displayName: "Uppercase",
  description: "Uppercase a string field (pure transform).",
  inputSchema: {
    type: "object",
    properties: { text: { type: "string" } },
    required: ["text"],
  },
  outputSchema: {
    type: "object",
    properties: { text: { type: "string" } },
    required: ["text"],
  },
  async execute(_ctx, inputs: { text: string }) {
    return { text: inputs.text.toUpperCase() };
  },
  // Optional lifecycle hooks used by the engine:
  // validate(inputs) -> string[] (problems), compensate(outputs) for rollback.
});
```

Built-in node kinds you can compose instead of re-implementing: `browser_agent`,
`code_agent`, `connector_action`, `verify`/`evaluate`/`assert`/`quality_gate`/
`retry`/`correct`, `approval`, `git_commit`, `create_pr`.

## 2. Manifest

```yaml
manifest_version: "1"
name: my-org/text-nodes
version: 1.0.0
display_name: Text nodes
description: Uppercase transform node.
author: {name: Your Name, email: you@example.com}
license: MIT
type: workflow-node
runtime: {language: typescript, entrypoint: src/index.ts}
permissions: [workflow:execute, filesystem:workspace]
capabilities: [text.uppercase]
events: [workflow.execution.completed.v1, workflow.execution.failed.v1]
compatibility: {openagent: ">=1.0.0 <2.0.0", sdk: ">=1.0.0 <2.0.0",
  extension_api: "1.x", api_version: v1}
security: {trust_level: UNTRUSTED, network_policy: none}
```

## 3. Test

```bash
openagent test   # contract: schemas round-trip, execute deterministic, no side effects
```

```typescript
import { describe, expect, it } from "vitest";
import node from "../src/index.js";

describe("text.uppercase", () => {
  it("uppercases", async () => {
    expect(await (node as any).execute({}, { text: "hello" })).toEqual({ text: "HELLO" });
  });
});
```

## 4. Publish

```bash
openagent validate && openagent package && openagent publish
```

Nodes needing models/tools/sandbox declare `model:invoke` / `tool:execute` /
`sandbox:execute` respectively. Example: `examples/custom-workflow-node`.
