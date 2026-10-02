#!/usr/bin/env node
/*
 * OpenAgent cross-platform clean.
 * Removes generated outputs only — never touches source, .env, or databases.
 *
 * Usage: node scripts/clean.mjs [--all]
 *   --all also removes node_modules and Python virtualenvs (full reset).
 */
import { rmSync, existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const ALL = process.argv.includes("--all");

const generated = [
  ".turbo",
  "apps/web/.next",
  "apps/web/coverage",
  "apps/api/.pytest_cache",
  "apps/api/.mypy_cache",
  "apps/api/.ruff_cache",
  "apps/worker/.pytest_cache",
  ".ruff_cache",
];

const workspaceOutputs = [
  "packages/agent-runtime/dist",
  "packages/api-client/dist",
  "packages/browser/dist",
  "packages/cli/dist",
  "packages/config/dist",
  "packages/connector-sdk/dist",
  "packages/core/dist",
  "packages/database/dist",
  "packages/developer-tools/dist",
  "packages/evaluator/dist",
  "packages/extension-sdk/dist",
  "packages/logger/dist",
  "packages/mcp/dist",
  "packages/memory/dist",
  "packages/model-router/dist",
  "packages/python-sdk/build",
  "packages/sandbox/dist",
  "packages/sdk/dist",
  "packages/sdk-types/dist",
  "packages/security/dist",
  "packages/tool-system/dist",
  "packages/types/dist",
  "packages/workflow-engine/dist",
];

const allOnly = ["node_modules", "apps/api/.venv", "apps/worker/.venv"];

let removed = 0;
for (const rel of [
  ...generated,
  ...workspaceOutputs,
  ...(ALL ? allOnly : []),
]) {
  const target = path.join(ROOT, rel);
  if (!existsSync(target)) continue;
  try {
    rmSync(target, { recursive: true, force: true });
    console.log(`removed ${rel}`);
    removed += 1;
  } catch (err) {
    console.error(`could not remove ${rel}: ${err.message}`);
    process.exitCode = 1;
  }
}
console.log(
  removed === 0 ? "Nothing to clean." : `Clean complete (${removed} path(s)).`,
);
if (!ALL) {
  console.log(
    "Tip: `pnpm clean:all` also removes node_modules and virtualenvs.",
  );
}
