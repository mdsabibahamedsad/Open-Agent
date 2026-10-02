import { defineAgent } from "@openagent/extension-sdk";

export default defineAgent({
  name: "hello-agent",
  description: "Greets the user.",
  model: { default: "gpt-4o-mini" },
  systemPrompt: "You are a friendly greeter. Keep replies to one sentence.",
  async onRun(ctx, input: { name?: string }) {
    const name = input.name?.trim() || "world";
    const completion = await ctx.model.complete(`Say hello to ${name}`);
    return { greeting: `Hello, ${name}!`, note: completion.text };
  },
});
