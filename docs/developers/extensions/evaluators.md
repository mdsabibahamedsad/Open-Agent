# Building Evaluators (`type: evaluator`)

Evaluators score runs and artifacts against versioned rubrics. Evidence is
tamper-resistant; scoring uses deterministic verifiers + Model-Router judges.
There are no force-success APIs.

## 1. Define

```typescript
// src/index.ts
import { defineEvaluator } from "@openagent/extension-sdk";

const BANNED = ["password", "secret", "BEGIN PRIVATE KEY"];

export default defineEvaluator({
  name: "no-secret-leak",
  displayName: "No Secret Leak",
  description: "Rule-based check: outputs must not contain credential material.",
  rubric: { id: "secret-hygiene@1", criteria: ["no credentials in output"] },
  async evaluate(_ctx, target: { output: unknown }) {
    const text = JSON.stringify(target.output ?? "");
    const hits = BANNED.filter((b) => text.includes(b));
    return {
      score: hits.length === 0 ? 1 : 0,
      passed: hits.length === 0,
      evidence: [{ check: "secret-patterns", hits }],
    };
  },
});
```

## 2. Manifest

```yaml
manifest_version: "1"
name: my-org/no-secret-leak
version: 1.0.0
display_name: No Secret Leak
description: Rule-based evaluator blocking credential leakage in outputs.
author: {name: Your Name, email: you@example.com}
license: MIT
type: evaluator
runtime: {language: typescript, entrypoint: src/index.ts}
permissions: [evaluation:run]
capabilities: [eval.no-secret-leak]
events: [evaluation.completed.v1]
compatibility: {openagent: ">=1.0.0 <2.0.0", sdk: ">=1.0.0 <2.0.0",
  extension_api: "1.x", api_version: v1}
security: {trust_level: COMMUNITY, network_policy: none}
```

Evaluators observe outputs only — they get `evaluation:run` and no memory,
network, or secret permissions. LLM-judge evaluators additionally declare
`model:invoke` and must pin the judge model + rubric version.

## 3. Test

```bash
openagent test   # contract: score in [0,1], evidence attached, deterministic per seed
```

```typescript
import { describe, expect, it } from "vitest";
import evaluator from "../src/index.js";

describe("no-secret-leak", () => {
  it("passes clean output", async () => {
    expect(await (evaluator as any).evaluate({}, { output: "hello world" }))
      .toMatchObject({ score: 1, passed: true });
  });
  it("fails leaked key material", async () => {
    expect(await (evaluator as any).evaluate({}, { output: "BEGIN PRIVATE KEY" }))
      .toMatchObject({ score: 0, passed: false });
  });
});
```

## 4. Publish

```bash
openagent validate && openagent package && openagent publish
```

Wire into quality gates (`quality-gates`, workflow `quality_gate` node, agent
verify hooks). Example: `examples/evaluator`.
