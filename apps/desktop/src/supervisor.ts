import { spawn, type ChildProcess } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { appendRotatingLog, findFreePort } from "@openagent/workflow-engine";
import {
  clearPidFile,
  engineStatus,
  openDashboard,
  writePidFile,
} from "./lifecycle.js";

export type ServiceState =
  "HEALTHY" | "STARTING" | "DEGRADED" | "FAILED" | "RESTARTING" | "STOPPED";

export interface SupervisorOptions {
  /** Directory holding openagent.pid / crash counter / logs. */
  dataDir: string;
  /** Project dir containing .openagent/. */
  projectDir: string;
  preferredPort?: number;
  safeMode?: boolean;
  openBrowser?: boolean;
  /** How to launch the engine, e.g. { cmd: process.execPath, args: [cliBin, "start", ...] } */
  engineCommand: (
    port: number,
    safe: boolean,
  ) => { cmd: string; args: string[] };
  onEvent?: (msg: string) => void;
  healthIntervalMs?: number;
  maxRestarts?: number;
}

interface CrashRecord {
  consecutiveCrashes: number;
  lastCrashAt?: string;
  recoveryMode: boolean;
}

function crashFile(dataDir: string): string {
  return path.join(dataDir, "supervisor-crashes.json");
}

function readCrashes(dataDir: string): CrashRecord {
  try {
    if (fs.existsSync(crashFile(dataDir))) {
      return JSON.parse(
        fs.readFileSync(crashFile(dataDir), "utf8"),
      ) as CrashRecord;
    }
  } catch {
    // start fresh
  }
  return { consecutiveCrashes: 0, recoveryMode: false };
}

function writeCrashes(dataDir: string, rec: CrashRecord): void {
  try {
    fs.mkdirSync(dataDir, { recursive: true });
    fs.writeFileSync(crashFile(dataDir), JSON.stringify(rec, null, 2));
  } catch {
    // best effort
  }
}

function log(dataDir: string, line: string): void {
  appendRotatingLog(path.join(dataDir, "logs"), "supervisor", line);
}

/**
 * Local service supervisor. Owns exactly one engine child process, polls
 * /health, and restarts on crash with backoff. After repeated crashes it
 * enters recovery (safe) mode instead of crash-looping.
 */
export class Supervisor {
  private child: ChildProcess | null = null;
  private timer: NodeJS.Timeout | null = null;
  private stopped = false;
  private restarts = 0;
  state: ServiceState = "STOPPED";
  port = 0;

  constructor(private opts: SupervisorOptions) {}

  private emit(msg: string): void {
    log(this.opts.dataDir, msg);
    try {
      this.opts.onEvent?.(msg);
    } catch {
      // listener errors must not break supervision
    }
  }

  async start(): Promise<{ port: number; recovered: boolean }> {
    this.stopped = false;
    const crashes = readCrashes(this.opts.dataDir);
    const recovered = crashes.recoveryMode || this.opts.safeMode === true;
    this.port = await findFreePort(this.opts.preferredPort ?? 5678);
    this.spawn(this.port, recovered);
    this.emit(
      `engine starting on port ${this.port}${recovered ? " (safe mode)" : ""}`,
    );
    if (this.opts.openBrowser !== false) {
      setTimeout(() => openDashboard(this.port), 2500);
    }
    this.timer = setInterval(
      () => void this.healthTick(),
      this.opts.healthIntervalMs ?? 15000,
    );
    if (this.timer.unref) this.timer.unref();
    return { port: this.port, recovered };
  }

  private spawn(port: number, safe: boolean): void {
    this.state = this.restarts > 0 ? "RESTARTING" : "STARTING";
    const { cmd, args } = this.opts.engineCommand(port, safe);
    const child = spawn(cmd, args, {
      cwd: this.opts.projectDir,
      stdio: ["ignore", "pipe", "pipe"],
      detached: process.platform !== "win32",
      shell: false,
      env: {
        ...process.env,
        OPENAGENT_SUPERVISED: "1",
        OPENAGENT_SAFE_MODE: safe ? "1" : "",
      },
    });
    this.child = child;
    writePidFile(this.opts.dataDir, child.pid ?? 0, port);
    child.stdout?.on("data", (c: Buffer) =>
      log(this.opts.dataDir, `[engine] ${String(c).trimEnd()}`),
    );
    child.stderr?.on("data", (c: Buffer) =>
      log(this.opts.dataDir, `[engine:err] ${String(c).trimEnd()}`),
    );
    child.on("exit", (code) => void this.onExit(code));
  }

  private async onExit(code: number | null): Promise<void> {
    clearPidFile(this.opts.dataDir);
    this.child = null;
    if (this.stopped) {
      this.state = "STOPPED";
      return;
    }
    this.emit(`engine exited (code ${code}) — restarting`);
    const crashes = readCrashes(this.opts.dataDir);
    crashes.consecutiveCrashes += 1;
    crashes.lastCrashAt = new Date().toISOString();
    const max = this.opts.maxRestarts ?? 5;
    if (crashes.consecutiveCrashes >= max) {
      crashes.recoveryMode = true;
      writeCrashes(this.opts.dataDir, crashes);
      this.state = "FAILED";
      this.emit("engine crashed repeatedly — entering recovery (safe) mode");
      this.restarts = 0;
      this.spawn(this.port, true);
      return;
    }
    writeCrashes(this.opts.dataDir, crashes);
    this.restarts += 1;
    this.state = "RESTARTING";
    const backoff = Math.min(2000 * this.restarts, 15000);
    await new Promise((r) => setTimeout(r, backoff));
    if (!this.stopped) this.spawn(this.port, false);
  }

  private async healthTick(): Promise<void> {
    if (this.stopped || !this.child) return;
    const st = await engineStatus(this.opts.dataDir);
    if (!st.running) {
      this.state = "DEGRADED";
      return;
    }
    if (st.healthy) {
      this.state = "HEALTHY";
      const crashes = readCrashes(this.opts.dataDir);
      if (crashes.consecutiveCrashes > 0) {
        writeCrashes(this.opts.dataDir, {
          consecutiveCrashes: 0,
          recoveryMode: false,
        });
      }
    } else {
      this.state = this.state === "STARTING" ? "STARTING" : "DEGRADED";
    }
  }

  /** Clear crash history (used after successful repair / update). */
  clearRecovery(): void {
    writeCrashes(this.opts.dataDir, {
      consecutiveCrashes: 0,
      recoveryMode: false,
    });
  }

  inRecovery(): boolean {
    return readCrashes(this.opts.dataDir).recoveryMode;
  }

  async stop(): Promise<void> {
    this.stopped = true;
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
    this.child?.removeAllListeners("exit");
    this.child = null;
    const { stopEngine } = await import("./lifecycle.js");
    await stopEngine(this.opts.dataDir);
    this.state = "STOPPED";
  }
}
