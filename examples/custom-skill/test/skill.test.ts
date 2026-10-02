import { describe, expect, it } from "vitest";
import skill from "../src/index.js";

describe("incident-triage", () => {
  it("renders prompts", () => {
    expect((skill as any).renderPrompt("triage.prompt", { symptoms: "500s" })).toContain("500s");
  });
  it("rejects unknown prompts", () => {
    expect(() => (skill as any).renderPrompt("nope", {})).toThrow();
  });
});
