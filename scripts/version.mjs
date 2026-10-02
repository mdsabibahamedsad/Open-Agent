#!/usr/bin/env node
/*
 * OpenAgent version reporter (read-only, cross-platform).
 * Canonical platform version = root package.json `version` (currently 0.1.0).
 * The Developer Platform 1.x line (CLI/SDK) carries its own compatibility
 * version — see docs/release/release-readiness.md. This script reports both
 * instead of pretending there is one number.
 *
 * Usage: node scripts/version.mjs [--json]
 */
import { readFileSync, existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const JSON_OUT = process.argv.includes("--json");
const readJson = (p) => JSON.parse(readFileSync(p, "utf8"));

const root = readJson(path.join(ROOT, "package.json"));
const info = { platform: root.version ?? "unknown", components: {} };

const webPkg = path.join(ROOT, "apps", "web", "package.json");
if (existsSync(webPkg)) info.components.web = readJson(webPkg).version;

const cliPkg = path.join(ROOT, "packages", "cli", "package.json");
if (existsSync(cliPkg)) info.components.cli = readJson(cliPkg).version;

const apiToml = path.join(ROOT, "apps", "api", "pyproject.toml");
if (existsSync(apiToml)) {
  const m = readFileSync(apiToml, "utf8").match(/^version\s*=\s*"([^"]+)"/m);
  if (m) info.components.api = m[1];
}

const sdkPkg = path.join(ROOT, "packages", "python-sdk", "pyproject.toml");
if (existsSync(sdkPkg)) {
  const m = readFileSync(sdkPkg, "utf8").match(/^version\s*=\s*"([^"]+)"/m);
  if (m) info.components["python-sdk"] = m[1];
}

if (JSON_OUT) {
  console.log(JSON.stringify(info, null, 2));
} else {
  console.log(`OpenAgent ${info.platform}`);
  for (const [k, v] of Object.entries(info.components))
    console.log(`  ${k}: ${v}`);
}
