import fs from "node:fs";
import path from "node:path";
import { runWorkflow } from "./engine.js";
import { saveExecution } from "./server.js";
import { FileCredentialResolver } from "./credentials.js";
import { FileMemoryManager } from "./memory.js";
import { ToolRegistry } from "./tools.js";
import type { WorkflowDefinition } from "./types.js";

export interface ScheduleEntry {
  id: string;
  workflowId: string;
  cron?: string;
  intervalMs?: number;
  timezone?: string;
  enabled: boolean;
  createdAt: string;
}

function schedulesFile(projectDir: string): string {
  return path.join(projectDir, ".openagent", "schedules", "schedules.json");
}

export function listSchedules(projectDir: string): ScheduleEntry[] {
  const file = schedulesFile(projectDir);
  try {
    if (!fs.existsSync(file)) return [];
    return JSON.parse(fs.readFileSync(file, "utf8")) as ScheduleEntry[];
  } catch {
    return [];
  }
}

export function saveSchedules(
  projectDir: string,
  entries: ScheduleEntry[],
): void {
  fs.mkdirSync(path.dirname(schedulesFile(projectDir)), { recursive: true });
  fs.writeFileSync(schedulesFile(projectDir), JSON.stringify(entries, null, 2));
}

export function parseIntervalToMs(input: string): number {
  const m = input
    .trim()
    .toLowerCase()
    .match(
      /^(\d+)\s*(s|sec|secs|second|seconds|m|min|mins|minute|minutes|h|hr|hrs|hour|hours|d|day|days)?$/,
    );
  if (!m)
    throw new Error(`cannot parse interval '${input}' (try '5m', '1h', '30s')`);
  const n = Number(m[1]);
  const unit = m[2] ?? "m";
  if (unit.startsWith("s")) return n * 1000;
  if (unit.startsWith("m")) return n * 60 * 1000;
  if (unit.startsWith("h")) return n * 3600 * 1000;
  return n * 86400 * 1000;
}

/** Minimal cron matcher supporting `*` and `*\/n` plus exact minute/hour fields. */
export function cronDue(cron: string, now = new Date()): boolean {
  const parts = cron.trim().split(/\s+/);
  if (parts.length !== 5) return false;
  const [min, hour] = parts as [string, string, string, string, string];
  const match = (expr: string, value: number): boolean => {
    if (expr === "*") return true;
    const step = expr.match(/^\*\/(\d+)$/);
    if (step) return value % Number(step[1]) === 0;
    if (expr.includes(",")) return expr.split(",").map(Number).includes(value);
    return Number(expr) === value;
  };
  return match(min, now.getMinutes()) && match(hour, now.getHours());
}

/** Starts in-process scheduling loop. Returns a stop function. */
export function startScheduler(
  projectDir: string,
  opts?: {
    tickMs?: number;
    onRun?: (entry: ScheduleEntry, workflowId: string) => void;
  },
): () => void {
  const tickMs = opts?.tickMs ?? 30_000;
  let stopped = false;
  const firedMinute = new Map<string, string>();
  const timer = setInterval(() => {
    if (stopped) return;
    void (async () => {
      const entries = listSchedules(projectDir).filter((e) => e.enabled);
      for (const entry of entries) {
        let due = false;
        if (entry.cron) {
          const key = `${entry.id}:${new Date().toISOString().slice(0, 16)}`;
          if (!firedMinute.has(key) && cronDue(entry.cron)) {
            firedMinute.set(key, "1");
            due = true;
          }
        } else if (entry.intervalMs) {
          const lastKey = `last:${entry.id}`;
          void lastKey;
          due = true; // interval handled via per-entry timers below
        }
        if (!due) continue;
        await fireSchedule(projectDir, entry);
        opts?.onRun?.(entry, entry.workflowId);
      }
    })();
  }, tickMs);
  // Interval-based entries get dedicated timers.
  const intervalTimers: NodeJS.Timeout[] = [];
  for (const entry of listSchedules(projectDir).filter(
    (e) => e.enabled && e.intervalMs,
  )) {
    intervalTimers.push(
      setInterval(
        () => {
          if (stopped) return;
          void fireSchedule(projectDir, entry).then(() =>
            opts?.onRun?.(entry, entry.workflowId),
          );
        },
        Math.max(entry.intervalMs as number, 10_000),
      ),
    );
  }
  void timer;
  return () => {
    stopped = true;
    clearInterval(timer);
    for (const t of intervalTimers) clearInterval(t);
  };
}

async function fireSchedule(
  projectDir: string,
  entry: ScheduleEntry,
): Promise<void> {
  const file = path.join(
    projectDir,
    ".openagent",
    "workflows",
    `${entry.workflowId}.json`,
  );
  if (!fs.existsSync(file)) return;
  const def = JSON.parse(fs.readFileSync(file, "utf8")) as WorkflowDefinition;
  const rec = await runWorkflow(def, {
    input: { scheduleId: entry.id, tick: new Date().toISOString() },
    credentials: new FileCredentialResolver(projectDir),
    memory: new FileMemoryManager(projectDir),
    tools: new ToolRegistry(),
    projectDir,
  });
  saveExecution(projectDir, rec);
}
