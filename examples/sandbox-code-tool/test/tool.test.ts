import { describe, expect, it } from "vitest";
import tool from "../src/index.js";

describe("py.run", () => {
  it("delegates to the sandbox", async () => {
    const ctx: any = { sandbox: { execute: async () => ({ stdout: "3\n" }) } };
    expect(await (tool as any).run(ctx, { code: "print(1+2)" })).toEqual({ stdout: "3\n" });
  });
  it("blocks forbidden modules", async () => {
    await expect((tool as any).run({}, { code: "import os" })).rejects.toThrow();
  });
});
