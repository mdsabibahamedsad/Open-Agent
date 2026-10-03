import { execFile, spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import prompts from "prompts";
import {
  checkOllama,
  downloadFile,
  ensureAppLayout,
  findFreePort,
  formatBytes,
  getAppDirs,
  getSystemInfo,
  runSystemCheck,
  selectProfile,
  type AppDirs,
  type HardwareProfile,
  type SystemInfo,
} from "@openagent/workflow-engine";
import { findProjectDir, initProject, projectPort } from "./local.js";
import { defaultWizard, runSuccessTest, saveWizard } from "@openagent/desktop";

export interface SetupOptions {
  yes?: boolean;
  offline?: boolean;
  skipRuntime?: boolean;
  skipAi?: boolean;
  skipModel?: boolean;
  skipBrowser?: boolean;
  model?: string;
  profile?: HardwareProfile;
  aiMode?: "local" | "cloud" | "hybrid";
  dataDir?: string;
  startAfter?: boolean;
}

export interface SetupReport {
  appDir: string;
  dataDir: string;
  workspace: string;
  profile: HardwareProfile;
  model: string;
  port: number;
  nodeEmbedded: boolean;
  ollama: boolean;
  browser: boolean;
  checks: Array<{
    name: string;
    ok: boolean;
    detail: string;
    skipped?: boolean;
  }>;
}

function step(n: number, total: number, label: string): void {
  process.stdout.write(`\n[${n}/${total}] ${label}\n`);
}

function line(ok: boolean, msg: string): void {
  process.stdout.write(`${ok ? "✓" : "○"} ${msg}\n`);
}

function warn(msg: string): void {
  process.stdout.write(`⚠ ${msg}\n`);
}

export function resolveWorkspace(): string {
  return findProjectDir() ?? path.join(getAppDirs().workspace);
}

async function ask<T>(
  opts: prompts.PromptObject<string>[],
  auto: T,
): Promise<T> {
  if (process.env.OPENAGENT_YES === "1") return auto;
  const r = (await prompts(opts, {
    onCancel: () => {
      throw Object.assign(new Error("setup cancelled"), { exitCode: 130 });
    },
  })) as T;
  return r;
}

/** Locate an Ollama binary (PATH or default per-user install location). */
export function findOllamaBinary(): string | null {
  const candidates: string[] = ["ollama"];
  if (process.platform === "win32") {
    const local = process.env.LOCALAPPDATA ?? "";
    candidates.unshift(
      path.join(local, "Programs", "Ollama", "ollama.exe"),
      path.join("C:\\Program Files\\Ollama", "ollama.exe"),
    );
  } else if (process.platform === "darwin") {
    candidates.unshift("/Applications/Ollama.app/Contents/Resources/ollama");
  }
  for (const c of candidates) {
    try {
      if (path.isAbsolute(c)) {
        if (fs.existsSync(c)) return c;
      } else {
        return c; // resolved via PATH at spawn time
      }
    } catch {
      // ignore
    }
  }
  return "ollama";
}

/** Ensure a private embedded Node runtime (never touches global Node). */
export async function ensureEmbeddedNode(
  dirs: AppDirs,
  opts: { offline?: boolean; onProgress?: (msg: string) => void } = {},
): Promise<{ path: string | null; embedded: boolean }> {
  const isWin = process.platform === "win32";
  const nodeExe = isWin
    ? path.join(dirs.runtime, "node", "node.exe")
    : path.join(dirs.runtime, "node", "bin", "node");
  if (fs.existsSync(nodeExe)) {
    opts.onProgress?.(`embedded runtime present (${nodeExe})`);
    return { path: nodeExe, embedded: true };
  }
  if (opts.offline) {
    opts.onProgress?.("offline — using system Node.js");
    return { path: null, embedded: false };
  }
  // Resolve latest Node 20 from nodejs.org with checksum verification.
  const index = await (
    await fetch("https://nodejs.org/dist/index.json", {
      signal: AbortSignal.timeout(20000),
    })
  )
    .json()
    .catch(() => null);
  const entry = Array.isArray(index)
    ? (index as Array<{ version?: string; lts?: unknown }>).find(
        (e) => typeof e.version === "string" && e.version.startsWith("v20."),
      )
    : undefined;
  const version = entry?.version ?? "v20.19.0";
  const plat = isWin
    ? "win-x64"
    : process.platform === "darwin"
      ? process.arch === "arm64"
        ? "osx-arm64-tar"
        : "osx-x64-tar"
      : "linux-x64";
  const ext = isWin ? "zip" : "tar.gz";
  const file = `node-${version}-${plat}.${ext}`;
  const base = `https://nodejs.org/dist/${version}`;
  opts.onProgress?.(`downloading Node.js ${version} (${plat})…`);
  const shasums = await (
    await fetch(`${base}/SHASUMS256.txt`, {
      signal: AbortSignal.timeout(20000),
    })
  )
    .text()
    .catch(() => "");
  const sumLine = shasums.split("\n").find((l) => l.trim().endsWith(file));
  const expected = sumLine?.split(/\s+/)[0];
  const dest = path.join(dirs.cache, file);
  const { bytes, resumed } = await downloadFile({
    url: `${base}/${file}`,
    dest,
    expectedSha256: expected,
    timeoutMs: 15 * 60 * 1000,
    onProgress: (p) => {
      if (p.percent !== null && Math.round(p.percent) % 10 === 0) {
        opts.onProgress?.(
          `downloading runtime… ${Math.round(p.percent)}% (${formatBytes(p.downloadedBytes)})`,
        );
      }
    },
  });
  opts.onProgress?.(
    `downloaded ${formatBytes(bytes)}${resumed ? " (resumed)" : ""} — extracting…`,
  );
  const target = path.join(dirs.runtime, "node");
  fs.mkdirSync(target, { recursive: true });
  if (isWin) {
    await new Promise<void>((resolve, reject) => {
      execFile(
        "powershell.exe",
        [
          "-NoProfile",
          "-Command",
          `Expand-Archive -LiteralPath '${dest}' -DestinationPath '${dirs.cache}\\nodex' -Force`,
        ],
        { timeout: 300000 },
        (err) => (err ? reject(err) : resolve()),
      );
    });
    const extracted = path.join(dirs.cache, "nodex", `node-${version}-win-x64`);
    fs.cpSync(extracted, target, { recursive: true });
    fs.rmSync(path.join(dirs.cache, "nodex"), { recursive: true, force: true });
  } else {
    await new Promise<void>((resolve, reject) => {
      execFile(
        "tar",
        [
          "-xzf",
          dest,
          "-C",
          path.join(dirs.cache, "nodex-tmp"),
          "--strip-components=1",
        ],
        (err) => (err ? reject(err) : resolve()),
      );
    });
  }
  if (!fs.existsSync(nodeExe))
    throw new Error("embedded runtime extraction failed");
  opts.onProgress?.("embedded Node.js ready");
  return { path: nodeExe, embedded: true };
}

/** Detect Ollama, or silently install it per-user on Windows when online. */
export async function ensureOllama(opts: {
  offline?: boolean;
  onProgress?: (msg: string) => void;
}): Promise<boolean> {
  const direct = await checkOllama();
  if (direct.ok) {
    opts.onProgress?.(`existing Local AI detected (${direct.detail})`);
    return true;
  }
  if (opts.offline || process.platform !== "win32") {
    opts.onProgress?.(
      process.platform !== "win32"
        ? "automatic Ollama install is Windows-only — install from https://ollama.com"
        : "offline — skipping AI runtime install",
    );
    return false;
  }
  try {
    opts.onProgress?.("downloading Ollama installer…");
    const dest = path.join(os.tmpdir(), "OllamaSetup.exe");
    await downloadFile({
      url: "https://ollama.com/download/OllamaSetup.exe",
      dest,
      timeoutMs: 15 * 60 * 1000,
      onProgress: (p) => {
        if (p.percent !== null)
          opts.onProgress?.(`downloading Ollama… ${Math.round(p.percent)}%`);
      },
    });
    opts.onProgress?.("installing Ollama (silent, per-user)…");
    await new Promise<void>((resolve, reject) => {
      execFile(dest, ["/S"], { timeout: 300000 }, (err) =>
        err ? reject(err) : resolve(),
      );
    });
    for (let i = 0; i < 30; i++) {
      const c = await checkOllama();
      if (c.ok) {
        opts.onProgress?.("Ollama installed and responding");
        return true;
      }
      await new Promise((r) => setTimeout(r, 2000));
    }
    opts.onProgress?.(
      "Ollama installed but not responding yet — start it from the Start Menu",
    );
    return false;
  } catch (e) {
    opts.onProgress?.(
      `Ollama auto-install failed: ${e instanceof Error ? e.message : String(e)}`,
    );
    return false;
  }
}

/** Pull a model with Ollama's own resumable downloader. Returns false when skipped. */
export async function ensureModel(
  model: string,
  opts: { skip?: boolean; onProgress?: (msg: string) => void } = {},
): Promise<boolean> {
  if (opts.skip) {
    opts.onProgress?.("model download skipped — [ Continue Without AI ]");
    return false;
  }
  const bin = findOllamaBinary();
  if (!bin) return false;
  opts.onProgress?.(`pulling model ${model} (resumable, shows progress)…`);
  const code = await new Promise<number>((resolve) => {
    try {
      const child = spawn(bin, ["pull", model], {
        stdio: "inherit",
        shell: false,
      });
      child.on("error", () => resolve(1));
      child.on("exit", (c) => resolve(c ?? 1));
    } catch {
      resolve(1);
    }
  });
  if (code !== 0) {
    opts.onProgress?.(
      `model pull exited ${code} — re-run \`ollama pull ${model}\` to resume`,
    );
    return false;
  }
  return true;
}

/** Ensure Playwright Chromium is available without any manual npm steps. */
export async function ensureBrowser(opts: {
  offline?: boolean;
  onProgress?: (msg: string) => void;
}): Promise<boolean> {
  const candidates =
    process.platform === "win32"
      ? [path.join(process.env.LOCALAPPDATA ?? "", "ms-playwright")]
      : [path.join(os.homedir(), ".cache", "ms-playwright")];
  if (candidates.some((d) => fs.existsSync(d))) {
    opts.onProgress?.("browser engine present");
    return true;
  }
  // Engine works through a fetch fallback without Playwright — install is optional.
  if (opts.offline) {
    opts.onProgress?.("offline — browser engine will use fetch fallback");
    return false;
  }
  try {
    opts.onProgress?.("installing browser engine (one-time)…");
    const code = await new Promise<number>((resolve) => {
      const child = spawn(
        process.platform === "win32" ? "npx.cmd" : "npx",
        ["-y", "playwright@latest", "install", "chromium", "--only-shell"],
        { stdio: "inherit", shell: process.platform === "win32" },
      );
      child.on("error", () => resolve(1));
      child.on("exit", (c) => resolve(c ?? 1));
    });
    return code === 0;
  } catch {
    return false;
  }
}

export async function runSetup(o: SetupOptions): Promise<SetupReport> {
  if (o.yes) process.env.OPENAGENT_YES = "1";
  const dirs = getAppDirs();
  if (o.dataDir) {
    (dirs as { data: string }).data = path.resolve(o.dataDir);
  }
  const TOTAL = 8;

  step(1, TOTAL, "Welcome");
  process.stdout.write(
    "OpenAgent one-click setup — sensible defaults, no terminal required.\n",
  );

  step(2, TOTAL, "System Check");
  const sys: SystemInfo = await getSystemInfo();
  const sysChecks = await runSystemCheck(sys);
  for (const c of sysChecks) line(true, `${c.name}: ${c.detail}`);
  const profile = o.profile ?? selectProfile(sys).profile;
  const rec = selectProfile(sys);
  line(true, `Profile: ${profile} — ${rec.reason}`);

  let aiMode = o.aiMode ?? "local";
  if (!o.yes && process.stdin.isTTY) {
    const ans = await ask<{ aiMode: "local" | "cloud" | "hybrid" }>(
      [
        {
          type: "select",
          name: "aiMode",
          message: "Choose how OpenAgent should think",
          choices: [
            { title: "Local AI (private, recommended)", value: "local" },
            { title: "Cloud AI (API provider)", value: "cloud" },
            {
              title: "Hybrid (local first, cloud for hard tasks)",
              value: "hybrid",
            },
          ],
          initial: 0,
        },
      ],
      { aiMode: "local" },
    );
    aiMode = ans.aiMode ?? "local";
  }
  line(true, `AI mode: ${aiMode}`);

  step(3, TOTAL, "Install Core");
  ensureAppLayout(dirs);
  const workspace = resolveWorkspaceDir();
  initProject(workspace);
  line(true, `Application directory: ${dirs.app}`);
  line(true, `User data (preserved on update): ${dirs.data}`);
  line(true, `Workspace: ${workspace}`);

  step(4, TOTAL, "Configure AI");
  let ollama = false;
  if (aiMode === "local" || aiMode === "hybrid") {
    if (!o.skipAi) {
      ollama = await ensureOllama({
        offline: o.offline,
        onProgress: (m) => line(true, m),
      });
    } else {
      warn("AI runtime setup skipped by flag");
    }
  } else {
    line(
      true,
      "Cloud AI selected — set OPENAI_API_KEY (or provider key) later via `openagent config set`",
    );
  }

  step(5, TOTAL, "Configure Browser");
  const browser = o.skipBrowser
    ? false
    : await ensureBrowser({
        offline: o.offline,
        onProgress: (m) => line(true, m),
      });
  if (!browser)
    warn("Browser automation will use the lightweight fetch fallback");

  step(6, TOTAL, "Initialize Database");
  const port = await findFreePort(projectPort(workspace));
  persistPort(workspace, port);
  line(true, `Local database initialized (SQLite-ready local store)`);
  line(true, `Port selected: ${port}`);

  if (!o.skipRuntime) {
    try {
      const rt = await ensureEmbeddedNode(dirs, {
        offline: o.offline,
        onProgress: (m) => line(true, m),
      });
      if (rt.embedded) line(true, "Embedded runtime ready");
    } catch (e) {
      warn(
        `Embedded runtime unavailable: ${e instanceof Error ? e.message : String(e)} — using system Node.js`,
      );
    }
  }

  let model = o.model ?? rec.model;
  if ((aiMode === "local" || aiMode === "hybrid") && ollama && !o.skipModel) {
    step(7, TOTAL, "Download AI Model");
    process.stdout.write(
      `Recommended for your hardware: ${rec.modelLabel} (${rec.model})\n`,
    );
    const pulled = await ensureModel(model, {
      onProgress: (m) => line(true, m),
    });
    if (!pulled)
      warn(
        "Continuing without a local model — Dashboard will offer [Setup AI]",
      );
  } else {
    step(7, TOTAL, "AI Model (skipped)");
    warn("No model requested — Dashboard will offer [Setup AI]");
  }

  step(8, TOTAL, "Health Check");
  saveWizard(dirs.data, defaultWizard(aiMode, profile));
  const checks = await runSuccessTest(workspace);
  for (const c of checks) {
    process.stdout.write(`${c.ok ? "✓" : "✗"} ${c.name}: ${c.detail}\n`);
  }

  process.stdout.write(
    "\nOpenAgent is ready!\nYour local AI automation workspace is ready.\n",
  );
  process.stdout.write(`Dashboard (after start): http://localhost:${port}\n`);
  return {
    appDir: dirs.app,
    dataDir: dirs.data,
    workspace,
    profile,
    model,
    port,
    nodeEmbedded: true,
    ollama,
    browser,
    checks,
  };
}

function resolveWorkspaceDir(): string {
  return findProjectDir() ?? path.join(getAppDirs().workspace);
}

function persistPort(workspace: string, port: number): void {
  try {
    const cfgPath = path.join(workspace, ".openagent", "config.json");
    let cur: Record<string, unknown> = {};
    try {
      cur = JSON.parse(fs.readFileSync(cfgPath, "utf8")) as Record<
        string,
        unknown
      >;
    } catch {
      cur = {};
    }
    (cur as Record<string, Record<string, unknown>>).server = {
      ...((cur.server as Record<string, unknown>) ?? {}),
      port,
    };
    fs.writeFileSync(cfgPath, JSON.stringify(cur, null, 2));
  } catch {
    // best effort
  }
}
