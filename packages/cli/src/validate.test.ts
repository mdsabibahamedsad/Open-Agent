import { describe, expect, it } from "vitest";
import { validateManifestObject } from "./validate.js";

const GOOD_YAML = `
manifest_version: '1'
name: my-tool
version: 0.1.0
type: tool
description: A useful tool for testing purposes.
license: MIT
runtime:
  entrypoint: src/index.ts
  language: typescript
permissions:
  - tool:execute
compatibility:
  openagent: '>=1.0.0 <2.0.0'
`;

function goodManifest(): Record<string, unknown> {
  return {
    manifest_version: "1",
    name: "my-tool",
    version: "0.1.0",
    type: "tool",
    description: "A useful tool for testing purposes.",
    license: "MIT",
    runtime: { entrypoint: "src/index.ts", language: "typescript" },
    permissions: ["tool:execute"],
    compatibility: { openagent: ">=1.0.0 <2.0.0" },
  };
}

describe("validateManifestObject", () => {
  it("accepts a good manifest", () => {
    const { errors } = validateManifestObject(goodManifest(), "openagent.yaml", GOOD_YAML);
    expect(errors).toEqual([]);
  });

  it("rejects a bad type", () => {
    const m = goodManifest();
    m.type = "not-a-real-type";
    const { errors } = validateManifestObject(m, "openagent.yaml", GOOD_YAML);
    expect(errors.some((e) => e.field === "type")).toBe(true);
  });

  it("rejects unknown permission", () => {
    const m = goodManifest();
    m.permissions = ["teleport:anywhere"];
    const { errors } = validateManifestObject(m, "openagent.yaml", GOOD_YAML);
    expect(errors.some((e) => (e.field ?? "").startsWith("permissions"))).toBe(true);
  });

  it("requires allowed_hosts for network:outbound", () => {
    const m = goodManifest();
    m.permissions = [{ permission: "network:outbound" }];
    const { errors } = validateManifestObject(m, "openagent.yaml", GOOD_YAML);
    expect(errors.some((e) => /allowed_hosts/.test(e.message))).toBe(true);
  });

  it("accepts network:outbound with allowed_hosts", () => {
    const m = goodManifest();
    m.permissions = [{ permission: "network:outbound", allowed_hosts: ["api.example.com"] }];
    const { errors } = validateManifestObject(m, "openagent.yaml", GOOD_YAML);
    expect(errors).toEqual([]);
  });

  it("rejects lowercase secret refs", () => {
    const m = goodManifest();
    m.permissions = ["secret:access"];
    (m as Record<string, unknown>).secrets = ["my_secret"];
    const { errors } = validateManifestObject(m, "openagent.yaml", GOOD_YAML);
    expect(errors.some((e) => e.field === "secrets")).toBe(true);
  });

  it("rejects bad semver", () => {
    const m = goodManifest();
    m.version = "not-a-version";
    const { errors } = validateManifestObject(m, "openagent.yaml", GOOD_YAML);
    expect(errors.some((e) => e.field === "version")).toBe(true);
  });
});
