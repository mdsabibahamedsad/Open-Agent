#!/usr/bin/env node
/*
 * OpenAgent doctor — beginner-friendly environment diagnostics.
 * Read-only: never modifies files, never prints secret values.
 * Exit code 0 when ready, 1 when something needs attention.
 *
 * Usage:
 *   node scripts/doctor.mjs [--json]
 */
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const JSON_OUT = process.argv.includes("--json");
const results = [];

function record(name, status, detail, fix) {
  results.push({ name, status, detail, fix: fix ?? null });
}

function run(cmd, cmdArgs) {
  try {
    return execFileSync(cmd, cmdArgs, {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"],
    }).trim();
  } catch {
    // fall through to platform fallbacks
  }
  if (process.platform === "win32") {
    // PowerShell .ps1 shims (pnpm.ps1, npm.ps1) are not directly executable.
    for (const shell of ["powershell", "pwsh"]) {
      try {
        const quoted = [cmd, ...cmdArgs]
          .map((a) => `"${String(a).replace(/"/g, '""')}"`)
          .join(" ");
        return execFileSync(
          shell,
          ["-NoProfile", "-NonInteractive", "-Command", `& ${quoted}`],
          { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] },
        ).trim();
      } catch {
        // try next shell
      }
    }
  }
  return null;
}

function versionAtLeast(actual, major, minor = 0) {
  const m = String(actual ?? "").match(/(\d+)\.(\d+)/);
  if (!m) return false;
  return (
    Number(m[1]) > major || (Number(m[1]) === major && Number(m[2]) >= minor)
  );
}

// --- static checks ---------------------------------------------------------

record(
  "Operating System",
  "pass",
  `${os.type()} ${os.release()} (${os.arch()})`,
);

const nodeVersion = process.versions.node;
record(
  "Node.js",
  versionAtLeast(nodeVersion, 20) ? "pass" : "fail",
  nodeVersion,
  "Install Node.js 20 LTS: https://nodejs.org/en/download",
);

const pnpmVersion = run("pnpm", ["--version"]);
record(
  "pnpm",
  pnpmVersion ? "pass" : "fail",
  pnpmVersion ?? "not found",
  "Install pnpm 8.15+: https://pnpm.io/installation (or run `corepack enable`)",
);

const npmVersion = run("npm", ["--version"]);
record(
  "npm",
  npmVersion ? "pass" : "warn",
  npmVersion ?? "not found",
  npmVersion
    ? null
    : "Optional: https://nodejs.org/en/download (pnpm remains canonical)",
);

const pythonVersion =
  run("python", ["--version"]) ??
  run("python3", ["--version"]) ??
  run("py", ["--version"]) ??
  run(path.join(ROOT, "apps", "api", ".venv", "Scripts", "python.exe"), [
    "--version",
  ]);
record(
  "Python",
  pythonVersion && versionAtLeast(pythonVersion, 3, 11)
    ? "pass"
    : pythonVersion
      ? "warn"
      : "fail",
  pythonVersion ?? "not found",
  "Install Python 3.11+: https://www.python.org/downloads/",
);

const gitVersion = run("git", ["--version"]);
record(
  "Git",
  gitVersion ? "pass" : "fail",
  gitVersion ?? "not found",
  "Install Git: https://git-scm.com/downloads",
);

const dockerVersion = run("docker", ["--version"]);
record(
  "Docker",
  dockerVersion ? "pass" : "warn",
  dockerVersion ?? "not found",
  dockerVersion
    ? null
    : "Install Docker Desktop: https://docs.docker.com/get-docker/ — or use non-Docker mode (docs/getting-started/non-docker.md)",
);

let composeVersion = null;
if (dockerVersion) {
  composeVersion = run("docker", ["compose", "version"]);
}
record(
  "Docker Compose",
  dockerVersion ? (composeVersion ? "pass" : "fail") : "warn",
  composeVersion ?? (dockerVersion ? "not found" : "skipped (no Docker)"),
  "Use Docker Desktop or Compose v2: https://docs.docker.com/compose/install/",
);

// --- project checks --------------------------------------------------------

record(
  "Project root",
  existsSync(path.join(ROOT, "pnpm-workspace.yaml")) ? "pass" : "fail",
  existsSync(path.join(ROOT, "pnpm-workspace.yaml"))
    ? "pnpm-workspace.yaml found"
    : "not an OpenAgent checkout",
  "Clone https://github.com/mdsabibahamedsad/Open-Agent.git",
);

record(
  "JS dependencies",
  existsSync(path.join(ROOT, "node_modules")) ? "pass" : "warn",
  existsSync(path.join(ROOT, "node_modules"))
    ? "node_modules present"
    : "not installed",
  "Run `pnpm setup` (or `pnpm install`)",
);

const envPath = path.join(ROOT, ".env");
if (!existsSync(envPath)) {
  record(
    "Environment (.env)",
    "warn",
    "not found",
    "Run `pnpm setup` to create .env from .env.example",
  );
} else {
  const vars = {};
  for (const line of readFileSync(envPath, "utf8").split("\n")) {
    const t = line.trim();
    if (!t || t.startsWith("#")) continue;
    const eq = t.indexOf("=");
    if (eq > 0) vars[t.slice(0, eq).trim()] = t.slice(eq + 1).trim();
  }
  const missing = [
    "DATABASE_URL",
    "REDIS_URL",
    "SECRET_KEY",
    "ENCRYPTION_KEY",
  ].filter((k) => !vars[k]);
  const shortSecrets = ["SECRET_KEY", "ENCRYPTION_KEY"].filter(
    (k) => vars[k] && vars[k].length < 32,
  );
  if (missing.length > 0 || shortSecrets.length > 0) {
    const problems = [
      ...missing.map((k) => `missing ${k}`),
      ...shortSecrets.map((k) => `${k} too short`),
    ];
    record(
      "Environment (.env)",
      "fail",
      `problems: ${problems.join(", ")}`,
      "Re-run `pnpm setup --force` or compare with .env.example (values are never printed here)",
    );
  } else {
    record(
      "Environment (.env)",
      "pass",
      "required variables present (values redacted)",
    );
  }
}

