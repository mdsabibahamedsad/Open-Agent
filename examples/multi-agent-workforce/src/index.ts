import { defineAgent } from "@openagent/extension-sdk";

export const triageAgent = defineAgent({
  name: "support-triage",
  description: "Classify tickets and hand off with a context manifest.",
  model: { default: "gpt-4o-mini" },
  systemPrompt: "Classify SEV + topic. Always hand off with symptoms, sev, tried.",
  async onRun(ctx, input: { ticket: string }) {
    const c = await ctx.model.complete(`Classify: ${input.ticket}`);
    return { handoff: { to: "support-resolver", context: { ticket: input.ticket, verdict: c.text } } };
  },
});

export const resolverAgent = defineAgent({
  name: "support-resolver",
  description: "Resolve handed-off tickets.",
  model: { default: "gpt-4o-mini" },
  systemPrompt: "Resolve using the handoff context. Ask for approval on destructive steps.",
  async onRun(ctx, input: { ticket: string; verdict?: string }) {
    const c = await ctx.model.complete(`Resolve (${input.verdict}): ${input.ticket}`);
    return { resolution: c.text };
  },
});

export default { triageAgent, resolverAgent };
