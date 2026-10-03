#!/usr/bin/env node
// OpenAgent CLI launcher — cross-platform npm bin entrypoint.
// Works on Windows (npm generates openagent.cmd / openagent.ps1 from this),
// macOS, and Linux. Loads the self-contained bundled implementation in
// dist/bin/openagent.cjs so the installed CLI never depends on the source dir.
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const require = createRequire(import.meta.url);
const here = path.dirname(fileURLToPath(import.meta.url));
const bundled = path.join(here, "..", "dist", "bin", "openagent.cjs");

try {
  await import(pathToFileURL(bundled).href);
} catch (err) {
  // Fallback for unusual layouts: try resolving relative to package root.
  try {
    const pkgRoot = path.join(here, "..");
    const fallback = require.resolve("./dist/bin/openagent.cjs", {
      paths: [pkgRoot, here],
    });
    await import(pathToFileURL(fallback).href);
  } catch {
    const msg = err instanceof Error ? err.message : String(err);
    process.stderr.write(`openagent: failed to load CLI runtime: ${msg}\n`);
    process.exit(1);
  }
}
