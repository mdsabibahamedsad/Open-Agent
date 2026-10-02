import { describe, expect, it } from "vitest";
import node from "../src/index.js";

describe("text.uppercase", () => {
  it("uppercases", async () => {
    expect(await (node as any).execute({}, { text: "hello" })).toEqual({ text: "HELLO" });
  });
  it("validates input", () => {
    expect((node as any).validate({ text: 42 })).toHaveLength(1);
    expect((node as any).validate({ text: "ok" })).toHaveLength(0);
  });
});
