#!/usr/bin/env node
/*
 * OpenAgent cross-platform setup.
 * - Never overwrites an existing .env without --force.
 * - Never prints secret values.
 * - Only creates files; never installs system software.
 *
 * Usage:
 *   node scripts/setup.mjs [--force] [--yes]
 */
import { randomBytes } from "node:crypto";
import { existsSync, copyFileSync, readFileSync, writeFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const args = new Set(process.argv.slice(2));
const FORCE = args.has("--force");

function run(cmd, cmdArgs, opts = {}) {
  try {
    return execFileSync(cmd, cmdArgs, {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"],
      ...opts,
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
          { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"], ...opts },
        ).trim();
      } catch {
        // try next shell
      }
    }
  }
  return null;
}

function fail(message, hint) {
  console.error(`\n✗ ${message}`);
  if (hint) console.error(`  ${hint}`);
  process.exitCode = 1;
}

function checkNode() {
  const major = Number(process.versions.node.split(".")[0]);
  if (Number.isNaN(major) || major < 20) {
    fail(
      `Node.js ${process.versions.node} is below the required >=20.`,
      "Install Node.js 20 LTS: https://nodejs.org/en/download",
    );
    return false;
  }
  console.log(`✓ Node.js ${process.versions.node}`);
  return true;
}

function checkPackageManager() {
  const pnpm = run("pnpm", ["--version"]);
  if (!pnpm) {
    fail(
      "pnpm was not found.",
      "Install pnpm 8.15+: https://pnpm.io/installation (or `corepack enable`)",
    );
    return false;
  }
  console.log(`✓ pnpm ${pnpm}`);
  return true;
}

function checkPython() {
  const venvCandidates = [
    "apps/api/.venv/Scripts/python.exe",
    "apps/api/.venv/bin/python",
  ].map((p) => path.join(ROOT, p));
  const venv = venvCandidates.find((p) => existsSync(p));
  const out =
    run("python", ["--version"]) ??
    run("python3", ["--version"]) ??
    run("py", ["--version"]) ??
    (venv ? run(venv, ["--version"]) : null);
  if (!out) {
    console.log(
      "! Python not found on PATH — backend/worker setup will be skipped.",
    );
    console.log("  Install Python 3.11+: https://www.python.org/downloads/");
    return false;
  }
  const match = out.match(/(\d+)\.(\d+)/);
  const ok =
    match !== null &&
    (Number(match[1]) > 3 ||
      (Number(match[1]) === 3 && Number(match[2]) >= 11));
  console.log(`${ok ? "✓" : "!"} ${out}${ok ? "" : " (3.11+ recommended)"}`);
  return ok;
}

function ensureDeps() {
  if (existsSync(path.join(ROOT, "node_modules"))) {
    console.log(
      "✓ JavaScript dependencies already installed (node_modules present).",
    );
    return;
  }
  console.log("Installing JavaScript dependencies (pnpm install)…");
  try {
    execFileSync("pnpm", ["install"], { cwd: ROOT, stdio: "inherit" });
  } catch {
    fail(
      "pnpm install failed.",
      "See the output above; verify network access and Node/pnpm versions, then re-run.",
    );
  }
}

function randomHex(bytes) {
  return randomBytes(bytes).toString("hex");
}

function ensureEnv() {
  const envPath = path.join(ROOT, ".env");
  const examplePath = path.join(ROOT, ".env.example");
  if (existsSync(envPath) && !FORCE) {
    console.log(
      "✓ .env already exists — leaving it untouched (use --force to regenerate).",
    );
    return validateEnv(envPath);
  }
  if (!existsSync(examplePath)) {
    fail(".env.example is missing; cannot create .env.");
    return false;
  }
  let content = readFileSync(examplePath, "utf8");
  const replacements = {
    "your-secret-key-here-min-32-chars": randomHex(32),
    "your-encryption-key-here-min-32-chars": randomHex(32),
  };
  for (const [placeholder, value] of Object.entries(replacements)) {
    content = content.split(placeholder).join(value);
  }
  writeFileSync(envPath, content, { mode: 0o600 });
  console.log(
    "✓ Created .env from .env.example with fresh development secrets.",
  );
  return validateEnv(envPath);
}

function parseEnvFile(filePath) {
  const vars = {};
  for (const line of readFileSync(filePath, "utf8").split("\n")) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const eq = trimmed.indexOf("=");
    if (eq > 0)
      vars[trimmed.slice(0, eq).trim()] = trimmed.slice(eq + 1).trim();
  }
  return vars;
}

function validateEnv(envPath) {
  const vars = parseEnvFile(envPath);
  const required = [
    "DATABASE_URL",
    "REDIS_URL",
    "SECRET_KEY",
    "ENCRYPTION_KEY",
  ];
  let ok = true;
  for (const key of required) {
    const value = vars[key] ?? "";
    if (!value) {
      console.error(`✗ .env is missing ${key}.`);
      ok = false;
    } else if (
      (key === "SECRET_KEY" || key === "ENCRYPTION_KEY") &&
      value.length < 32
    ) {
      console.error(`✗ ${key} must be at least 32 characters.`);
      ok = false;
    }
  }
  if (ok) console.log("✓ .env contains all required variables.");
  else process.exitCode = 1;
  return ok;
}

const nodeOk = checkNode();
const pnpmOk = checkPackageManager();
checkPython();
if (!nodeOk || !pnpmOk) process.exit(1);
ensureDeps();
if (!ensureEnv()) process.exit(1);

console.log(
  [
    "",
    "OpenAgent setup complete.",
    "",
    "Next steps:",
    "  pnpm doctor        # verify your environment",
    "  pnpm dev           # full stack via Docker (recommended)",
    "  pnpm dev:local     # infrastructure in Docker, code on your machine",
    "  pnpm infra:up      # Postgres + Redis only (hybrid mode)",
  ].join("\n"),
);
