import fs from "node:fs";
import path from "node:path";
import yaml from "js-yaml";
// Single canonical extension architecture: type + permission catalogs are
// owned by @openagent/developer-tools (mirrors the backend registry).
// This module re-exports them so the CLI can never drift.
import {
  EXTENSION_TYPES as CANONICAL_EXTENSION_TYPES,
  PERMISSION_CATALOG as CANONICAL_PERMISSION_CATALOG,
} from "@openagent/developer-tools";

export const EXTENSION_TYPES: readonly string[] = CANONICAL_EXTENSION_TYPES;

export type ExtensionType = (typeof CANONICAL_EXTENSION_TYPES)[number];

export const PERMISSION_CATALOG: readonly string[] = Object.keys(CANONICAL_PERMISSION_CATALOG);

export interface ValidationIssue {
  file: string;
  line?: number;
  field?: string;
  message: string;
  severity: "error" | "warning";
}

export interface ValidationResult {
  ok: boolean;
  manifest: Record<string, unknown>;
  manifestPath: string;
  errors: ValidationIssue[];
  warnings: ValidationIssue[];
}

export interface ExtensionManifest {
  manifest_version?: unknown;
  name?: unknown;
  version?: unknown;
  type?: unknown;
  description?: unknown;
  runtime?: unknown;
  permissions?: unknown;
  compatibility?: unknown;
  license?: unknown;
  authors?: unknown;
  [k: string]: unknown;
}

const NAME_RE = /^[a-z0-9][a-z0-9-_]{1,62}$/;
const SEMVER_RE = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$/;
const SECRET_REF_RE = /^[A-Z][A-Z0-9_]*$/;

function lineOf(text: string, needle: string): number | undefined {
  const idx = text.indexOf(needle);
  if (idx < 0) return undefined;
  return text.slice(0, idx).split("\n").length;
}

function parseCompatConstraint(raw: string): { ok: boolean; message?: string } {
  // Accept forms like ">=1.0.0 <2.0.0", "^1.2.0", "~1.2.0", ">=1.0.0", "1.2.3"
  const parts = raw.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return { ok: false, message: "empty compatibility constraint" };
  const single = /^(>=|<=|>|<|\^|~|=)?\s*\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$/;
  for (const p of parts) {
    if (!single.test(p)) return { ok: false, message: `unparseable constraint segment '${p}'` };
  }
  return { ok: true };
}

export function findManifestPath(cwd: string): string | undefined {
  const candidates = ["openagent.yaml", "openagent.yml", "openagent.json"];
  for (const c of candidates) {
    const p = path.join(cwd, c);
    if (fs.existsSync(p)) return p;
  }
  return undefined;
}

export function loadManifestFile(manifestPath: string): { manifest: Record<string, unknown>; rawText: string } {
  const rawText = fs.readFileSync(manifestPath, "utf8");
  let manifest: unknown;
  if (manifestPath.endsWith(".json")) {
    manifest = JSON.parse(rawText);
  } else {
    manifest = yaml.load(rawText);
  }
  if (!manifest || typeof manifest !== "object" || Array.isArray(manifest)) {
    throw new Error(`Manifest at ${manifestPath} must be a YAML/JSON mapping.`);
  }
  return { manifest: manifest as Record<string, unknown>, rawText };
}

