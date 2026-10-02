import { describe, expect, it } from "vitest";
import agent from "../src/index.js";

describe("price-watch", () => {
  it("extracts price on allowlisted host", async () => {
    const ctx: any = {
      browser: { goto: async (u: string) => ({ title: "Widget" }), extract: async () => ({ text: "$9.99" }) },
    };
    expect(await (agent as any).run(ctx, { url: "https://shop.example.com/p/1" }))
      .toEqual({ title: "Widget", price: "$9.99" });
  });
  it("refuses off-allowlist URLs", async () => {
    await expect((agent as any).run({ browser: {} }, { url: "https://evil.example/x" })).rejects.toThrow();
  });
});
