// Tests for @openagent/developer-tools: validator, scanner, docgen, migration.
import { describe, expect, it } from "vitest";
import {
  findDeprecatedUsages,
  generateDocs,
  runToolContract,
  scanFiles,
  validateManifest,
} from "./index";

const good = {
  name: "example-tool",
  version: "1.0.0",
  description: "Example",
  author: { name: "Acme" },
  license: "MIT",
  type: "tool",
  runtime: { language: "typescript", entrypoint: "src/index.ts" },
  permissions: ["tool:execute"],
};

describe("developer-tools", () => {
  it("accepts a valid manifest", () => {
    expect(
      validateManifest(good).filter((i) => i.severity === "error"),
    ).toEqual([]);
  });

  it("rejects bad type/permission/version/secret", () => {
    const issues = validateManifest({
      ...good,
      type: "teleporter",
      version: "1.0",
      permissions: ["root:all"],
      secrets: ["sk-live-value"],
    });
    const errors = issues.filter((i) => i.severity === "error");
    expect(errors.length).toBeGreaterThanOrEqual(4);
    expect(errors.some((e) => e.fix)).toBe(true);
  });

  it("requires allowlist for outbound", () => {
    const issues = validateManifest({
      ...good,
      permissions: ["network:outbound"],
    });
    expect(issues.some((i) => i.location === "network.allowed_hosts")).toBe(
      true,
    );
  });

  it("secret scan blocks publish; clean passes", () => {
    expect(
      scanFiles({ "src/a.ts": 'const k = "AKIAIOSFODNN7EXAMPLE";' })
        .blocksPublish,
    ).toBe(true);
    expect(scanFiles({ "src/a.ts": "export const x = 1;" }).blocksPublish).toBe(
      false,
    );
  });

  it("docgen produces README + config ref", () => {
    const docs = generateDocs({ ...good, permissions: ["tool:execute"] });
    expect(docs["README.md"]).toContain("example-tool");
    expect(docs["README.md"]).toContain("tool:execute");
  });

  it("migration finder flags deprecated usage", () => {
    const hits = findDeprecatedUsages("client.runs.list()", "src/a.ts");
    expect(hits).toHaveLength(1);
    expect(hits[0].replacement).toContain("agentRuns");
    expect(findDeprecatedUsages("client.agents.list()", "src/a.ts")).toEqual(
      [],
    );
  });

  it("tool contract runs offline", async () => {
    const results = await runToolContract({
      name: "t",
      inputSchema: { type: "object" },
      execute: async () => ({ ok: true }),
    });
    expect(results.every((r) => r.passed)).toBe(true);
  });
});
