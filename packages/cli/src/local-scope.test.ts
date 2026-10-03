import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";
import {
  findProjectDir,
  globalWorkspaceDir,
  initProject,
  resolveRuntimeProject,
} from "./local.js";

describe("runtime project resolution", () => {
  it("prefers the nearest local project", () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "oa-scope-test-"));
    initProject(dir);
    const sub = path.join(dir, "nested");
    fs.mkdirSync(sub, { recursive: true });
    const r = resolveRuntimeProject(sub, { init: false });
    expect(r.dir).toBe(dir);
    expect(r.scoped).toBe(true);
    fs.rmSync(dir, { recursive: true, force: true });
  });

  it("falls back to the global workspace outside any project", () => {
    process.env.OPENAGENT_QUIET_SCOPE = "1";
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "oa-scope-empty-"));
    const r = resolveRuntimeProject(dir, { init: false });
    expect(r.dir).toBe(globalWorkspaceDir());
    expect(r.scoped).toBe(false);
    expect(findProjectDir(dir)).toBeNull();
    fs.rmSync(dir, { recursive: true, force: true });
  });

  it("initializes the global workspace on demand", () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "oa-scope-init-"));
    const r = resolveRuntimeProject(dir, { init: true });
    expect(fs.existsSync(path.join(r.dir, ".openagent", "config.json"))).toBe(
      true,
    );
    fs.rmSync(dir, { recursive: true, force: true });
  });
});
