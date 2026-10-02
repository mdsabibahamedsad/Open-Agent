import { describe, expect, it } from "vitest";
import tool, { evaluateExpression } from "../src/index.js";

describe("calculator", () => {
  it("evaluates 2*(3+4)", () => expect(evaluateExpression("2*(3+4)")).toBe(14));
  it("handles precedence and unary minus", () => expect(evaluateExpression("-2+3*4")).toBe(10));
  it("rejects injection", () => expect(() => evaluateExpression("process.exit()")).toThrow());
  it("rejects division by zero", () => expect(() => evaluateExpression("1/0")).toThrow());
  it("runs via the tool handler", async () => {
    expect(await (tool as any).run({}, { expression: "1+2*3" })).toEqual({ result: 7 });
  });
});
