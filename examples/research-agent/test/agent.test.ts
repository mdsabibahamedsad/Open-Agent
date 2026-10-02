import { describe, expect, it } from "vitest";
import agent from "../src/index.js";

const ctx: any = {
  model: { complete: async () => ({ text: "mock brief" }) },
  tools: { invoke: async () => [{ title: "t", url: "https://x.example" }] },
  memory: { read: async () => { throw new Error("miss"); }, write: async () => ({}) },
};

describe("research-agent", () => {
  it("returns a brief", async () => {
    const out: any = await (agent as any).run(ctx, { topic: "SSRF" });
    expect(out.brief).toBe("mock brief");
    expect(out.cached).toBe(false);
  });
});
