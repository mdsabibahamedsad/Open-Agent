#!/usr/bin/env node
/*
 * OpenAgent local process orchestrator (cross-platform).
 * Spawns web / api / worker with prefixed logs and clean Ctrl+C shutdown.
 *
 * Usage:
 *   node scripts/dev.mjs [--only=web|api|worker] [--no-banner]
 */
import { spawn } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const onlyArg = process.argv.find((a) => a.startsWith("--only="));
const ONLY = onlyArg
  ? onlyArg.split("=")[1].split(",")
  : ["web", "api", "worker"];
const NO_BANNER = process.argv.includes("--no-banner");

function envPorts() {
  const vars = {};
  const envPath = path.join(ROOT, ".env");
  try {
    for (const line of readFileSync(envPath, "utf8").split("\n")) {
      const t = line.trim();
      if (!t || t.startsWith("#")) continue;
      const eq = t.indexOf("=");
      if (eq > 0) vars[t.slice(0, eq).trim()] = t.slice(eq + 1).trim();
    }
  } catch {
    /* defaults below */
  }
  const portOf = (url, fallback) => {
    try {
      const p = new URL(url).port;
      return p ? Number(p) : fallback;
    } catch {
      return fallback;
    }
  };
  return {
    web: portOf(vars.WEB_URL || "http://localhost:3000", 3000),
    api: portOf(vars.API_URL || "http://localhost:8000", 8000),
  };
}

function apiPython() {
  const candidates = [
    path.join(ROOT, "apps", "api", ".venv", "Scripts", "python.exe"),
    path.join(ROOT, "apps", "api", ".venv", "bin", "python"),
  ];
  for (const c of candidates) {
    if (existsSync(c)) return c;
  }
  return "python";
}

function prefix(tag, color) {
  const colors = { web: "\x1b[36m", api: "\x1b[32m", worker: "\x1b[35m" };
  const reset = "\x1b[0m";
  const useColor = process.stdout.isTTY && !process.env.NO_COLOR;
  const label = `[${tag}]`;
  return (line) =>
    `${useColor ? (colors[tag] ?? "") + label + reset : label} ${line}`;
}

const children = [];
function startService(tag, cmd, cmdArgs, cwd, extraEnv = {}) {
  const emit = prefix(tag);
  let child;
  try {
    child = spawn(cmd, cmdArgs, {
      cwd,
      env: { ...process.env, ...extraEnv, FORCE_COLOR: "1" },
      stdio: ["ignore", "pipe", "pipe"],
      shell: process.platform === "win32",
    });
  } catch (err) {
    console.error(emit(`failed to start: ${err.message}`));
    process.exitCode = 1;
    return;
  }
  children.push({ tag, child });
  child.stdout.on("data", (d) => {
    for (const line of String(d).split("\n")) {
      if (line.trim()) console.log(emit(line));
    }
  });
  child.stderr.on("data", (d) => {
    for (const line of String(d).split("\n")) {
      if (line.trim()) console.error(emit(line));
    }
  });
  child.on("exit", (code, signal) => {
    console.error(
      emit(`exited (code=${code ?? "?"}, signal=${signal ?? "?"})`),
    );
  });
  console.log(emit(`started (pid ${child.pid})`));
}

function shutdown(signal) {
  console.log(`\nStopping OpenAgent (${signal})…`);
  for (const { tag, child } of children) {
    try {
      if (process.platform === "win32") {
        child.kill("SIGTERM");
      } else {
        child.kill("SIGTERM");
      }
    } catch {
      /* already gone */
    }
  }
  const deadline = setTimeout(() => {
    for (const { child } of children) {
      try {
        child.kill("SIGKILL");
      } catch {
        /* already gone */
      }
    }
    process.exit(0);
  }, 8000);
  deadline.unref?.();
}
process.on("SIGINT", () => shutdown("SIGINT"));
process.on("SIGTERM", () => shutdown("SIGTERM"));

const ports = envPorts();
if (!NO_BANNER) {
  console.log(
    [
      "",
      "╔══════════════════════════════════════════════╗",
      "║                 OpenAgent                    ║",
      "║         Open-Source AI Workforce OS          ║",
      "╚══════════════════════════════════════════════╝",
      "",
      `Web:      http://localhost:${ports.web}`,
      `API:      http://localhost:${ports.api}`,
      `API Docs: http://localhost:${ports.api}/docs`,
      `Health:   http://localhost:${ports.api}/api/v1/health`,
      "",
      "Environment: development (local processes)",
      "Press Ctrl+C to stop.",
      "",
    ].join("\n"),
  );
}

const python = apiPython();
if (ONLY.includes("web")) {
  startService("web", "pnpm", ["--filter", "@openagent/web", "dev"], ROOT);
}
if (ONLY.includes("api")) {
  startService(
    "api",
    python,
    [
      "-m",
      "uvicorn",
      "openagent.main:app",
      "--reload",
      "--host",
      "0.0.0.0",
      "--port",
      String(ports.api),
    ],
    path.join(ROOT, "apps", "api"),
    { PYTHONPATH: path.join(ROOT, "apps", "api", "src") },
  );
}
if (ONLY.includes("worker")) {
  startService(
    "worker",
    python,
    ["-m", "worker.main"],
    path.join(ROOT, "apps", "worker"),
    { PYTHONPATH: path.join(ROOT, "apps", "worker", "src") },
  );
}

if (children.length === 0) {
  console.error("Nothing to start. Use --only=web|api|worker.");
  process.exit(1);
}
