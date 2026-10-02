import { defineTool } from "@openagent/extension-sdk";

export default defineTool({
  name: "hello.run",
  description: "Hello-world tool.",
  inputSchema: { type: "object", properties: { name: { type: "string" } }, required: ["name"] },
  outputSchema: { type: "object", properties: { greeting: { type: "string" } }, required: ["greeting"] },
  async handler(_ctx, args: { name: string }) {
    return { greeting: `Hello, ${args.name}!` };
  },
});