export function validateManifestObject(
  manifest: Record<string, unknown>,
  fileLabel: string,
  rawText: string,
): { errors: ValidationIssue[]; warnings: ValidationIssue[] } {
  const errors: ValidationIssue[] = [];
  const warnings: ValidationIssue[] = [];
  const err = (field: string, message: string, severity: "error" | "warning" = "error") => {
    const issue: ValidationIssue = { file: fileLabel, field, message, severity };
    const l = lineOf(rawText, field);
    if (l !== undefined) issue.line = l;
    (severity === "error" ? errors : warnings).push(issue);
  };

  // manifest_version
  if (manifest.manifest_version !== "1") {
    err("manifest_version", `manifest_version must be the string '1' (got ${JSON.stringify(manifest.manifest_version)}).`);
  }
  // name
  if (typeof manifest.name !== "string" || !NAME_RE.test(manifest.name)) {
    err("name", "name must match /^[a-z0-9][a-z0-9-_]{1,62}$/ (lowercase, digits, '-' or '_').");
  }
  // version
  if (typeof manifest.version !== "string" || !SEMVER_RE.test(manifest.version)) {
    err("version", "version must be valid semver (e.g. 0.1.0).");
  }
  // type
  if (typeof manifest.type !== "string" || !(EXTENSION_TYPES as readonly string[]).includes(manifest.type)) {
    err("type", `type must be one of: ${EXTENSION_TYPES.join(", ")} (got ${JSON.stringify(manifest.type)}).`);
  }
  // description
  if (typeof manifest.description !== "string" || manifest.description.trim().length < 10) {
    err("description", "description must be a string of at least 10 characters.", "error");
  }
  // runtime
  const runtime = manifest.runtime as Record<string, unknown> | undefined;
  if (!runtime || typeof runtime !== "object") {
    err("runtime", "runtime must be a mapping with at least 'entrypoint'.");
  } else {
    if (typeof runtime.entrypoint !== "string" || runtime.entrypoint.trim() === "") {
      err("runtime.entrypoint", "runtime.entrypoint is required (e.g. src/index.ts or src/main.py).");
    } else if (runtime.entrypoint.includes("..") || path.isAbsolute(runtime.entrypoint)) {
      err("runtime.entrypoint", "runtime.entrypoint must be a relative path inside the project.");
    }
    if (runtime.language !== undefined && !["typescript", "python"].includes(String(runtime.language))) {
      err("runtime.language", "runtime.language must be 'typescript' or 'python' when set.", "warning");
    }
  }
  // permissions
  const perms = manifest.permissions;
  if (perms !== undefined) {
    if (!Array.isArray(perms)) {
      err("permissions", "permissions must be an array of permission strings or {permission, allowed_hosts} objects.");
    } else {
      const seen = new Set<string>();
      for (let i = 0; i < perms.length; i++) {
        const p = perms[i] as unknown;
        let permName: string | undefined;
        let obj: Record<string, unknown> | undefined;
        if (typeof p === "string") {
          permName = p;
        } else if (p && typeof p === "object") {
          obj = p as Record<string, unknown>;
          permName = typeof obj.permission === "string" ? obj.permission : undefined;
        }
        if (!permName || !(PERMISSION_CATALOG as readonly string[]).includes(permName)) {
          err(`permissions[${i}]`, `unknown permission ${JSON.stringify(permName)}. Allowed: ${PERMISSION_CATALOG.join(", ")}.`);
          continue;
        }
        if (seen.has(permName)) {
          err(`permissions[${i}]`, `duplicate permission '${permName}'.`, "warning");
        }
        seen.add(permName);
        if (permName === "network:outbound") {
          const hosts = obj?.allowed_hosts ?? (manifest as Record<string, unknown>).allowed_hosts;
          if (!Array.isArray(hosts) || hosts.length === 0 || !hosts.every((h) => typeof h === "string" && h.length > 0)) {
            err(
              `permissions[${i}]`,
              "permission 'network:outbound' requires 'allowed_hosts' (non-empty string array) on the entry or top-level manifest.",
            );
          }
        }
        if (permName === "secret:access" && obj?.refs !== undefined) {
          if (!Array.isArray(obj.refs) || !obj.refs.every((r) => typeof r === "string" && SECRET_REF_RE.test(r))) {
            err(`permissions[${i}].refs`, "secrets refs must be UPPER_SNAKE_CASE names (e.g. MY_API_KEY).");
          }
        }
      }
      // top-level secrets refs check
      const secrets = (manifest as Record<string, unknown>).secrets;
      if (secrets !== undefined) {
        if (!Array.isArray(secrets) || !secrets.every((s) => typeof s === "string" && SECRET_REF_RE.test(s))) {
          err("secrets", "top-level 'secrets' must be an array of UPPER_SNAKE_CASE references (no raw values).");
        }
      }
    }
  }
  // compatibility
  const compat = manifest.compatibility as Record<string, unknown> | undefined;
  if (!compat || typeof compat !== "object") {
    err("compatibility", "compatibility must be a mapping including openagent constraint (e.g. '>=1.0.0 <2.0.0').", "warning");
  } else {
    const oa = compat.openagent;
    if (typeof oa !== "string" || oa.trim() === "") {
      err("compatibility.openagent", "compatibility.openagent is required (e.g. '>=1.0.0 <2.0.0').", "warning");
    } else {
      const parsed = parseCompatConstraint(oa);
      if (!parsed.ok) err("compatibility.openagent", `invalid openagent constraint: ${parsed.message}.`, "error");
    }
  }
  // license
  if (typeof manifest.license !== "string" || manifest.license.trim() === "") {
    err("license", "license is required (e.g. MIT).");
  }
  return { errors, warnings };
}

export function validateProject(cwd: string, manifestPathOverride?: string): ValidationResult {
  const manifestPath = manifestPathOverride ?? findManifestPath(cwd);
  if (!manifestPath) {
    return {
      ok: false,
      manifest: {},
      manifestPath: path.join(cwd, "openagent.yaml"),
      errors: [{ file: path.join(cwd, "openagent.yaml"), message: "No manifest found (looked for openagent.yaml, openagent.yml, openagent.json). Run `openagent init`.", severity: "error" }],
      warnings: [],
    };
  }
  let manifest: Record<string, unknown> = {};
  let rawText = "";
  try {
    const loaded = loadManifestFile(manifestPath);
    manifest = loaded.manifest;
    rawText = loaded.rawText;
  } catch (e) {
    return {
      ok: false,
      manifest: {},
      manifestPath,
      errors: [{ file: manifestPath, message: `Failed to parse manifest: ${e instanceof Error ? e.message : String(e)}`, severity: "error" }],
      warnings: [],
    };
  }
  const { errors, warnings } = validateManifestObject(manifest, manifestPath, rawText);
  // entrypoint existence check (warning, not error — file may be generated later)
  const runtime = manifest.runtime as Record<string, unknown> | undefined;
  if (runtime && typeof runtime.entrypoint === "string") {
    const ep = path.resolve(path.dirname(manifestPath), runtime.entrypoint);
    if (!fs.existsSync(ep)) {
      warnings.push({ file: manifestPath, field: "runtime.entrypoint", message: `entrypoint '${runtime.entrypoint}' does not exist yet.`, severity: "warning" });
    }
  }
  return { ok: errors.length === 0, manifest, manifestPath, errors, warnings };
}

export function formatIssues(result: ValidationResult): string {
  const lines: string[] = [];
  for (const i of result.errors) {
    lines.push(`error ${i.file}${i.line ? `:${i.line}` : ""}${i.field ? ` [${i.field}]` : ""}: ${i.message}`);
  }
  for (const i of result.warnings) {
    lines.push(`warning ${i.file}${i.line ? `:${i.line}` : ""}${i.field ? ` [${i.field}]` : ""}: ${i.message}`);
  }
  return lines.join("\n");
}
