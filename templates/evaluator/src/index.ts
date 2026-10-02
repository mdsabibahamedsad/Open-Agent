import { defineEvaluator } from "@openagent/extension-sdk";

export default defineEvaluator({
  name: "hello-check",
  description: "Hello-world evaluator.",
  rubric: { id: "hello@1", criteria: ["output is non-empty"] },
  async evaluate(_ctx, target: { output: unknown }) {
    const passed = JSON.stringify(target.output ?? "").length > 2;
    return { score: passed ? 1 : 0, passed, evidence: [{ check: "non-empty" }] };
  },
});
