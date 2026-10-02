#!/usr/bin/env node
/*
 * OpenAgent database commands (cross-platform).
 * Alembic is authoritative for the backend schema. Prisma files in
 * packages/database remain for companion tooling only.
 *
 * Usage:
 *   node scripts/db.mjs migrate|rollback|seed|setup|reset [--yes]
 *
 * Safety:
 *   - `reset` requires --yes AND refuses when OPENAGENT_ENV=production.
 *   - Never touches production without explicit confirmation.
 */
import { spawnSync, execFileSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import readline from "node:readline";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const API_DIR = path.join(ROOT, "apps", "api");
const [command, ...rest] = process.argv.slice(2);
const YES = rest.includes("--yes");

function apiPython() {
  const candidates = [
    path.join(API_DIR, ".venv", "Scripts", "python.exe"),
    path.join(API_DIR, ".venv", "bin", "python"),
  ];
  for (const c of candidates) {
    if (existsSync(c)) return c;
  }
  return null;
}

function envOf() {
  const vars = { ...process.env };
  const envPath = path.join(ROOT, ".env");
  try {
    for (const line of readFileSync(envPath, "utf8").split("\n")) {
      const t = line.trim();
      if (!t || t.startsWith("#")) continue;
      const eq = t.indexOf("=");
      if (eq > 0 && !(t.slice(0, eq).trim() in vars)) {
        vars[t.slice(0, eq).trim()] = t.slice(eq + 1).trim();
      }
    }
  } catch {
    /* .env optional here; alembic will error clearly */
  }
  vars.PYTHONPATH =
    path.join(API_DIR, "src") +
    (process.platform === "win32" ? ";" : ":") +
    (vars.PYTHONPATH ?? "");
  return vars;
}

function runAlembic(args) {
  const python = apiPython();
  if (!python) {
    console.error("✗ Backend virtualenv not found (apps/api/.venv).");
    console.error("  Create it: `python -m venv apps/api/.venv`");
    console.error(
      '  Then install: `apps/api/.venv/Scripts/python -m pip install -e "apps/api[dev]"`',
    );
    process.exit(1);
  }
  const result = spawnSync(python, ["-m", "alembic", ...args], {
    cwd: API_DIR,
    env: envOf(),
    stdio: "inherit",
  });
  if (result.status !== 0) {
    console.error(
      `✗ alembic ${args.join(" ")} failed (exit ${result.status}).`,
    );
    console.error(
      "  Is PostgreSQL reachable? Try `pnpm infra:up`, then `pnpm doctor`.",
    );
    process.exit(result.status ?? 1);
  }
}

function runSeed() {
  const python = apiPython();
  if (!python) {
    console.error("✗ Backend virtualenv not found (apps/api/.venv).");
    process.exit(1);
  }
  const seedScript = path.join(ROOT, "scripts", "seed_dev.py");
  if (!existsSync(seedScript)) {
    console.error("✗ scripts/seed_dev.py not found.");
    process.exit(1);
  }
  const result = spawnSync(python, [seedScript], {
    cwd: API_DIR,
    env: envOf(),
    stdio: "inherit",
  });
  if (result.status !== 0) {
    console.error(
      `✗ seed failed (exit ${result.status}). Run migrations first: \`pnpm db:migrate\`.`,
    );
    process.exit(result.status ?? 1);
  }
  console.log("✓ Development seed data applied.");
}

async function confirm(question) {
  const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout,
  });
  const answer = await new Promise((resolve) =>
    rl.question(`${question} [y/N] `, resolve),
  );
  rl.close();
  return answer.trim().toLowerCase() === "y";
}

async function main() {
  switch (command) {
    case "migrate":
      console.log("Running Alembic migrations (upgrade head)…");
      runAlembic(["upgrade", "head"]);
      console.log("✓ Database is at the latest migration.");
      break;
    case "rollback":
      console.log("Rolling back the last Alembic migration…");
      runAlembic(["downgrade", "-1"]);
      console.log("✓ Rolled back one migration.");
      break;
    case "seed":
      runSeed();
      break;
    case "setup":
      runAlembic(["upgrade", "head"]);
      runSeed();
      break;
    case "reset": {
      const envName = (envOf().OPENAGENT_ENV ?? "development").toLowerCase();
      if (envName === "production") {
        console.error(
          "✗ Refusing to reset a production database. This command never runs in production.",
        );
        process.exit(1);
      }
      const confirmed =
        YES ||
        (await confirm(
          "This will DOWNGRADE ALL migrations and re-apply them (data loss). Continue?",
        ));
      if (!confirmed) {
        console.log("Aborted — database untouched.");
        process.exit(0);
      }
      runAlembic(["downgrade", "base"]);
      runAlembic(["upgrade", "head"]);
      runSeed();
      console.log("✓ Database reset complete (development data re-seeded).");
      break;
    }
    default:
      console.error(`Unknown db command: ${command ?? "(none)"}`);
      console.error(
        "Usage: node scripts/db.mjs migrate|rollback|seed|setup|reset [--yes]",
      );
      process.exit(1);
  }
}

main().catch((err) => {
  console.error(`✗ ${err.message}`);
  process.exit(1);
});
