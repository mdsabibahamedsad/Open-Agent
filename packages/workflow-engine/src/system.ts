import { execFile } from "node:child_process";
import os from "node:os";
import net from "node:net";

export type HardwareProfile = "LOW" | "BALANCED" | "POWER";

export interface SystemInfo {
  os: string;
  platform: NodeJS.Platform;
  arch: string;
  cpuModel: string;
  cpuCount: number;
  totalRamMb: number;
  freeRamMb: number;
  diskFreeMb: number;
  diskTotalMb: number;
  gpu: string;
  internet: boolean;
  nodeVersion: string;
}

export interface ProfileRecommendation {
  profile: HardwareProfile;
  reason: string;
  model: string;
  modelLabel: string;
  maxWorkers: number;
  browserWorkers: number;
  concurrency: number;
  memoryEnabled: boolean;
}

function run(cmd: string, args: string[], timeout = 8000): Promise<string> {
  return new Promise((resolve) => {
    try {
      execFile(cmd, args, { timeout }, (err, stdout) => {
        resolve(err ? "" : String(stdout ?? ""));
      });
    } catch {
      resolve("");
    }
  });
}

async function diskInfo(): Promise<{ freeMb: number; totalMb: number }> {
  if (process.platform === "win32") {
    const drive = (process.cwd().slice(0, 2) || "C:").toUpperCase();
    const out = await run("cmd.exe", [
      "/d",
      "/s",
      "/c",
      `wmic logicaldisk where "DeviceID='${drive}'" get FreeSpace,Size /value`,
    ]);
    const free = Number((out.match(/FreeSpace=(\d+)/) ?? [])[1] ?? NaN);
    const total = Number((out.match(/Size=(\d+)/) ?? [])[1] ?? NaN);
    if (Number.isFinite(free) && Number.isFinite(total)) {
      return {
        freeMb: Math.floor(free / 1048576),
        totalMb: Math.floor(total / 1048576),
      };
    }
    // wmic is removed on newer Windows 11 — fall back to PowerShell.
    const ps = await run("powershell.exe", [
      "-NoProfile",
      "-Command",
      `(Get-PSDrive -Name '${drive.replace(":", "")}').Free; (Get-PSDrive -Name '${drive.replace(":", "")}').Used`,
    ]);
    const nums = ps
      .split(/[\r\n]+/)
      .map((s) => Number(s.trim()))
      .filter((n) => Number.isFinite(n));
    if (nums.length >= 2) {
      const [freeB, usedB] = nums as [number, number];
      return {
        freeMb: Math.floor((freeB as number) / 1048576),
        totalMb: Math.floor(((freeB as number) + (usedB as number)) / 1048576),
      };
    }
    return { freeMb: 0, totalMb: 0 };
  }
  const out = await run("df", ["-k", process.cwd()]);
  const line = out.trim().split("\n").pop() ?? "";
  const parts = line.split(/\s+/);
  if (parts.length >= 4) {
    const totalKb = Number(parts[1]);
    const availKb = Number(parts[3]);
    if (Number.isFinite(totalKb) && Number.isFinite(availKb)) {
      return {
        freeMb: Math.floor(availKb / 1024),
        totalMb: Math.floor(totalKb / 1024),
      };
    }
  }
  return { freeMb: 0, totalMb: 0 };
}

async function gpuInfo(): Promise<string> {
  if (process.platform === "win32") {
    const out = await run("cmd.exe", [
      "/d",
      "/s",
      "/c",
      "wmic path win32_VideoController get Name /value",
    ]);
    const names = [...out.matchAll(/Name=(.+)/g)]
      .map((m) => (m[1] ?? "").trim())
      .filter(Boolean);
    return names.join("; ") || "unknown";
  }
  if (process.platform === "darwin") {
    const out = await run("system_profiler", ["SPDisplaysDataType"]);
    const m = out.match(/Chipset Model:\s*(.+)/);
    return (m?.[1] ?? "unknown").trim();
  }
  const out = await run("lspci", []);
  const m = out.match(/(VGA|3D controller)[^\n]*/i);
  return (m?.[0] ?? "unknown").trim();
}

export async function checkInternet(timeoutMs = 8000): Promise<boolean> {
  const targets = ["https://registry.npmjs.org/", "https://ollama.com/"];
  for (const url of targets) {
    try {
      const ctrl = new AbortController();
      const t = setTimeout(() => ctrl.abort(), timeoutMs);
      const res = await fetch(url, { method: "HEAD", signal: ctrl.signal });
      clearTimeout(t);
      if (res.ok || (res.status >= 300 && res.status < 500)) return true;
    } catch {
      // try next target
    }
  }
  return false;
}

