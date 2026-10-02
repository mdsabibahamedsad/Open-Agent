import { describe, expect, it } from "vitest";
import agent from "../src/index.js";

describe("hello-agent", () => {
  it("greets by name", async () => {
    const ctx = { model: { complete: async (p: string) => ({ text: `mock:${p}` }) } };
    const out: any = await (agent as any).run(ctx, { name: "Ada" });
    expect(out.greeting).toBe("Hello, Ada!");
  });
});
