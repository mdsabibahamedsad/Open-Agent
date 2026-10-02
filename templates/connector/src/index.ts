import { defineConnector } from "@openagent/extension-sdk";

export default defineConnector({
  id: "hello-api",
  displayName: "Hello API",
  auth: { type: "api_key" },
  capabilities: [{ id: "hello-api.items.read", risk: "LOW" }],
  actions: [
    {
      id: "hello-api.list_items",
      inputSchema: { type: "object", properties: {}, required: [] },
      requiredCapabilities: ["hello-api.items.read"],
      async run(ctx) {
        return ctx.http.get("https://api.example.com/items", {});
      },
    },
  ],
});
