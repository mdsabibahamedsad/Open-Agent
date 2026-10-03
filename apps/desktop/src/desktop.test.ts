import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";
import {
  findFreePort,
  getAppDirs,
  getTemplate,
  listBackups,
  createBackup,
  restoreBackup,
  runWorkflow,
  selectProfile,
  validateWorkflow,
  FileCredentialResolver,
  FileMemoryManager,
  ToolRegistry,
} from "@openagent/workflow-engine";
import { engineStatus, writePidFile, clearPidFile } from "./lifecycle.js";
import {
  compareVersions,
  detectInstallMode,
  releaseTagToVersion,
} from "./updates.js";

function tmpDir(prefix: string): string {
  const d = path.join(fs.mkdtempSync(path.join(os.tmpdir(), prefix)));
  fs.mkdirSync(d, { recursive: true });
  return d;
}

describe("hardware profiles", () => {
  it("selects LOW below 8GB", () => {
    const p = selectProfile({ totalRamMb: 6 * 1024, cpuCount: 4 });
    expect(p.profile).toBe("LOW");
    expect(p.browserWorkers).toBe(1);
  });
  it("selects BALANCED for 8-16GB", () => {
    const p = selectProfile({ totalRamMb: 12 * 1024, cpuCount: 8 });
    expect(p.profile).toBe("BALANCED");
  });
  it("selects POWER at 16GB+", () => {
    const p = selectProfile({ totalRamMb: 32 * 1024, cpuCount: 12 });
    expect(p.profile).toBe("POWER");
    expect(p.maxWorkers).toBeGreaterThan(4);
  });
});

describe("ports", () => {
  it("finds a free port at or above the preferred one", async () => {
    const port = await findFreePort(5678);
    expect(port).toBeGreaterThanOrEqual(5678);
  });
});

describe("app dirs", () => {
  it("separates app binaries from user data", () => {
    const d = getAppDirs();
    expect(d.data).not.toBe(d.app);
    expect(d.workspace).toContain(d.data);
    expect(d.runtime).toContain(d.app);
  });
});

describe("backups", () => {
  it("round-trips user data", () => {
    const app = tmpDir("oa-app-");
    const data = tmpDir("oa-data-");
    const dirs = { ...getAppDirs(), app, data } as ReturnType<
      typeof getAppDirs
    >;
    fs.mkdirSync(path.join(data, "workflows"), { recursive: true });
    fs.writeFileSync(
      path.join(data, "workflows", "w.json"),
      JSON.stringify({ id: "w" }),
    );
    const m = createBackup(dirs, "manual", 5);
    expect(m.files).toContain("workflows");
    fs.rmSync(path.join(data, "workflows", "w.json"));
    restoreBackup(m.id, dirs);
    expect(fs.existsSync(path.join(data, "workflows", "w.json"))).toBe(true);
    expect(listBackups(dirs).length).toBeGreaterThanOrEqual(1);
    fs.rmSync(app, { recursive: true, force: true });
    fs.rmSync(data, { recursive: true, force: true });
  });
});

describe("hello-ai first workflow", () => {
  it("validates and runs offline", async () => {
    const tpl = getTemplate("hello-ai");
    expect(tpl).toBeDefined();
    const wf = tpl!.build();
    wf.id = "hello-ai";
    expect(validateWorkflow(wf).ok).toBe(true);
    const projectDir = tmpDir("oa-proj-");
    const rec = await runWorkflow(wf, {
      input: { hello: "world" },
      credentials: new FileCredentialResolver(projectDir),
      memory: new FileMemoryManager(projectDir),
      tools: new ToolRegistry(),
      projectDir,
      timeout: 60000,
    });
    expect(rec.status).toBe("SUCCESS");
    fs.rmSync(projectDir, { recursive: true, force: true });
  });
});

describe("release updates (repo is source of truth, not npm)", () => {
  it("normalizes release tags", () => {
    expect(releaseTagToVersion("v1.2.3")).toBe("1.2.3");
    expect(releaseTagToVersion("1.2.3")).toBe("1.2.3");
    expect(releaseTagToVersion("v10.0.0-beta.1")).toBe("10.0.0-beta.1");
    expect(releaseTagToVersion("latest")).toBeNull();
    expect(releaseTagToVersion("")).toBeNull();
  });
  it("never offers a downgrade across version lines", () => {
    expect(compareVersions("1.0.0", "1.0.0")).toBe(0);
    expect(compareVersions("1.1.0", "1.0.0")).toBe(1);
    expect(compareVersions("0.1.0", "1.0.0")).toBe(-1);
    expect(compareVersions("2.0.0", "10.0.0")).toBe(-1);
  });
  it("detects a dev checkout by workspace file", () => {
    // vitest runs with cwd = apps/desktop, so repo root is two levels up.
    const repoRoot = path.resolve(process.cwd(), "..", "..");
    expect(detectInstallMode(repoRoot)).toBe("dev");
  });
  it("detects an npm-global entrypoint", () => {
    const fakeCwd = tmpDir("oa-mode-");
    expect(
      detectInstallMode(
        fakeCwd,
        "C:\\Users\\User\\.npm-global\\node_modules\\@openagent\\cli\\bin\\openagent.js",
      ),
    ).toBe("npm");
    expect(
      detectInstallMode(
        fakeCwd,
        "C:\\Users\\User\\AppData\\Local\\OpenAgent\\bin\\launcher.js",
      ),
    ).toBe("portable");
    fs.rmSync(fakeCwd, { recursive: true, force: true });
  });
});

describe("lifecycle pid file", () => {
  it("reports stopped when no pid file exists", async () => {
    const dataDir = tmpDir("oa-pid-");
    const st = await engineStatus(dataDir);
    expect(st.running).toBe(false);
    writePidFile(dataDir, 999999999, 5678);
    const st2 = await engineStatus(dataDir);
    // bogus pid is not alive → cleaned up, reported stopped
    expect(st2.running).toBe(false);
    clearPidFile(dataDir);
    fs.rmSync(dataDir, { recursive: true, force: true });
  });
});
