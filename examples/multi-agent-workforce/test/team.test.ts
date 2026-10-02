import { describe, expect, it } from "vitest";
import { triageAgent, resolverAgent } from "../src/index.js";

const ctx: any = { model: { complete: async (p: string) => ({ text: `mock:${p.slice(0, 10)}` }) } };

describe("support-team", () => {
  it("hands off with context", async () => {
    const t: any = await (triageAgent as any).run(ctx, { ticket: "500s" });
    expect(t.handoff.to).toBe("support-resolver");
    const r: any = await (resolverAgent as any).run(ctx, { ticket: "500s", verdict: t.handoff.context.verdict });
    expect(r.resolution).toContain("mock:");
  });
});
