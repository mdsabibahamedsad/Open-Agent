import { execFile, execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  createBackup,
  downloadFile,
  ensureAppLayout,
  getAppDirs,
  listBackups,
  restoreBackup,
} from "@openagent/workflow-engine";
import { stopEngine } from "./lifecycle.js";

/** Source of truth for updates: the Git repository's releases, not npm. */
export const UPDATE_REPO =
  process.env.OPENAGENT_UPDATE_REPO ?? "mdsabibahamedsad/Open-Agent";

export interface UpdateInfo {
  current: string;
  latest: string;
  available: boolean;
  /** Where the candidate came from. `none` = up to date or offline. */
  source: "github" | "npm" | "none";
  /** Release tag (e.g. `v1.0.0`) when source is github. */
  tag?: string;
}

/** Normalize a release tag (`v1.2.3`, `1.2.3`) to a version, or null. */
export function releaseTagToVersion(tag: string): string | null {
  const m = tag.trim().match(/^v?(\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?)$/);
  return m ? (m[1] as string) : null;
}

/**
 * Compare two versions numerically (`1` = newer, `-1` = older, `0` = equal).
 * Platform (0.x) and component (1.x) lines differ, so plain `!==` would
 * wrongly offer downgrades — only a strictly newer release is an update.
 */
export function compareVersions(a: string, b: string): number {
  const parts = (v: string) =>
    v
      .split(/[+-]/)[0]
      ?.split(".")
      .map((n) => Number(n) || 0) ?? [0, 0, 0];
  const pa = parts(a);
  const pb = parts(b);
  for (let i = 0; i < 3; i++) {
    if ((pa[i] ?? 0) !== (pb[i] ?? 0))
      return (pa[i] ?? 0) > (pb[i] ?? 0) ? 1 : -1;
  }
  return 0;
}

export async function checkForUpdates(
  packageName: string,
  current: string,
  timeoutMs = 10000,
): Promise<UpdateInfo> {
  // GitHub releases first — the repository is the source of truth.
  try {
    const res = await fetch(
      `https://api.github.com/repos/${UPDATE_REPO}/releases/latest`,
      {
        headers: { Accept: "application/vnd.github+json" },
        signal: AbortSignal.timeout(timeoutMs),
      },
    );
    if (res.ok) {
      const j = (await res.json()) as { tag_name?: string };
      const v = j.tag_name ? releaseTagToVersion(j.tag_name) : null;
      if (v) {
        const newer = compareVersions(v, current) > 0;
        return {
          current,
          latest: v,
          available: newer,
          source: newer ? "github" : "none",
          tag: j.tag_name,
        };
      }
    }
  } catch {
    // offline or no releases yet — try npm as a secondary source
  }
  let latest = current;
  try {
    const res = await fetch(
      `https://registry.npmjs.org/${encodeURIComponent(packageName)}/latest`,
      {
        signal: AbortSignal.timeout(timeoutMs),
      },
    );
    if (res.ok) {
      const j = (await res.json()) as { version?: string };
      if (j.version) latest = j.version;
    }
  } catch {
    // offline — no update info
  }
  const newer = compareVersions(latest, current) > 0;
  return {
    current,
    latest,
    available: newer,
    source: newer ? "npm" : "none",
  };
}

function npmRun(args: string[], cwd: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const cmd = process.platform === "win32" ? "cmd.exe" : "npm";
    const fullArgs =
      process.platform === "win32"
        ? ["/d", "/s", "/c", `npm ${args.join(" ")}`]
        : args;
    const child = execFile(cmd, fullArgs, { cwd, timeout: 300000 }, (err) => {
      if (err)
        reject(new Error(`update step failed: ${err.message.slice(0, 400)}`));
      else resolve();
    });
    void child;
  });
}

export interface UpdateResult {
  updated: boolean;
  from: string;
  to: string;
  backupId?: string;
  rolledBack?: boolean;
  /** Human-readable outcome, especially when no update was applied. */
  detail?: string;
}

/** How this copy of OpenAgent was installed (decides the update path). */
export function detectInstallMode(
  cwd: string,
  entrypoint = process.argv[1] ?? "",
): "dev" | "npm" | "portable" {
  if (fs.existsSync(path.join(path.resolve(cwd), "pnpm-workspace.yaml")))
    return "dev";
  const ep = entrypoint.replace(/\\/g, "/").toLowerCase();
  if (
    ep.includes("node_modules/") &&
    (ep.includes(".npm-global") ||
      ep.includes("npm/node_modules") ||
      ep.includes("nodejs/node_modules"))
  )
    return "npm";
  return "portable";
}

function extractZip(zipPath: string, destDir: string): void {
  fs.mkdirSync(destDir, { recursive: true });
  if (process.platform === "win32") {
    execFileSync(
      "powershell.exe",
      [
        "-NoProfile",
        "-Command",
        `Expand-Archive -LiteralPath '${zipPath}' -DestinationPath '${destDir}' -Force`,
      ],
      { stdio: "pipe", timeout: 10 * 60 * 1000 },
    );
    return;
  }
  execFileSync("unzip", ["-q", "-o", zipPath, "-d", destDir], {
    stdio: "pipe",
    timeout: 10 * 60 * 1000,
  });
}

