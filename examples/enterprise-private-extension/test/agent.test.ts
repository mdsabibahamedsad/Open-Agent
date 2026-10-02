import { describe, expect, it } from "vitest";
import agent from "../src/index.js";

describe("vault-agent", () => {
  it("looks up entries", async () => {
    const ctx: any = { tools: { invoke: async () => ({ value: "redacted-handle" }) } };
    const out: any = await (agent as any).run(ctx, { path: "kv/db" });
    expect(out.path).toBe("kv/db");
  });
});
