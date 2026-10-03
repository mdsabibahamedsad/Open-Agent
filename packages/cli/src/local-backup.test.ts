import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";
import {
  createProjectBackup,
  initProject,
  listProjectBackups,
  restoreProjectBackup,
} from "./local.js";

function makeProject(): string {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "oa-backup-test-"));
  initProject(dir);
  fs.writeFileSync(
    path.join(dir, ".openagent", "workflows", "demo.json"),
    JSON.stringify({ id: "demo", name: "Demo", nodes: [], edges: [] }),
  );
  return dir;
}

describe("project backups", () => {
  it("creates, lists and restores backups", () => {
    const dir = makeProject();
    const m = createProjectBackup(dir, 5);
    expect(m.id.startsWith("backup_")).toBe(true);
    expect(m.files).toContain("workflows");
    expect(listProjectBackups(dir).length).toBe(1);

    fs.rmSync(path.join(dir, ".openagent", "workflows", "demo.json"));
    restoreProjectBackup(dir, m.id);
    expect(
      fs.existsSync(path.join(dir, ".openagent", "workflows", "demo.json")),
    ).toBe(true);
    fs.rmSync(dir, { recursive: true, force: true });
  });

  it("keeps rolling retention", () => {
    const dir = makeProject();
    for (let i = 0; i < 7; i++) {
      createProjectBackup(dir, 3);
    }
    expect(listProjectBackups(dir).length).toBeLessThanOrEqual(3);
    fs.rmSync(dir, { recursive: true, force: true });
  });

  it("rejects unknown backup ids", () => {
    const dir = makeProject();
    expect(() => restoreProjectBackup(dir, "backup_nope")).toThrow();
    fs.rmSync(dir, { recursive: true, force: true });
  });
});
