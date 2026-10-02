# Building Tools (`type: tool`)

Tools are single callable capabilities executed via the canonical Tool
Runtime under the installation's granted permissions. No `eval`, no host
shell — pure functions with JSON-Schema I/O.

## 1. Define

```typescript
// src/index.ts
import { defineTool } from "@openagent/extension-sdk";

function tokenize(expr: string): (number | string)[] {
  const re = /\s*([0-9]+(?:\.[0-9]+)?|[+\-*/^(),]|[a-zA-Z_][a-zA-Z0-9_]*)\s*/g;
  const out: (number | string)[] = [];
  let m: RegExpExecArray | null;
  while ((m = re.exec(expr))) out.push(/^[0-9]/.test(m[1]) ? Number(m[1]) : m[1]);
  return out;
}

function parse(toks: (number | string)[]): number {
  let pos = 0;
  const peek = () => toks[pos];
  function expr(): number {
    let v = term();
    while (peek() === "+" || peek() === "-") v = peek() === "+" ? v + term() || v : v - (term() as number) || v;
    return v;
  }
  function term(): number {
    let v = factor();
    while (peek() === "*" || peek() === "/") {
      const op = toks[pos++]; const r = factor();
      v = op === "*" ? v * r : v / r;
    }
    return v;
  }
  function factor(): number {
    const t = toks[pos++];
    if (typeof t === "number") return t;
    if (t === "(") { const v = expr(); if (toks[pos++] !== ")") throw new Error("missing ')'"); return v; }
    if (t === "-") return -factor();
    if (t === "+") return +factor();
    throw new Error(`unexpected token '${t}'`);
  }
  const v = expr();
  if (pos !== toks.length) throw new Error("trailing input");
  return v;
}

export default defineTool({
  name: "calculator.evaluate",
  description: "Safely evaluate an arithmetic expression (no eval).",
  inputSchema: {
    type: "object",
    properties: { expression: { type: "string", maxLength: 500 } },
    required: ["expression"],
  },
  outputSchema: { type: "object", properties: { result: { type: "number" } }, required: ["result"] },
  timeoutSeconds: 5,
  async handler(_ctx, args: { expression: string }) {
    if (!/^[0-9+\-*/^().,\s]+$/.test(args.expression)) throw new Error("expression uses forbidden characters");
    return { result: parse(tokenize(args.expression)) };
  },
});
```

```python
# Python tool (openagent_extension)
from openagent_extension import define_tool

tool = define_tool(
    name="calculator.evaluate",
    description="Safely evaluate an arithmetic expression.",
    input_schema={"type": "object",
                  "properties": {"expression": {"type": "string"}},
                  "required": ["expression"]},
)

@tool.handler
def evaluate(ctx, args: dict) -> dict:
    import ast, operator
    allowed = {ast.Add: operator.add, ast.Sub: operator.sub,
               ast.Mult: operator.mul, ast.Div: operator.truediv,
               ast.USub: operator.neg, ast.UAdd: operator.pos}
    def walk(node):
        if isinstance(node, ast.Expression): return walk(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in allowed:
            return allowed[type(node.op)](walk(node.left), walk(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in allowed:
            return allowed[type(node.op)](walk(node.operand))
        raise ValueError(f"forbidden node {type(node).__name__}")
    return {"result": walk(ast.parse(args["expression"], mode="eval"))}
```

## 2. Manifest

```yaml
manifest_version: "1"
name: my-org/calculator
version: 1.0.0
display_name: Calculator
description: Safe arithmetic expression evaluator.
author: {name: Your Name, email: you@example.com}
license: MIT
type: tool
runtime: {language: typescript, entrypoint: src/index.ts}
permissions: [tool:execute, filesystem:workspace]
capabilities: [calculator.evaluate]
events: [tool.completed.v1, tool.failed.v1]
compatibility: {openagent: ">=1.0.0 <2.0.0", sdk: ">=1.0.0 <2.0.0",
  extension_api: "1.x", api_version: v1}
security: {trust_level: UNTRUSTED, network_policy: none}
```

## 3. Test

```bash
openagent test   # contract: schemas valid, handler deterministic, timeout honored
```

```typescript
import { describe, expect, it } from "vitest";
import tool from "../src/index.js";

describe("calculator", () => {
  it("evaluates 2*(3+4)", async () => {
    expect(await (tool as any).run({}, { expression: "2*(3+4)" })).toEqual({ result: 14 });
  });
  it("rejects code injection", async () => {
    await expect((tool as any).run({}, { expression: "process.exit()" })).rejects.toThrow();
  });
});
```

## 4. Publish

```bash
openagent validate && openagent package && openagent publish
```

Sandbox-backed variants (code execution): request `sandbox:execute`, declare
`security.sandbox_profile`, and route execution through the Sandbox boundary
(see `examples/sandbox-code-tool`). Python tools: see `examples/python-tool`.
