import { defineConnector } from "@openagent/extension-sdk";
import { createHmac, timingSafeEqual } from "node:crypto";

function verifyTelegram(secret: string, body: Buffer, token: string): boolean {
  // Telegram webhook secret_token check (constant-time).
  const a = Buffer.from(token);
  const b = Buffer.from(secret);
  return a.length === b.length && timingSafeEqual(a, b);
}

export { verifyTelegram };

export default defineConnector({
  id: "telegram-custom",
  displayName: "Telegram (custom)",
  auth: { type: "custom_header", header: "X-Telegram-Bot-Api-Secret-Token" },
  capabilities: [{ id: "telegram.messages.send", risk: "MEDIUM" }],
  actions: [
    {
      id: "telegram-custom.send",
      inputSchema: {
        type: "object",
        properties: { chat_id: { type: "string" }, text: { type: "string", maxLength: 4000 } },
        required: ["chat_id", "text"],
      },
      requiredCapabilities: ["telegram.messages.send"],
      timeoutSeconds: 20,
      async run(ctx, args: { chat_id: string; text: string }) {
        const token = await ctx.secrets.resolve("TELEGRAM_BOT_TOKEN");
        return ctx.http.post(`https://api.telegram.org/bot${token}/sendMessage`, {
          chat_id: args.chat_id, text: args.text,
        });
      },
    },
  ],
  triggers: [{ id: "telegram-custom.update", kind: "webhook", eventTypes: ["message"] }],
  async onWebhook(ctx, req: { body: Buffer; secretToken: string }) {
    const expected = await ctx.secrets.resolve("TELEGRAM_WEBHOOK_SECRET");
    if (!verifyTelegram(expected, req.body, req.secretToken)) throw new Error("bad webhook signature");
    return { event: "connector.event.received.v1", payload: JSON.parse(req.body.toString()) };
  },
});