function nodeVersionOf(cliJs: string): string | null {
  try {
    const out = execFileSync(process.execPath, [cliJs, "--version"], {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"],
      timeout: 60000,
    }).trim();
    return /^\d+\.\d+\.\d+/.test(out) ? out : null;
  } catch {
    return null;
  }
}

/**
 * Safe update: snapshot user data first, install, verify, rollback on failure.
 * User data is never destroyed — rollback restores the pre-update snapshot.
 *
 * Source of truth is the GitHub release bundle. npm is used only when this
 * copy was itself installed from npm; dev checkouts update via git + setup.
 */
export async function updateWithRollback(opts: {
  packageName: string;
  current: string;
  cwd: string;
  createSnapshot?: boolean;
}): Promise<UpdateResult> {
  const info = await checkForUpdates(opts.packageName, opts.current);
  if (!info.available)
    return {
      updated: false,
      from: info.current,
      to: info.latest,
      detail: "Already up to date.",
    };

  const dirs = getAppDirs();
  let backupId: string | undefined;
  if (opts.createSnapshot !== false) {
    try {
      backupId = createBackup(dirs, "pre-update").id;
    } catch {
      // snapshot is best-effort; update still proceeds
    }
  }
  const rollback = (): UpdateResult => {
    if (backupId) {
      try {
        restoreBackup(backupId, dirs);
        return {
          updated: false,
          from: info.current,
          to: info.latest,
          backupId,
          rolledBack: true,
        };
      } catch {
        // fall through
      }
    }
    return { updated: false, from: info.current, to: info.latest, backupId };
  };

  const mode = detectInstallMode(opts.cwd);
  try {
    if (mode === "dev") {
      return {
        updated: false,
        from: info.current,
        to: info.latest,
        backupId,
        detail:
          "Dev checkout detected — update with `git pull` then `setup.cmd`. No files were changed.",
      };
    }
    if (mode === "npm" || info.source === "npm") {
      await npmRun(
        ["install", "-g", `${opts.packageName}@${info.latest}`],
        opts.cwd,
      );
      return { updated: true, from: info.current, to: info.latest, backupId };
    }
    // Portable / per-user installer layout: release bundle overlay.
    // Never touches user data — only app payload directories.
    if (!info.tag) throw new Error("release tag unknown");
    const base = `https://github.com/${UPDATE_REPO}/releases/download/${info.tag}`;
    const updDir = path.join(dirs.data, "updates");
    fs.mkdirSync(updDir, { recursive: true });
    const zipName = `openagent-${info.tag}-win-x64.zip`;
    const zipPath = path.join(updDir, zipName);
    const shaRes = await fetch(`${base}/openagent-win-x64.zip.sha256`, {
      signal: AbortSignal.timeout(30000),
    });
    if (!shaRes.ok) throw new Error("checksum file unavailable");
    const expected = (await shaRes.text()).split(/\s+/)[0] ?? "";
    if (!/^[0-9a-f]{64}$/i.test(expected)) throw new Error("bad checksum file");
    await downloadFile({
      url: `${base}/openagent-win-x64.zip`,
      dest: zipPath,
      expectedSha256: expected,
      timeoutMs: 30 * 60 * 1000,
    });
    const staged = path.join(
      fs.mkdtempSync(path.join(os.tmpdir(), "oa-update-")),
      "OpenAgent",
    );
    extractZip(zipPath, path.dirname(staged));
    const stagedRoot = fs.existsSync(
      path.join(path.dirname(staged), "OpenAgent"),
    )
      ? path.join(path.dirname(staged), "OpenAgent")
      : path.dirname(staged);
    const stagedCli = path.join(
      stagedRoot,
      "app",
      "cli",
      "bin",
      "openagent.js",
    );
    const verified = fs.existsSync(stagedCli) ? nodeVersionOf(stagedCli) : null;
    if (verified !== info.latest)
      throw new Error(
        `staged bundle failed verification (got ${verified ?? "nothing"})`,
      );
    // Stop a running engine so files are not locked, then overlay payload.
    try {
      await stopEngine(path.join(dirs.workspace, ".openagent"));
    } catch {
      // engine was not running
    }
    ensureAppLayout(dirs);
    for (const sub of ["app", "bin", "runtime", "tools"]) {
      const from = path.join(stagedRoot, sub);
      if (!fs.existsSync(from)) continue;
      fs.cpSync(from, path.join(dirs.app, sub), { recursive: true });
    }
    fs.rmSync(path.dirname(staged), { recursive: true, force: true });
    return {
      updated: true,
      from: info.current,
      to: info.latest,
      backupId,
      detail: `Installed ${info.tag} from GitHub releases. User data preserved.`,
    };
  } catch (e) {
    const r = rollback();
    if (!r.rolledBack) throw e;
    return r;
  }
}

export async function downloadReleaseBundle(opts: {
  url: string;
  dest: string;
  expectedSha256?: string;
  onProgress?: (
    percent: number | null,
    downloaded: number,
    total: number | null,
  ) => void;
}): Promise<string> {
  const r = await downloadFile({
    url: opts.url,
    dest: opts.dest,
    expectedSha256: opts.expectedSha256,
    timeoutMs: 30 * 60 * 1000,
    onProgress: (p) =>
      opts.onProgress?.(p.percent, p.downloadedBytes, p.totalBytes),
  });
  return r.path;
}

export { listBackups };
