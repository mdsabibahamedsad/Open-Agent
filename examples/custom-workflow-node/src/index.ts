import { defineWorkflowNode } from "@openagent/extension-sdk";

export default defineWorkflowNode({
  kind: "text.uppercase",
  displayName: "Uppercase",
  description: "Uppercase a string field (pure transform).",
  inputSchema: { type: "object", properties: { text: { type: "string" } }, required: ["text"] },
  outputSchema: { type: "object", properties: { text: { type: "string" } }, required: ["text"] },
  validate(inputs: { text?: unknown }) {
    if (typeof inputs.text !== "string") return ["'text' must be a string"];
    if (inputs.text.length > 10000) return ["'text' exceeds 10000 chars"];
    return [];
  },
  async execute(_ctx, inputs: { text: string }) {
    return { text: inputs.text.toUpperCase() };
  },
});
