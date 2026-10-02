#!/usr/bin/env node
/*
 * OpenAgent release gate (read-only, cross-platform).
 * Validates release preparedness WITHOUT publishing, pushing, or tagging.
 * Exit 0 = all checks pass. Exit 1 = at least one FAIL (WARN never fails).
 *
 * Usage: node scripts/release-check.mjs [--json]
 */
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const JSON_OUT = process.argv.includes("--json");
const results = [];
const ok = (name, detail) => results.push({ name, status: "pass", detail });
const warn = (name, detail) => results.push({ name, status: "warn", detail });
const fail = (name, detail) => results.push({ name, status: "fail", detail });

const run = (cmd, args, cwd = ROOT) => {
  try {
    return execFileSync(cmd, args, {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"],
      cwd,
    }).trim();
  } catch {
    return null;
  }
};

// 1. Clean git state on main (or on an exact release tag in CI)
const porcelain = run("git", ["status", "--porcelain"]);
const branch = run("git", ["branch", "--show-current"]);
if (branch === "main" || branch === "master") ok("branch", branch);
else {
  const tag = run("git", ["describe", "--exact-match", "--tags", "HEAD"]);
  if (tag && /^v\d+\.\d+\.\d+$/.test(tag))
    ok("branch", `detached at release tag ${tag}`);
  else
    fail(
      "branch",
      `expected main or a vX.Y.Z tag, on '${branch ?? tag ?? "?"}'`,
    );
}
if (porcelain === "") ok("git-clean", "working tree clean");
else fail("git-clean", "uncommitted changes present — commit or stash first");

// 2. Canonical version readable + consistent with API version surface
try {
  const root = JSON.parse(
    readFileSync(path.join(ROOT, "package.json"), "utf8"),
  );
  const mainPy = readFileSync(
    path.join(ROOT, "apps", "api", "src", "openagent", "main.py"),
    "utf8",
  );
  const m = mainPy.match(/"version":\s*"([^"]+)"/);
  if (root.version && m && m[1] === root.version)
    ok("version", `platform ${root.version} (root + API agree)`);
  else
    fail(
      "version",
      `root=${root.version ?? "?"} api=${m ? m[1] : "?"} — must agree`,
    );
} catch (e) {
  fail("version", `could not read version metadata: ${e.message}`);
}

// 3. Required release files exist
for (const f of [
  "CHANGELOG.md",
  "LICENSE",
  "SECURITY.md",
  ".env.example",
  ".env.production.example",
  "docker-compose.yml",
  "docker-compose.production.yml",
  "docs/release/release-readiness.md",
  "docs/release/release-notes.md",
  "docs/deployment/self-hosted.md",
  "docs/deployment/production-checklist.md",
  "docs/deployment/upgrading.md",
  "docs/security/data-flow.md",
]) {
  if (existsSync(path.join(ROOT, f))) ok(`file:${f}`, "present");
  else fail(`file:${f}`, "missing");
}

// 4. No secrets tracked (patterns only — values never printed).
// A bare "BEGIN PRIVATE KEY" string is EXPECTED in this repo: the secret
// scanners and their test fixtures mention the marker with fake payloads
// (e.g. "...PRIVATE KEY-----\nabc"). Only a header followed by a real
// base64 payload line (64+ chars) counts as a finding.
const candidates = run("git", [
  "grep",
  "-l",
  "-E",
  "BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY",
  "--",
  ".",
]);
let realKeys = [];
if (candidates) {
  const { readFileSync: rf } = await import("node:fs");
  const pemRe =
    /-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----\s*\r?\n\s*[A-Za-z0-9+/=]{64,}/;
  for (const f of candidates
    .split("\n")
    .map((s) => s.trim())
    .filter(Boolean)) {
    try {
      if (pemRe.test(rf(path.join(ROOT, f), "utf8"))) realKeys.push(f);
    } catch {
      /* unreadable — ignore */
    }
  }
}
if (realKeys.length === 0) {
  ok(
    "secret-scan",
    "no private-key payloads tracked (marker strings exist only in scanners/fixtures)",
  );
} else {
  fail("secret-scan", `private-key payload in: ${realKeys.join(", ")}`);
}
const envTracked = run("git", ["ls-files"]);
if (envTracked && envTracked.split("\n").some((l) => l.trim() === ".env")) {
  fail("env-tracked", ".env is tracked — remove it immediately");
} else {
  ok("env-tracked", ".env not tracked");
}

