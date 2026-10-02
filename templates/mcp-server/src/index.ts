import { defineMCPServer } from "@openagent/extension-sdk";

export default defineMCPServer({
  name: "hello-mcp",
  description: "Hello-world MCP server.",
  tools: [
    {
      name: "hello.ping",
      description: "Return pong.",
      inputSchema: { type: "object", properties: {}, required: [] },
      async handler() {
        return { pong: true };
      },
    },
  ],
  resources: [],
  prompts: [],
});
