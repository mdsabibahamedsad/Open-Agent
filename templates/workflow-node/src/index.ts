import { defineWorkflowNode } from "@openagent/extension-sdk";

export default defineWorkflowNode({
  kind: "hello.passthrough",
  displayName: "Hello passthrough",
  description: "Echo inputs back (replace with your transform).",
  inputSchema: { type: "object", properties: { text: { type: "string" } }, required: ["text"] },
  outputSchema: { type: "object", properties: { text: { type: "string" } }, required: ["text"] },
  async execute(_ctx, inputs: { text: string }) {
    return { text: inputs.text };
  },
});