// 5. Alembic: exactly one head, linear history (offline check, no DB needed)
const alembicHeads = (() => {
  const venvWin = path.join(
    ROOT,
    "apps",
    "api",
    ".venv",
    "Scripts",
    "python.exe",
  );
  const venvNix = path.join(ROOT, "apps", "api", ".venv", "bin", "python");
  const py = existsSync(venvWin)
    ? venvWin
    : existsSync(venvNix)
      ? venvNix
      : null;
  if (!py) return null;
  try {
    return execFileSync(py, ["-m", "alembic", "heads"], {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"],
      cwd: path.join(ROOT, "apps", "api"),
    }).trim();
  } catch {
    return null;
  }
})();
if (alembicHeads === null)
  warn("alembic-heads", "could not run alembic (no backend venv?) — skipped");
else if (alembicHeads.includes("\n"))
  fail("alembic-heads", "multiple heads — resolve before release");
else ok("alembic-heads", alembicHeads || "(no output)");

// 6. CHANGELOG has an entry for the current version (or Unreleased)
try {
  const cl = readFileSync(path.join(ROOT, "CHANGELOG.md"), "utf8");
  const root = JSON.parse(
    readFileSync(path.join(ROOT, "package.json"), "utf8"),
  );
  if (cl.includes(`## [${root.version}]`) || cl.includes("## [Unreleased]")) {
    ok("changelog", `covers ${root.version} or Unreleased`);
  } else fail("changelog", `no entry for ${root.version} or Unreleased`);
} catch (e) {
  fail("changelog", e.message);
}

// 7. Production compose + prod env template parse and agree on required vars
try {
  const compose = readFileSync(
    path.join(ROOT, "docker-compose.production.yml"),
    "utf8",
  );
  const envExample = readFileSync(
    path.join(ROOT, ".env.production.example"),
    "utf8",
  );
  const required = [...compose.matchAll(/\$\{([A-Z_]+):\?/g)].map((m) => m[1]);
  const missing = [...new Set(required)].filter((v) => !envExample.includes(v));
  if (missing.length === 0)
    ok(
      "prod-config",
      `${new Set(required).size} required vars all documented in .env.production.example`,
    );
  else fail("prod-config", `undocumented required vars: ${missing.join(", ")}`);
} catch (e) {
  fail("prod-config", e.message);
}

// 8. CLI builds/offline surface (dist must exist from a real build)
if (
  existsSync(path.join(ROOT, "packages", "cli", "dist", "bin", "openagent.js"))
) {
  ok("cli-dist", "packages/cli/dist present (built)");
} else {
  warn(
    "cli-dist",
    "packages/cli/dist missing — run pnpm build before packaging a CLI release",
  );
}

// Report
if (JSON_OUT) {
  console.log(JSON.stringify({ results }, null, 2));
} else {
  console.log("\nOpenAgent release:check\n");
  for (const r of results) {
    const icon = r.status === "pass" ? "✓" : r.status === "warn" ? "!" : "✗";
    console.log(`${icon} ${r.name}: ${r.detail}`);
  }
  const failed = results.filter((r) => r.status === "fail").length;
  console.log(
    failed === 0
      ? "\nRelease checks passed (validation only — nothing published)."
      : `\n${failed} check(s) FAILED — do not tag or publish.`,
  );
}
process.exitCode = results.some((r) => r.status === "fail") ? 1 : 0;
