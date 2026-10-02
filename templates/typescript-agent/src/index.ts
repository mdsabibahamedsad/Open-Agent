import { defineAgent } from "@openagent/extension-sdk";

export default defineAgent({
  name: "hello",
  description: "Hello-world agent. Replace with your logic.",
  model: { default: "gpt-4o-mini" },
  systemPrompt: "Be concise.",
  async onRun(ctx, input: Record<string, unknown>) {
    return { ok: true, input };
  },
});
