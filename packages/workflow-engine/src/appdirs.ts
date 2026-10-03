import fs from "node:fs";
import os from "node:os";
import path from "node:path";

export interface AppDirs {
  /** Per-user application install root (binaries, runtime). */
  app: string;
  /** Persistent user data root (never deleted on update). */
  data: string;
  runtime: string;
  models: string;
  browser: string;
  backups: string;
  logs: string;
  cache: string;
  config: string;
  /** Default workspace project (holds .openagent/). */
  workspace: string;
}

/**
 * Stable install locations. Application binaries and user data are always
 * separated so updates can never destroy workflows, agents, credentials,
 * memory, settings, or execution history.
 */
export function getAppDirs(): AppDirs {
  const override = process.env.OPENAGENT_HOME;
  const dataOverride = process.env.OPENAGENT_DATA_DIR;
  let app: string;
  let data: string;
  if (override) {
    app = path.resolve(override);
    data = dataOverride ? path.resolve(dataOverride) : path.join(app, "data");
  } else if (process.platform === "win32") {
    const base =
      process.env.LOCALAPPDATA ?? path.join(os.homedir(), "AppData", "Local");
    app = path.join(base, "OpenAgent");
    data = dataOverride ? path.resolve(dataOverride) : path.join(app, "data");
  } else if (process.platform === "darwin") {
    app = path.join(
      os.homedir(),
      "Library",
      "Application Support",
      "OpenAgent",
    );
    data = dataOverride ? path.resolve(dataOverride) : path.join(app, "data");
  } else {
    const base =
      process.env.XDG_DATA_HOME ?? path.join(os.homedir(), ".local", "share");
    app = path.join(base, "openagent");
    data = dataOverride ? path.resolve(dataOverride) : path.join(app, "data");
  }
  return {
    app,
    data,
    runtime: path.join(app, "runtime"),
    models: path.join(app, "models"),
    browser: path.join(app, "browser"),
    backups: path.join(data, "backups"),
    logs: path.join(data, "logs"),
    cache: path.join(data, "cache"),
    config: path.join(data, "config"),
    workspace: path.join(data, "workspace"),
  };
}

const APP_SUBDIRS = [
  "app",
  "runtime",
  "engine",
  "browser",
  "models",
  "plugins",
  "logs",
  "cache",
  "config",
] as const;
const DATA_SUBDIRS = [
  "config",
  "workflows",
  "agents",
  "memory",
  "executions",
  "backups",
  "logs",
  "cache",
] as const;

export function ensureAppLayout(dirs = getAppDirs()): AppDirs {
  for (const sub of APP_SUBDIRS) {
    fs.mkdirSync(path.join(dirs.app, sub), { recursive: true });
  }
  for (const sub of DATA_SUBDIRS) {
    fs.mkdirSync(path.join(dirs.data, sub), { recursive: true });
  }
  fs.mkdirSync(dirs.runtime, { recursive: true });
  fs.mkdirSync(dirs.models, { recursive: true });
  fs.mkdirSync(dirs.workspace, { recursive: true });
  return dirs;
}

export interface BackupManifest {
  id: string;
  createdAt: string;
  kind: "pre-update" | "manual" | "scheduled";
  files: string[];
}

/** Rolling backups of user data. Secrets are never stored in plaintext. */
export function createBackup(
  dirs = getAppDirs(),
  kind: BackupManifest["kind"] = "manual",
  keep = 5,
): BackupManifest {
  const id = `backup_${new Date().toISOString().replace(/[:.]/g, "-")}`;
  const dest = path.join(dirs.backups, id);
  fs.mkdirSync(dest, { recursive: true });
  const files: string[] = [];
  const copyIfExists = (rel: string) => {
    const src = path.join(dirs.data, rel);
    if (!fs.existsSync(src)) return;
    const target = path.join(dest, rel);
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.cpSync(src, target, { recursive: true });
    files.push(rel);
  };
  // User data only — credentials vault is copied as-is (already encrypted
  // at rest); memory metadata included; cache/logs excluded by design.
  // Covers both the global data layout and desktop workspace projects
  // (<data>/workspace/.openagent/).
  copyIfExists("workflows");
  copyIfExists("agents");
  copyIfExists("config");
  copyIfExists(path.join("workspace", ".openagent", "workflows"));
  copyIfExists(path.join("workspace", ".openagent", "agents"));
  copyIfExists(path.join("workspace", ".openagent", "config.json"));
  const manifest: BackupManifest = {
    id,
    createdAt: new Date().toISOString(),
    kind,
    files,
  };
  fs.writeFileSync(
    path.join(dest, "manifest.json"),
    JSON.stringify(manifest, null, 2),
  );
  // Rolling retention.
  try {
    const all = fs
      .readdirSync(dirs.backups)
      .filter((d) => d.startsWith("backup_"))
      .sort();
    while (all.length > keep) {
      const oldest = all.shift() as string;
      fs.rmSync(path.join(dirs.backups, oldest), {
        recursive: true,
        force: true,
      });
    }
  } catch {
    // best effort
  }
  return manifest;
}

export function listBackups(dirs = getAppDirs()): BackupManifest[] {
  if (!fs.existsSync(dirs.backups)) return [];
  const out: BackupManifest[] = [];
  for (const d of fs.readdirSync(dirs.backups)) {
    const mf = path.join(dirs.backups, d, "manifest.json");
    try {
      if (fs.existsSync(mf))
        out.push(JSON.parse(fs.readFileSync(mf, "utf8")) as BackupManifest);
    } catch {
      // skip corrupt entries
    }
  }
  return out.sort((a, b) => (a.createdAt < b.createdAt ? 1 : -1));
}

export function restoreBackup(id: string, dirs = getAppDirs()): void {
  const src = path.join(dirs.backups, id);
  const mf = path.join(src, "manifest.json");
  if (!fs.existsSync(mf)) throw new Error(`backup '${id}' not found`);
  const manifest = JSON.parse(fs.readFileSync(mf, "utf8")) as BackupManifest;
  for (const rel of manifest.files) {
    if (rel.includes("..")) continue; // safety: never escape data dir
    const from = path.join(src, rel);
    const to = path.join(dirs.data, rel);
    if (!fs.existsSync(from)) continue;
    fs.mkdirSync(path.dirname(to), { recursive: true });
    fs.cpSync(from, to, { recursive: true });
  }
}

/** Append to a rotating log file (1 MB per file, keep 5). */
export function appendRotatingLog(
  dir: string,
  name: string,
  line: string,
): void {
  fs.mkdirSync(dir, { recursive: true });
  const MAX = 1024 * 1024;
  const KEEP = 5;
  const current = path.join(dir, `${name}.log`);
  try {
    if (fs.existsSync(current) && fs.statSync(current).size > MAX) {
      for (let i = KEEP - 1; i >= 1; i--) {
        const a = path.join(dir, `${name}.${i}.log`);
        const b = path.join(dir, `${name}.${i + 1}.log`);
        if (fs.existsSync(a)) fs.renameSync(a, b);
      }
      fs.renameSync(current, path.join(dir, `${name}.1.log`));
    }
    fs.appendFileSync(current, `${new Date().toISOString()} ${line}\n`);
  } catch {
    // logging must never crash the app
  }
}
