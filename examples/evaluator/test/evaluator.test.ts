import { describe, expect, it } from "vitest";
import evaluator from "../src/index.js";

describe("no-secret-leak", () => {
  it("passes clean output", async () => {
    expect(await (evaluator as any).evaluate({}, { output: "hello" }))
      .toMatchObject({ score: 1, passed: true });
  });
  it("fails key material", async () => {
    expect(await (evaluator as any).evaluate({}, { output: "key AKIAIOSFODNN7EXAMPLE" }))
      .toMatchObject({ score: 0, passed: false });
  });
});
