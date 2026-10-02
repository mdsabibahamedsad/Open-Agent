import { describe, expect, it } from "vitest";
import connector, { verifyTelegram } from "../src/index.js";

describe("telegram-connector", () => {
  it("verifies webhook secret tokens", () => {
    expect(verifyTelegram("s3cret", Buffer.from("{}"), "s3cret")).toBe(true);
    expect(verifyTelegram("s3cret", Buffer.from("{}"), "wrong")).toBe(false);
  });
  it("sends via Bot API", async () => {
    const ctx: any = {
      secrets: { resolve: async () => "TOKEN" },
      http: { post: async (url: string) => ({ ok: true, url }) },
    };
    const action = (connector as any).actions[0];
    const out = await action.run(ctx, { chat_id: "1", text: "hi" });
    expect(out.url).toContain("api.telegram.org");
  });
});
