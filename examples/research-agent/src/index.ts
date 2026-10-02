import { defineAgent } from "@openagent/extension-sdk";

export default defineAgent({
  name: "research-agent",
  description: "Researches a topic using a search tool.",
  model: { default: "gpt-4o-mini" },
  systemPrompt: "Research thoroughly. Cite sources. Flag uncertainty.",
  tools: ["web.search"],
  memory: { scope: "agent:research-agent", read: true, write: true },
  async onRun(ctx, input: { topic: string; max_sources?: number }) {
    const prior = await ctx.memory.read(`topic:${input.topic}`).catch(() => null);
    const results = await ctx.tools.invoke("web.search", {
      q: input.topic, limit: input.max_sources ?? 5,
    });
    const brief = await ctx.model.complete(
      `Summarize these findings on "${input.topic}": ${JSON.stringify(results)}`,
    );
    await ctx.memory.write(`topic:${input.topic}`, { brief: brief.text });
    return { topic: input.topic, brief: brief.text, cached: Boolean(prior) };
  },
});