record(
  "Backend config",
  existsSync(path.join(ROOT, "apps", "api", "pyproject.toml"))
    ? "pass"
    : "fail",
  "apps/api/pyproject.toml",
  "Repository checkout looks incomplete — re-clone the repo",
);
record(
  "Frontend config",
  existsSync(path.join(ROOT, "apps", "web", "package.json")) ? "pass" : "fail",
  "apps/web/package.json",
  "Repository checkout looks incomplete — re-clone the repo",
);

const apiVenv = ["apps/api/.venv", "apps/api/venv"]
  .map((p) => path.join(ROOT, p))
  .find((p) => existsSync(p));
record(
  "Backend venv",
  apiVenv ? "pass" : "warn",
  apiVenv ?? "no virtualenv yet",
  'Create one: `python -m venv apps/api/.venv`, then install `pip install -e "apps/api[dev]"`',
);

// --- live checks (TCP + HTTP, short timeouts) -------------------------------

function tcpOpen(host, port, timeoutMs = 1500) {
  return new Promise((resolve) => {
    const socket = new net.Socket();
    let done = false;
    const finish = (ok) => {
      if (done) return;
      done = true;
      socket.destroy();
      resolve(ok);
    };
    socket.setTimeout(timeoutMs);
    socket.on("connect", () => finish(true));
    socket.on("timeout", () => finish(false));
    socket.on("error", () => finish(false));
    socket.connect(port, host);
  });
}

function httpStatus(url, timeoutMs = 2500) {
  return new Promise((resolve) => {
    const lib = url.startsWith("https")
      ? import("node:https")
      : import("node:http");
    lib
      .then((mod) => {
        const req = mod.get(url, { timeout: timeoutMs }, (res) => {
          res.resume();
          resolve(res.statusCode ?? 0);
        });
        req.on("timeout", () => {
          req.destroy();
          resolve(0);
        });
        req.on("error", () => resolve(0));
      })
      .catch(() => resolve(0));
  });
}

function parsePort(url, fallback) {
  try {
    const port = new URL(url).port;
    return port ? Number(port) : fallback;
  } catch {
    return fallback;
  }
}

let envVars = {};
try {
  if (existsSync(envPath)) {
    for (const line of readFileSync(envPath, "utf8").split("\n")) {
      const t = line.trim();
      if (!t || t.startsWith("#")) continue;
      const eq = t.indexOf("=");
      if (eq > 0) envVars[t.slice(0, eq).trim()] = t.slice(eq + 1).trim();
    }
  }
} catch {
  /* read-only best effort */
}

const apiPort = parsePort(envVars.API_URL || "http://localhost:8000", 8000);
const webPort = parsePort(envVars.WEB_URL || "http://localhost:3000", 3000);

const checks = await Promise.all([
  tcpOpen("127.0.0.1", 5432).then((ok) =>
    record(
      "PostgreSQL :5432",
      ok ? "pass" : "warn",
      ok ? "reachable" : "not reachable",
      "Start it: `pnpm infra:up` (Docker) or install PostgreSQL 15+: https://www.postgresql.org/download/",
    ),
  ),
  tcpOpen("127.0.0.1", 6379).then((ok) =>
    record(
      "Redis :6379",
      ok ? "pass" : "warn",
      ok ? "reachable" : "not reachable",
      "Start it: `pnpm infra:up` (Docker) or install Redis 7+: https://redis.io/docs/install/",
    ),
  ),
  tcpOpen("127.0.0.1", apiPort).then(async (ok) => {
    if (!ok) {
      record(
        `API :${apiPort}`,
        "warn",
        "not running",
        "Start it: `pnpm dev` (Docker) or `pnpm dev:api` (local)",
      );
      return;
    }
    const status = await httpStatus(
      `http://127.0.0.1:${apiPort}/api/v1/health`,
    );
    record(
      `API :${apiPort}`,
      status === 200 ? "pass" : "warn",
      status === 200 ? "/api/v1/health OK" : `health returned ${status}`,
    );
  }),
  tcpOpen("127.0.0.1", webPort).then((ok) =>
    record(
      `Web :${webPort}`,
      ok ? "pass" : "warn",
      ok ? "reachable" : "not running",
      "Start it: `pnpm dev` (Docker) or `pnpm dev:web` (local)",
    ),
  ),
]);

// --- report ----------------------------------------------------------------

if (JSON_OUT) {
  console.log(JSON.stringify({ results }, null, 2));
} else {
  console.log("\nOpenAgent Doctor\n");
  for (const r of results) {
    const icon = r.status === "pass" ? "✓" : r.status === "warn" ? "!" : "✗";
    console.log(`${icon} ${r.name}: ${r.detail}`);
    if (r.status !== "pass" && r.fix) console.log(`  → ${r.fix}`);
  }
  const failed = results.filter((r) => r.status === "fail").length;
  const warned = results.filter((r) => r.status === "warn").length;
  console.log(
    failed === 0
      ? warned === 0
        ? "\nOpenAgent is ready to run."
        : "\nOpenAgent can run with warnings above addressed as needed."
      : "\nOpenAgent is not ready yet — fix the ✗ items above, then re-run `pnpm doctor`.",
  );
}

process.exitCode = results.some((r) => r.status === "fail") ? 1 : 0;
