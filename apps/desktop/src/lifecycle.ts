import { execFile, spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

export interface EngineStatus {
  running: boolean;
  pid?: number;
  port?: number;
  startedAt?: string;
  healthy?: boolean;
}

function pidFile(dataDir: string): string {
  return path.join(dataDir, "openagent.pid");
}

function portFile(dataDir: string): string {
  return path.join(dataDir, "openagent.port");
}

function isPidAlive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

async function portHealthy(port: number): Promise<boolean> {
  try {
    const res = await fetch(`http://127.0.0.1:${port}/health`, {
      signal: AbortSignal.timeout(5000),
    });
    return res.ok;
  } catch {
    return false;
  }
}

export function writePidFile(dataDir: string, pid: number, port: number): void {
  fs.mkdirSync(dataDir, { recursive: true });
  fs.writeFileSync(
    pidFile(dataDir),
    JSON.stringify({ pid, port, startedAt: new Date().toISOString() }),
  );
  fs.writeFileSync(portFile(dataDir), String(port));
}

export function clearPidFile(dataDir: string): void {
  for (const f of [pidFile(dataDir), portFile(dataDir)]) {
    try {
      fs.rmSync(f, { force: true });
    } catch {
      // ignore
    }
  }
}

export function readPidFile(
  dataDir: string,
): { pid: number; port: number; startedAt: string } | null {
  try {
    if (!fs.existsSync(pidFile(dataDir))) return null;
    return JSON.parse(fs.readFileSync(pidFile(dataDir), "utf8")) as {
      pid: number;
      port: number;
      startedAt: string;
    };
  } catch {
    return null;
  }
}

export async function engineStatus(dataDir: string): Promise<EngineStatus> {
  const rec = readPidFile(dataDir);
  if (!rec) return { running: false };
  if (!isPidAlive(rec.pid)) {
    clearPidFile(dataDir);
    return { running: false };
  }
  const healthy = await portHealthy(rec.port);
  return {
    running: true,
    pid: rec.pid,
    port: rec.port,
    startedAt: rec.startedAt,
    healthy,
  };
}

/** Stop a supervised engine (whole process tree on Windows). */
export async function stopEngine(
  dataDir: string,
  timeoutMs = 15000,
): Promise<boolean> {
  const rec = readPidFile(dataDir);
  if (!rec) return false;
  if (!isPidAlive(rec.pid)) {
    clearPidFile(dataDir);
    return false;
  }
  try {
    if (process.platform === "win32") {
      await new Promise<void>((resolve) => {
        execFile("taskkill", ["/PID", String(rec.pid), "/T", "/F"], () =>
          resolve(),
        );
      });
    } else {
      try {
        process.kill(-rec.pid, "SIGTERM");
      } catch {
        try {
          process.kill(rec.pid, "SIGTERM");
        } catch {
          // already dead
        }
      }
    }
    const deadline = Date.now() + timeoutMs;
    while (isPidAlive(rec.pid) && Date.now() < deadline) {
      await new Promise((r) => setTimeout(r, 250));
    }
  } finally {
    clearPidFile(dataDir);
  }
  return !isPidAlive(rec.pid);
}

/** Open the dashboard in the default browser (best effort). */
export function openDashboard(port: number): void {
  const url = `http://localhost:${port}`;
  try {
    if (process.platform === "win32") {
      spawn("cmd", ["/d", "/s", "/c", "start", "", url], {
        stdio: "ignore",
        detached: true,
        shell: false,
      }).unref();
    } else if (process.platform === "darwin") {
      spawn("open", [url], { stdio: "ignore", detached: true }).unref();
    } else {
      spawn("xdg-open", [url], { stdio: "ignore", detached: true }).unref();
    }
  } catch {
    // opening a browser is best-effort
  }
}