export async function getSystemInfo(): Promise<SystemInfo> {
  const cpus = os.cpus();
  const disk = await diskInfo();
  const [gpu, internet] = await Promise.all([gpuInfo(), checkInternet()]);
  return {
    os: `${os.type()} ${os.release()}`,
    platform: process.platform,
    arch: process.arch,
    cpuModel: cpus[0]?.model.trim() ?? "unknown",
    cpuCount: Math.max(cpus.length, 1),
    totalRamMb: Math.floor(os.totalmem() / 1048576),
    freeRamMb: Math.floor(os.freemem() / 1048576),
    diskFreeMb: disk.freeMb,
    diskTotalMb: disk.totalMb,
    gpu,
    internet,
    nodeVersion: process.version,
  };
}

/** Hardware-aware profile: LOW (4–8GB), BALANCED (8–16GB), POWER (16GB+). */
export function selectProfile(
  sys: Pick<SystemInfo, "totalRamMb" | "cpuCount">,
): ProfileRecommendation {
  const ramGb = sys.totalRamMb / 1024;
  if (ramGb < 8) {
    return {
      profile: "LOW",
      reason: `${ramGb.toFixed(1)} GB RAM detected — lightweight mode.`,
      model: "qwen2.5:1.5b",
      modelLabel: "Lightweight AI",
      maxWorkers: 2,
      browserWorkers: 1,
      concurrency: 2,
      memoryEnabled: true,
    };
  }
  if (ramGb < 16) {
    return {
      profile: "BALANCED",
      reason: `${ramGb.toFixed(1)} GB RAM detected — balanced mode.`,
      model: "qwen2.5:7b",
      modelLabel: "Balanced AI",
      maxWorkers: 4,
      browserWorkers: 2,
      concurrency: 4,
      memoryEnabled: true,
    };
  }
  return {
    profile: "POWER",
    reason: `${ramGb.toFixed(1)} GB RAM detected — power mode.`,
    model: "qwen2.5:14b",
    modelLabel: "Power AI",
    maxWorkers: 8,
    browserWorkers: 4,
    concurrency: 8,
    memoryEnabled: true,
  };
}

export function isPortFree(port: number, host = "127.0.0.1"): Promise<boolean> {
  return new Promise((resolve) => {
    const srv = net.createServer();
    srv.once("error", () => resolve(false));
    srv.once("listening", () => {
      srv.close(() => resolve(true));
    });
    srv.listen(port, host);
  });
}

/** Never crash on an occupied port — scan upward for a free one. */
export async function findFreePort(
  preferred: number,
  maxTries = 20,
): Promise<number> {
  for (let i = 0; i < maxTries; i++) {
    const port = preferred + i;
    if (await isPortFree(port)) return port;
  }
  throw new Error(
    `no free port found in range ${preferred}-${preferred + maxTries - 1}`,
  );
}

export interface SystemCheckItem {
  name: string;
  ok: boolean;
  detail: string;
  blocking: boolean;
}

export async function runSystemCheck(
  sys?: SystemInfo,
): Promise<SystemCheckItem[]> {
  const s = sys ?? (await getSystemInfo());
  const items: SystemCheckItem[] = [];
  const isWin = s.platform === "win32";
  items.push({
    name: "OS",
    ok: isWin ? /10|11/.test(s.os) || true : true,
    detail: s.os,
    blocking: false,
  });
  items.push({
    name: "CPU",
    ok: s.arch === "x64" || s.arch === "arm64",
    detail: `${s.cpuCount} cores (${s.cpuModel.slice(0, 60)})`,
    blocking: false,
  });
  items.push({
    name: "RAM",
    ok: s.totalRamMb >= 4096,
    detail:
      s.totalRamMb >= 8192
        ? `${(s.totalRamMb / 1024).toFixed(1)} GB`
        : `${(s.totalRamMb / 1024).toFixed(1)} GB — lightweight mode recommended`,
    blocking: false,
  });
  items.push({
    name: "Storage",
    ok: s.diskFreeMb === 0 || s.diskFreeMb >= 2048,
    detail:
      s.diskFreeMb === 0
        ? "could not determine free space"
        : `${(s.diskFreeMb / 1024).toFixed(1)} GB free`,
    blocking: false,
  });
  items.push({
    name: "Internet",
    ok: true,
    detail: s.internet
      ? "available"
      : "unavailable — offline-capable components only",
    blocking: false,
  });
  items.push({
    name: "Port 5678",
    ok: true,
    detail: (await isPortFree(5678))
      ? "5678 available"
      : "5678 occupied — a free port will be selected automatically",
    blocking: false,
  });
  return items;
}
