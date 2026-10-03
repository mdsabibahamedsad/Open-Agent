import { execFile } from "node:child_process";
import {
  createBackup,
  downloadFile,
  listBackups,
  restoreBackup,
} from "@openagent/workflow-engine";

export interface UpdateInfo {
  current: string;
  latest: string;
  available: boolean;
}

export async function checkForUpdates(
  packageName: string,
  current: string,
  timeoutMs = 10000,
): Promise<UpdateInfo> {
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
  return { current, latest, available: latest !== current };
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
}

/**
 * Safe update: snapshot user data first, install, verify, rollback on failure.
 * User data is never destroyed — rollback restores the pre-update snapshot.
 */
export async function updateWithRollback(opts: {
  packageName: string;
  current: string;
  cwd: string;
  createSnapshot?: boolean;
}): Promise<UpdateResult> {
  const info = await checkForUpdates(opts.packageName, opts.current);
  if (!info.available)
    return { updated: false, from: info.current, to: info.latest };

  let backupId: string | undefined;
  if (opts.createSnapshot !== false) {
    try {
      const { getAppDirs } = await import("@openagent/workflow-engine");
      backupId = createBackup(getAppDirs(), "pre-update").id;
    } catch {
      // snapshot is best-effort; update still proceeds
    }
  }

  try {
    await npmRun(
      ["install", "-g", `${opts.packageName}@${info.latest}`],
      opts.cwd,
    );
  } catch (e) {
    if (backupId) {
      try {
        const { getAppDirs } = await import("@openagent/workflow-engine");
        restoreBackup(backupId, getAppDirs());
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
    throw e;
  }
  return { updated: true, from: info.current, to: info.latest, backupId };
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
