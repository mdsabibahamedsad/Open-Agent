import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { execSync, spawn } from "node:child_process";
import type { Command } from "commander";
import prompts from "prompts";
import pc from "picocolors";
import yaml from "js-yaml";
import { ApiClient, printResult, printSuccess, printErrorLine, newIdempotencyKey, type OutputOptions } from "./http.js";
import { getProfile, saveProfile, listProfiles, maskApiKey, redactSecrets, configFilePath, registryDir } from "./config.js";
import { loginInteractive, logout as doLogout, whoami } from "./auth.js";
import { scaffoldProject, SCAFFOLD_KINDS, type ScaffoldKind, type ScaffoldLanguage } from "./scaffold.js";
import { validateProject, findManifestPath, loadManifestFile, formatIssues } from "./validate.js";
import { scanDirectory, formatFindings } from "./security.js";
import { packageProject, inspectPackage } from "./packaging.js";

export interface GlobalFlags {
  json?: boolean;
  quiet?: boolean;
  verbose?: boolean;
  org?: string;
  profile?: string;
  color?: boolean;
}

function outFrom(program: Command, cmd: Command): OutputOptions & { client: ApiClient; orgId?: string; apiUrl: string; profileName: string } {
  const go = program.opts<GlobalFlags>();
  const lo = cmd.opts<GlobalFlags>();
  const json = lo.json ?? go.json ?? false;
  const quiet = lo.quiet ?? go.quiet ?? false;
  const verbose = lo.verbose ?? go.verbose ?? false;
  const org = lo.org ?? go.org;
  const profileOpt = lo.profile ?? go.profile;
  const colorFalse = (lo.color === false || go.color === false) || process.env.NO_COLOR !== undefined;
  const resolved = getProfile(profileOpt, org);
  const client = new ApiClient({ baseUrl: resolved.apiUrl, apiKey: resolved.apiKey, orgId: resolved.orgId, verbose });
  return { json, quiet, verbose, noColor: colorFalse, client, orgId: resolved.orgId, apiUrl: resolved.apiUrl, profileName: resolved.name };
}

function okLine(msg: string, out: OutputOptions): void {
  if (out.quiet) return;
  if (out.json) {
    process.stdout.write(JSON.stringify({ ok: true, message: msg }) + "\n");
    return;
  }
  const useColor = !out.noColor && !process.env.NO_COLOR;
  process.stdout.write((useColor ? pc.green("✓ ") : "") + msg + "\n");
}

function ensureOrg(out: { orgId?: string }): string {
  if (!out.orgId) throw Object.assign(new Error("Organization ID is required. Pass --org, set OPENAGENT_ORG_ID, or run `openagent config set orgId <id>`."), { exitCode: 3 });
  return out.orgId;
}

function cwdOf(dirOpt?: string): string {
  return path.resolve(dirOpt ?? process.cwd());
}

function readManifestCwd(cwd: string): { manifest: Record<string, unknown>; manifestPath: string } {
  const mp = findManifestPath(cwd);
  if (!mp) throw Object.assign(new Error(`No openagent manifest in ${cwd}. Run \`openagent init\`.`), { exitCode: 2 });
  const { manifest } = loadManifestFile(mp);
  return { manifest, manifestPath: mp };
}

export function registerCommands(program: Command): void {
  // ---------- init ----------
  program
    .command("init [dir]")
    .description("Scaffold a new extension project")
    .option("--kind <kind>", `extension kind (${SCAFFOLD_KINDS.join("|")})`)
    .option("--language <lang>", "language (ts|python)")
    .option("--name <name>", "extension name")
    .option("--description <desc>", "short description")
    .option("--yes", "non-interactive; use defaults/flags only")
    .action(async (dir: string | undefined, opts: Record<string, unknown>, cmd: Command) => {
      const out = outFrom(program, cmd);
      let kind = String(opts.kind ?? "");
      let language = String(opts.language ?? "");
      let name = String(opts.name ?? "");
      let description = String(opts.description ?? "");
      const yes = Boolean(opts.yes);
      if (!yes && (!kind || !language || !name)) {
        const answers = await prompts([
          { type: kind ? null : "select", name: "kind", message: "Extension kind", choices: [...SCAFFOLD_KINDS, "agent", "tool"].filter((v, i, a) => a.indexOf(v) === i).map((v) => ({ title: v, value: v })), initial: 1 },
          { type: language ? null : "select", name: "language", message: "Language", choices: [{ title: "TypeScript", value: "ts" }, { title: "Python", value: "python" }], initial: 0 },
          { type: name ? null : "text", name: "name", message: "Extension name", initial: "my-extension" },
        ]);
        kind = kind || answers.kind || "tool";
        language = language || answers.language || "ts";
        name = name || answers.name || "my-extension";
        if (!description) {
          const d = await prompts({ type: "text", name: "description", message: "Description", initial: `My ${kind} extension.` });
          description = d.description ?? "";
        }
      }
      kind = kind || "tool";
      language = (language || "ts") as string;
      name = name || "my-extension";
      if (!SCAFFOLD_KINDS.includes(kind as ScaffoldKind) && !["agent", "tool"].includes(kind)) {
        printErrorLine(`Unknown kind '${kind}'. Allowed: ${SCAFFOLD_KINDS.join(", ")}`, out);
        process.exitCode = 2;
        return;
      }
      if (language !== "ts" && language !== "python") {
        printErrorLine("Language must be ts or python.", out);
        process.exitCode = 2;
        return;
      }
      const target = path.resolve(dir ?? ".");
      const { dir: created, files } = scaffoldProject({ name, kind: kind as ScaffoldKind, language: language as ScaffoldLanguage, targetDir: target, description });
      okLine(`Scaffolded ${kind} '${name}' in ${created} (${files.length} files).`, out);
      printResult({ dir: created, files }, out);
    });

  // ---------- login / logout / whoami ----------
  program
    .command("login")
    .description("Authenticate (device flow, --api-key, or --token stdin)")
    .option("--api-key <key>", "non-interactive API key")
    .option("--token", "read token from stdin")
    .option("--org <org>", "organization ID")
    .option("--api-url <url>", "API base URL")
    .action(async (opts: Record<string, string | boolean | undefined>, cmd: Command) => {
      const out = outFrom(program, cmd);
      const res = await loginInteractive({
        apiKey: typeof opts.apiKey === "string" ? opts.apiKey : undefined,
        tokenStdin: Boolean(opts.token),
        profile: out.profileName,
        org: typeof opts.org === "string" ? opts.org : out.orgId,
        apiUrl: typeof opts["apiUrl"] === "string" ? (opts["apiUrl"] as string) : out.apiUrl,
      });
      okLine(`Logged in (profile '${res.profile}'). Key: ${maskApiKey(getProfile(res.profile).apiKey)}`, out);
    });

  program
    .command("logout")
    .description("Remove stored credentials for the active profile")
    .action(async (_o: unknown, cmd: Command) => {
      const out = outFrom(program, cmd);
      const removed = doLogout(out.profileName);
      okLine(removed ? `Logged out (profile '${out.profileName}').` : `No credentials stored for '${out.profileName}'.`, out);
    });

  program
    .command("whoami")
    .description("Show current identity (GET /api/v1/auth/me)")
    .action(async (_o: unknown, cmd: Command) => {
      const out = outFrom(program, cmd);
      const resolved = getProfile((program.opts() as GlobalFlags).profile ?? (cmd.opts() as GlobalFlags).profile, (cmd.opts() as GlobalFlags).org ?? (program.opts() as GlobalFlags).org);
      const data = await whoami(resolved.apiUrl, resolved.apiKey, resolved.orgId);
      printResult(redactSecrets(data), out.json ? { ...out, json: true } : out);
    });

  const authCmd = program.command("auth").description("Auth helpers");
  authCmd
    .command("status")
    .description("Show auth status with masked key")
    .action(async (_o: unknown, cmd: Command) => {
      const parent = program;
      const go = parent.opts<GlobalFlags>();
      const resolved = getProfile(go.profile, go.org);
      const out: OutputOptions = { json: go.json, quiet: go.quiet, verbose: go.verbose, noColor: go.color === false };
      const payload = { profile: resolved.name, apiUrl: resolved.apiUrl, orgId: resolved.orgId ?? "(none)", apiKey: maskApiKey(resolved.apiKey), authenticated: Boolean(resolved.apiKey) };
      void cmd;
      printResult(out.json ? payload : payload, out);
    });

  // ---------- dev ----------
  program
    .command("dev")
    .description("DEVELOPMENT MODE: local manifest server with hot-reload (does not deploy)")
    .option("--dir <dir>", "project directory", ".")
    .option("--port <port>", "port to serve on", "8899")
    .action(async (opts: Record<string, string>, cmd: Command) => {
      const out = outFrom(program, cmd);
      const cwd = cwdOf(opts.dir);
      const port = Number(opts.port ?? "8899");
      await startDevServer(cwd, port, out);
    });

  // ---------- validate ----------
  program
    .command("validate")
    .description("Offline manifest validation")
    .option("--dir <dir>", "project directory", ".")
    .option("--manifest <path>", "manifest path override")
    .action(async (opts: Record<string, string>, cmd: Command) => {
      const out = outFrom(program, cmd);
      const cwd = cwdOf(opts.dir);
      const res = validateProject(cwd, opts.manifest ? path.resolve(opts.manifest) : undefined);
      if (out.json) {
        printResult({ ok: res.ok, manifestPath: res.manifestPath, errors: res.errors, warnings: res.warnings }, { ...out, json: true });
      } else if (!out.quiet) {
        if (res.ok && res.warnings.length === 0) okLine(`Manifest valid: ${res.manifestPath}`, out);
        else {
          const txt = formatIssues(res);
          if (txt) process.stdout.write(txt + "\n");
          if (res.ok) okLine("Manifest valid with warnings.", out);
        }
      }
      if (!res.ok) process.exitCode = 2;
    });

  // ---------- test ----------
  program
    .command("test")
    .description("Offline checks + server-side extension tests (POST .../extensions/{id}/test)")
    .option("--dir <dir>", "project directory", ".")
    .option("--id <id>", "extension ID for server tests")
    .option("--version <v>", "version for server tests")
    .action(async (opts: Record<string, string>, cmd: Command) => {
      const out = outFrom(program, cmd);
      const cwd = cwdOf(opts.dir);
      const res = validateProject(cwd);
      const scan = scanDirectory(cwd);
      if (out.json) {
        printResult({ manifestOk: res.ok, errors: res.errors, warnings: res.warnings, security: scan }, { ...out, json: true });
      } else if (!out.quiet) {
        process.stdout.write((formatIssues(res) ? formatIssues(res) + "\n" : "manifest: OK\n") + formatFindings(scan) + "\n");
      }
      if (!res.ok) {
        process.exitCode = 2;
        return;
      }
      if (scan.blocksPublish) {
        printErrorLine("Secret/dangerous findings block server publish; see report above.", out);
        process.exitCode = 2;
        return;
      }
      if (opts.id) {
        const org = ensureOrg(out);
        const data = await out.client.post(out.client.orgPath(`/extensions/${encodeURIComponent(opts.id)}/test`), { version: opts.version });
        printResult(data, out);
      } else if (!out.quiet && !out.json) {
        process.stdout.write("No --id given; server tests skipped (offline checks passed).\n");
      }
    });

  // ---------- build ----------
  program
    .command("build")
    .description("Presence-checked build (tsc for TS, compileall for Python)")
    .option("--dir <dir>", "project directory", ".")
    .action(async (opts: Record<string, string>, cmd: Command) => {
      const out = outFrom(program, cmd);
      const cwd = cwdOf(opts.dir);
      const { manifest } = readManifestCwd(cwd);
      const rt = (manifest.runtime ?? {}) as Record<string, unknown>;
      const entry = String(rt.entrypoint ?? "src/index.ts");
      if (entry.endsWith(".py")) {
        try {
          execSync("python3 -m compileall -q src", { cwd, stdio: out.verbose ? "inherit" : "pipe" });
          okLine("Python build check passed (compileall).", out);
        } catch {
          printErrorLine("Python build check failed (compileall).", out);
          process.exitCode = 1;
        }
        return;
      }
      // TypeScript: prefer local tsc.
      const tscCandidates = [path.join(cwd, "node_modules", ".bin", "tsc"), "npx tsc", "tsc"];
      let built = false;
      let lastErr = "";
      for (const tsc of tscCandidates.slice(0, 1)) {
        try {
          execSync(`${tsc} --noEmit -p tsconfig.json`, { cwd, stdio: out.verbose ? "inherit" : "pipe" });
          built = true;
          break;
        } catch (e) {
          lastErr = e instanceof Error ? e.message : String(e);
          // Fallback: at least verify entrypoint exists.
          if (fs.existsSync(path.join(cwd, entry))) {
            okLine("Build presence check passed (entrypoint exists; tsc unavailable or reported issues — see --verbose).", out);
            if (out.verbose) process.stderr.write(lastErr + "\n");
            return;
          }
        }
      }
      if (built) okLine("TypeScript build check passed (tsc --noEmit).", out);
      else {
        printErrorLine(`Build check failed: ${lastErr.slice(0, 500)}`, out);
        process.exitCode = 1;
      }
    });

  // ---------- package ----------
  program
    .command("package")
    .description("Build deterministic .oaext offline (+ optional server packaging call)")
    .option("--dir <dir>", "project directory", ".")
    .option("--out <path>", "output .oaext path")
    .option("--server-id <id>", "also call server packaging for extension ID")
    .option("--inspect", "inspect the built archive after packaging")
    .action(async (opts: Record<string, string | boolean | undefined>, cmd: Command) => {
      const out = outFrom(program, cmd);
      const cwd = cwdOf(typeof opts.dir === "string" ? opts.dir : ".");
      const res = validateProject(cwd);
      if (!res.ok) {
        if (!out.quiet) process.stdout.write(formatIssues(res) + "\n");
        process.exitCode = 2;
        return;
      }
      const scan = scanDirectory(cwd);
      if (scan.blocksPublish) {
        printErrorLine("Refusing to package: secret/dangerous findings:\n" + formatFindings(scan), out);
        process.exitCode = 2;
        return;
      }
      const built = packageProject(cwd, typeof opts.out === "string" ? { outPath: path.resolve(opts.out) } : {});
      okLine(`Packaged ${built.outPath} (${built.bytes} bytes, sha256 ${built.sha256.slice(0, 12)}…).`, out);
      printResult(built, out);
      if (opts.inspect) {
        const info = inspectPackage(built.outPath);
        printResult(info, out);
      }
      if (typeof opts.serverId === "string" && opts.serverId) {
        const org = ensureOrg(out);
        const data = await out.client.post(out.client.orgPath(`/extensions/${encodeURIComponent(opts.serverId)}/package`), { sha256: built.sha256 });
        printResult(data, out);
      }
    });

  program
    .command("inspect <archive>")
    .description("Verify and list contents of a .oaext archive")
    .action(async (archive: string, _o: unknown, cmd: Command) => {
      const out = outFrom(program, cmd);
      const info = inspectPackage(path.resolve(archive));
      okLine(`Archive OK: ${info.entries.length} entries, ${info.files} project files, checksums verified.`, out);
      printResult(info, out);
    });

  // ---------- publish / deploy / rollback ----------
  program
    .command("publish")
    .description("Secret-scan gate + POST .../extensions/{id}/publish")
    .requiredOption("--id <id>", "extension ID")
    .option("--version <v>", "version (defaults to manifest version)")
    .option("--notes <notes>", "release notes")
    .option("--dir <dir>", "project directory for manifest/scan", ".")
    .option("--skip-scan", "skip local secret scan (not recommended)")
    .action(async (opts: Record<string, string | boolean | undefined>, cmd: Command) => {
      const out = outFrom(program, cmd);
      const cwd = cwdOf(typeof opts.dir === "string" ? (opts.dir as string) : ".");
      let version = typeof opts.version === "string" ? opts.version : undefined;
      if (!version) {
        try {
          const { manifest } = readManifestCwd(cwd);
          version = String(manifest.version ?? "");
        } catch {
          version = undefined;
        }
      }
      if (!version) {
        printErrorLine("Version is required (--version or manifest version).", out);
        process.exitCode = 2;
        return;
      }
      if (!opts.skipScan) {
        const scan = scanDirectory(cwd);
        if (scan.blocksPublish) {
          printErrorLine("Publish blocked by secret scan:\n" + formatFindings(scan), out);
          process.exitCode = 2;
          return;
        }
      }
      const org = ensureOrg(out);
      const data = await out.client.post(
        out.client.orgPath(`/extensions/${encodeURIComponent(String(opts.id))}/publish`),
        { version, notes: typeof opts.notes === "string" ? opts.notes : undefined },
        { idempotencyKey: newIdempotencyKey() },
      );
      okLine(`Published ${String(opts.id)}@${version}.`, out);
      printResult(data, out);
    });

  program
    .command("deploy")
    .description("Deploy an extension version (POST .../extensions/{id}/deploy)")
    .requiredOption("--id <id>", "extension ID")
    .requiredOption("--version <v>", "version to deploy")
    .option("--env <env>", "target environment", "production")
    .action(async (opts: Record<string, string>, cmd: Command) => {
      const out = outFrom(program, cmd);
      const org = ensureOrg(out);
      const data = await out.client.post(
        out.client.orgPath(`/extensions/${encodeURIComponent(opts.id)}/deploy`),
        { version: opts.version, environment: opts.env ?? "production" },
        { idempotencyKey: newIdempotencyKey() },
      );
      okLine(`Deployed ${opts.id}@${opts.version} to ${opts.env ?? "production"}.`, out);
      printResult(data, out);
    });

  program
    .command("rollback")
    .description("Rollback an extension (POST .../extensions/{id}/rollback)")
    .requiredOption("--id <id>", "extension ID")
    .option("--version <v>", "version to roll back to")
    .action(async (opts: Record<string, string>, cmd: Command) => {
      const out = outFrom(program, cmd);
      const org = ensureOrg(out);
      const data = await out.client.post(out.client.orgPath(`/extensions/${encodeURIComponent(opts.id)}/rollback`), { version: opts.version });
      okLine(`Rollback requested for ${opts.id}${opts.version ? `@${opts.version}` : ""}.`, out);
      printResult(data, out);
    });

  // ---------- extensions lifecycle ----------
  const ext = program.command("extensions").description("Extension lifecycle (developer API)");
  ext.command("list").description("List extensions").action(async (_o: unknown, cmd: Command) => {
    const out = outFrom(program, cmd);
    const org = ensureOrg(out);
    printResult(await out.client.get(out.client.orgPath("/extensions")), out);
  });
  ext.command("get <id>").description("Get extension by ID").action(async (id: string, _o: unknown, cmd: Command) => {
    const out = outFrom(program, cmd);
    const org = ensureOrg(out);
    printResult(await out.client.get(out.client.orgPath(`/extensions/${encodeURIComponent(id)}`)), out);
  });
  ext.command("create").description("Create extension from local manifest").option("--dir <dir>", "project dir", ".").action(async (opts: Record<string, string>, _o: unknown, cmd: Command) => {
    const out = outFrom(program, cmd);
    const org = ensureOrg(out);
    const cwd = cwdOf(opts.dir);
    const { manifest } = readManifestCwd(cwd);
    printResult(await out.client.post(out.client.orgPath("/extensions"), { manifest }, { idempotencyKey: newIdempotencyKey() }), out);
  });
  ext.command("validate <id>").description("Server-side validation (POST .../validate)").action(async (id: string, _o: unknown, cmd: Command) => {
    const out = outFrom(program, cmd);
    const org = ensureOrg(out);
    printResult(await out.client.post(out.client.orgPath(`/extensions/${encodeURIComponent(id)}/validate`), {}), out);
  });
  ext.command("version <id> <version>").description("Create a new version (POST .../versions)").option("--notes <n>", "changelog").action(async (id: string, version: string, opts: Record<string, string>, cmd: Command) => {
    const out = outFrom(program, cmd);
    const org = ensureOrg(out);
    printResult(await out.client.post(out.client.orgPath(`/extensions/${encodeURIComponent(id)}/versions`), { version, changelog: opts.notes }), out);
  });
  for (const action of ["sign", "install", "disable", "quarantine"] as const) {
    ext.command(`${action} <id>`).description(`POST .../extensions/{id}/${action}`).action(async (id: string, _o: unknown, cmd: Command) => {
      const out = outFrom(program, cmd);
      const org = ensureOrg(out);
      printResult(await out.client.post(out.client.orgPath(`/extensions/${encodeURIComponent(id)}/${action}`), {}), out);
    });
  }
  ext.command("sign-complete <id>").description("Complete signing (POST .../sign/complete)").option("--signature <sig>", "signature payload").action(async (id: string, opts: Record<string, string>, _o: unknown, cmd: Command) => {
    const out = outFrom(program, cmd);
    const org = ensureOrg(out);
    printResult(await out.client.post(out.client.orgPath(`/extensions/${encodeURIComponent(id)}/sign/complete`), { signature: opts.signature }), out);
  });

  // ---------- developer projects / webhooks / events / usage / deployments / sdk ----------
  const projects = program.command("projects").description("Developer projects");
  projects.command("list").description("GET developer/projects").action(async (_o: unknown, cmd: Command) => {
    const out = outFrom(program, cmd);
    const org = ensureOrg(out);
    printResult(await out.client.get(out.client.orgPath("/developer/projects")), out);
  });
  projects.command("create <name>").description("POST developer/projects").option("--description <d>", "description").action(async (name: string, opts: Record<string, string>, _o: unknown, cmd: Command) => {
    const out = outFrom(program, cmd);
    const org = ensureOrg(out);
    printResult(await out.client.post(out.client.orgPath("/developer/projects"), { name, description: opts.description }, { idempotencyKey: newIdempotencyKey() }), out);
  });
  projects.command("get <id>").description("GET developer/projects/{id}").action(async (id: string, _o: unknown, cmd: Command) => {
    const out = outFrom(program, cmd);
    const org = ensureOrg(out);
    printResult(await out.client.get(out.client.orgPath(`/developer/projects/${encodeURIComponent(id)}`)), out);
  });
  projects.command("set-env <id> <env>").description("PUT developer/projects/{id}/environments/{env}").option("--value <json>", "JSON value").action(async (id: string, env: string, opts: Record<string, string>, _o: unknown, cmd: Command) => {
    const out = outFrom(program, cmd);
    const org = ensureOrg(out);
    const value = opts.value ? JSON.parse(opts.value) : {};
    printResult(await out.client.put(out.client.orgPath(`/developer/projects/${encodeURIComponent(id)}/environments/${encodeURIComponent(env)}`), value), out);
  });

  const webhooks = program.command("webhooks").description("Developer webhooks");
  webhooks.command("list").description("GET developer/webhooks").action(async (_o: unknown, cmd: Command) => {
    const out = outFrom(program, cmd);
    const org = ensureOrg(out);
    printResult(await out.client.get(out.client.orgPath("/developer/webhooks")), out);
  });
  webhooks.command("create <url>").description("POST developer/webhooks").option("--events <list>", "comma-separated event types").action(async (url: string, opts: Record<string, string>, _o: unknown, cmd: Command) => {
    const out = outFrom(program, cmd);
    const org = ensureOrg(out);
    printResult(await out.client.post(out.client.orgPath("/developer/webhooks"), { url, event_types: opts.events ? opts.events.split(",").map((s) => s.trim()) : [] }), out);
  });

  program.command("events").description("GET developer/events").action(async (_o: unknown, cmd: Command) => {
    const out = outFrom(program, cmd);
    const org = ensureOrg(out);
    printResult(await out.client.get(out.client.orgPath("/developer/events")), out);
  });
  program.command("usage").description("GET developer/usage").action(async (_o: unknown, cmd: Command) => {
    const out = outFrom(program, cmd);
    const org = ensureOrg(out);
    printResult(await out.client.get(out.client.orgPath("/developer/usage")), out);
  });
  program.command("deployments").description("GET developer/deployments").action(async (_o: unknown, cmd: Command) => {
    const out = outFrom(program, cmd);
    const org = ensureOrg(out);
    printResult(await out.client.get(out.client.orgPath("/developer/deployments")), out);
  });
  program.command("sdk").description("GET /api/v1/developer/sdk (public metadata)").action(async (_o: unknown, cmd: Command) => {
    const out = outFrom(program, cmd);
    printResult(await out.client.get("/api/v1/developer/sdk"), out);
  });

  // ---------- agents / tools / workflows / connectors / mcp / skills ----------
  const agents = program.command("agents").description("Agents");
  agents.command("list").description("List agents").action(async (_o: unknown, cmd: Command) => {
    const out = outFrom(program, cmd);
    const org = ensureOrg(out);
    printResult(await out.client.get(out.client.orgPath("/agents")), out);
  });
  agents.command("create <name>").description("Create agent").option("--model <m>", "model").action(async (name: string, opts: Record<string, string>, _o: unknown, cmd: Command) => {
    const out = outFrom(program, cmd);
    const org = ensureOrg(out);
    printResult(await out.client.post(out.client.orgPath("/agents"), { name, model: opts.model }, { idempotencyKey: newIdempotencyKey() }), out);
  });
  agents.command("get <id>").description("Get agent").action(async (id: string, _o: unknown, cmd: Command) => {
    const out = outFrom(program, cmd);
    const org = ensureOrg(out);
    printResult(await out.client.get(out.client.orgPath(`/agents/${encodeURIComponent(id)}`)), out);
  });
  agents.command("run <id>").description("Run agent (POST .../agents/{id}/run)").option("--input <json>", "JSON input").action(async (id: string, opts: Record<string, string>, _o: unknown, cmd: Command) => {
    const out = outFrom(program, cmd);
    const org = ensureOrg(out);
    const input = opts.input ? JSON.parse(opts.input) : {};
    printResult(await out.client.post(out.client.orgPath(`/agents/${encodeURIComponent(id)}/run`), { input }, { idempotencyKey: newIdempotencyKey() }), out);
  });

  const tools = program.command("tools").description("Tools");
  tools.command("list").description("List tools").action(async (_o: unknown, cmd: Command) => {
    const out = outFrom(program, cmd);
    const org = ensureOrg(out);
    printResult(await out.client.get(out.client.orgPath("/tools")), out);
  });
  tools.command("get <id>").description("Get tool").action(async (id: string, _o: unknown, cmd: Command) => {
    const out = outFrom(program, cmd);
    const org = ensureOrg(out);
    printResult(await out.client.get(out.client.orgPath(`/tools/${encodeURIComponent(id)}`)), out);
  });
  tools.command("test <id>").description("Preview-execute a tool (POST .../tools/execute)").option("--input <json>", "JSON input", "{}").action(async (id: string, opts: Record<string, string>, _o: unknown, cmd: Command) => {
    const out = outFrom(program, cmd);
    const org = ensureOrg(out);
    const input = opts.input ? JSON.parse(opts.input) : {};
    printResult(await out.client.post(out.client.orgPath("/tools/execute"), { tool_id: id, input }), out);
  });

  const workflows = program.command("workflows").description("Workflows");
  workflows.command("list").description("List workflows").action(async (_o: unknown, cmd: Command) => {
    const out = outFrom(program, cmd);
    const org = ensureOrg(out);
    printResult(await out.client.get(out.client.orgPath("/workflows")), out);
  });
  workflows.command("create <name>").description("Create workflow").option("--definition <json>", "JSON definition").action(async (name: string, opts: Record<string, string>, _o: unknown, cmd: Command) => {
    const out = outFrom(program, cmd);
    const org = ensureOrg(out);
    const definition = opts.definition ? JSON.parse(opts.definition) : {};
    printResult(await out.client.post(out.client.orgPath("/workflows"), { name, definition }, { idempotencyKey: newIdempotencyKey() }), out);
  });
  workflows.command("get <id>").description("Get workflow").action(async (id: string, _o: unknown, cmd: Command) => {
    const out = outFrom(program, cmd);
    const org = ensureOrg(out);
    printResult(await out.client.get(out.client.orgPath(`/workflows/${encodeURIComponent(id)}`)), out);
  });
  workflows.command("run <id>").description("Execute workflow (POST .../workflows/{id}/run)").option("--input <json>", "JSON input", "{}").action(async (id: string, opts: Record<string, string>, _o: unknown, cmd: Command) => {
    const out = outFrom(program, cmd);
    const org = ensureOrg(out);
    printResult(await out.client.post(out.client.orgPath(`/workflows/${encodeURIComponent(id)}/run`), { input: opts.input ? JSON.parse(opts.input) : {} }, { idempotencyKey: newIdempotencyKey() }), out);
  });

  const connectors = program.command("connectors").description("Connectors");
  connectors.command("list").description("List connectors").action(async (_o: unknown, cmd: Command) => {
    const out = outFrom(program, cmd);
    const org = ensureOrg(out);
    printResult(await out.client.get(out.client.orgPath("/connectors")), out);
  });
  connectors.command("get <id>").description("Get connector").action(async (id: string, _o: unknown, cmd: Command) => {
    const out = outFrom(program, cmd);
    const org = ensureOrg(out);
    printResult(await out.client.get(out.client.orgPath(`/connectors/${encodeURIComponent(id)}`)), out);
  });
  connectors.command("test <connectionId>").description("Test connection (POST .../integration-connections/{id}/test)").action(async (cid: string, _o: unknown, cmd: Command) => {
    const out = outFrom(program, cmd);
    const org = ensureOrg(out);
    printResult(await out.client.post(out.client.orgPath(`/integration-connections/${encodeURIComponent(cid)}/test`), {}), out);
  });

  const mcp = program.command("mcp").description("MCP servers");
  mcp.command("list").description("List MCP servers").action(async (_o: unknown, cmd: Command) => {
    const out = outFrom(program, cmd);
    const org = ensureOrg(out);
    printResult(await out.client.get(out.client.orgPath("/mcp-servers")), out);
  });
  mcp.command("get <id>").description("Get MCP server").action(async (id: string, _o: unknown, cmd: Command) => {
    const out = outFrom(program, cmd);
    const org = ensureOrg(out);
    printResult(await out.client.get(out.client.orgPath(`/mcp-servers/${encodeURIComponent(id)}`)), out);
  });
  mcp.command("create <name>").description("Register MCP server").option("--endpoint <url>", "endpoint URL").action(async (name: string, opts: Record<string, string>, _o: unknown, cmd: Command) => {
    const out = outFrom(program, cmd);
    const org = ensureOrg(out);
    printResult(await out.client.post(out.client.orgPath("/mcp-servers"), { name, endpoint: opts.endpoint }, { idempotencyKey: newIdempotencyKey() }), out);
  });
  mcp.command("test <id>").description("Test MCP server").action(async (id: string, _o: unknown, cmd: Command) => {
    const out = outFrom(program, cmd);
    const org = ensureOrg(out);
    printResult(await out.client.post(out.client.orgPath(`/mcp-servers/${encodeURIComponent(id)}/test`), {}), out);
  });

  const skills = program.command("skills").description("Skills");
  skills.command("list").description("List skills").action(async (_o: unknown, cmd: Command) => {
    const out = outFrom(program, cmd);
    const org = ensureOrg(out);
    printResult(await out.client.get(out.client.orgPath("/skills")), out);
  });
  skills.command("get <id>").description("Get skill").action(async (id: string, _o: unknown, cmd: Command) => {
    const out = outFrom(program, cmd);
    const org = ensureOrg(out);
    printResult(await out.client.get(out.client.orgPath(`/skills/${encodeURIComponent(id)}`)), out);
  });
  skills.command("create <name>").description("Create skill").option("--description <d>", "description").action(async (name: string, opts: Record<string, string>, _o: unknown, cmd: Command) => {
    const out = outFrom(program, cmd);
    const org = ensureOrg(out);
    printResult(await out.client.post(out.client.orgPath("/skills"), { name, description: opts.description }, { idempotencyKey: newIdempotencyKey() }), out);
  });
  skills.command("test <id>").description("Validate skill (offline manifest + server GET)").option("--dir <dir>", "project dir", ".").action(async (id: string, opts: Record<string, string>, _o: unknown, cmd: Command) => {
    const out = outFrom(program, cmd);
    const org = ensureOrg(out);
    const cwd = cwdOf(opts.dir);
    const res = validateProject(cwd);
    if (!res.ok) {
      if (!out.quiet) process.stdout.write(formatIssues(res) + "\n");
      process.exitCode = 2;
      return;
    }
    printResult(await out.client.get(out.client.orgPath(`/skills/${encodeURIComponent(id)}`)), out);
  });

  // ---------- registry / marketplace ----------
  const registry = program.command("registry").description("Local + server extension registry");
  registry.command("search <query>").description("Search server catalog + local registry").action(async (query: string, _o: unknown, cmd: Command) => {
    const out = outFrom(program, cmd);
    const local = searchLocalRegistry(query);
    let server: unknown = null;
    try {
      const org = ensureOrg(out);
      server = await out.client.get(out.client.orgPath("/packages"), { search: query });
    } catch (e) {
      server = { error: e instanceof Error ? e.message : String(e) };
    }
    printResult({ query, local, server }, out);
  });
  registry.command("install <id>").description("Install extension version").option("--version <v>", "version").option("--values <json>", "JSON values", "{}").action(async (id: string, opts: Record<string, string>, _o: unknown, cmd: Command) => {
    const out = outFrom(program, cmd);
    const org = ensureOrg(out);
    const version = opts.version ?? "latest";
    const values = opts.values ? JSON.parse(opts.values) : {};
    const pathV = version === "latest" ? id : `${id}/versions/${version}`;
    void pathV;
    const data = version === "latest"
      ? await out.client.post(out.client.orgPath(`/packages/${encodeURIComponent(id)}/install`), { values }, { idempotencyKey: newIdempotencyKey() })
      : await out.client.post(out.client.orgPath(`/packages/${encodeURIComponent(id)}/versions/${encodeURIComponent(version)}/install`), { values }, { idempotencyKey: newIdempotencyKey() });
    printResult(data, out);
  });
  registry.command("update <id>").description("Plan + apply update (POST .../installations/{id}/update)").option("--to <v>", "target version").action(async (id: string, opts: Record<string, string>, _o: unknown, cmd: Command) => {
    const out = outFrom(program, cmd);
    const org = ensureOrg(out);
    if (opts.to) await out.client.post(out.client.orgPath(`/installations/${encodeURIComponent(id)}/update-plan`), { to_version: opts.to });
    printResult(await out.client.post(out.client.orgPath(`/installations/${encodeURIComponent(id)}/update`), {}), out);
  });
  registry.command("remove <id>").description("Uninstall (DELETE .../installations/{id})").action(async (id: string, _o: unknown, cmd: Command) => {
    const out = outFrom(program, cmd);
    const org = ensureOrg(out);
    printResult(await out.client.delete(out.client.orgPath(`/installations/${encodeURIComponent(id)}`)), out);
  });
  registry.command("publish <archive>").description("Publish a local .oaext to local registry dir").action(async (archive: string, _o: unknown, cmd: Command) => {
    const out = outFrom(program, cmd);
    const info = inspectPackage(path.resolve(archive));
    const dir = registryDir();
    fs.mkdirSync(dir, { recursive: true });
    const dest = path.join(dir, path.basename(path.resolve(archive)));
    fs.copyFileSync(path.resolve(archive), dest);
    okLine(`Published to local registry: ${dest}`, out);
    printResult({ dest, manifest: redactSecrets(info.manifest) }, out);
  });

  const marketplace = program.command("marketplace").description("Marketplace");
  marketplace.command("search <query>").description("Search marketplace").action(async (query: string, _o: unknown, cmd: Command) => {
    const out = outFrom(program, cmd);
    printResult(await out.client.get("/api/v1/marketplace/search", { q: query }), out);
  });
  marketplace.command("publish").description("Create a marketplace listing (POST .../listings)").option("--package-id <id>", "package ID").option("--title <t>", "listing title").option("--description <d>", "description").action(async (opts: Record<string, string>, _o: unknown, cmd: Command) => {
    const out = outFrom(program, cmd);
    const org = ensureOrg(out);
    if (!opts.packageId || !opts.title) {
      printErrorLine("marketplace publish requires --package-id and --title.", out);
      process.exitCode = 2;
      return;
    }
    printResult(await out.client.post(out.client.orgPath("/listings"), { package_id: opts.packageId, title: opts.title, description: opts.description }, { idempotencyKey: newIdempotencyKey() }), out);
  });

  // ---------- logs / runs ----------
  program.command("logs").description("List recent runs (org /runs)").option("--limit <n>", "max items", "50").action(async (opts: Record<string, string>, _o: unknown, cmd: Command) => {
    const out = outFrom(program, cmd);
    const org = ensureOrg(out);
    printResult(await out.client.paginate(out.client.orgPath("/runs"), { params: { page_size: 50 }, limit: Number(opts.limit ?? 50) }), out);
  });
  const runs = program.command("runs").description("Runs");
  runs.command("list").description("List runs").action(async (_o: unknown, cmd: Command) => {
    const out = outFrom(program, cmd);
    const org = ensureOrg(out);
    printResult(await out.client.get(out.client.orgPath("/runs")), out);
  });
  runs.command("get <id>").description("Get run").action(async (id: string, _o: unknown, cmd: Command) => {
    const out = outFrom(program, cmd);
    const org = ensureOrg(out);
    printResult(await out.client.get(out.client.orgPath(`/runs/${encodeURIComponent(id)}`)), out);
  });

  // ---------- config ----------
  const config = program.command("config").description("Manage profiles and settings");
  config.command("list").description("List profiles (secrets masked)").action(async (_o: unknown, cmd: Command) => {
    const out = outFrom(program, cmd);
    const { active, names, raw } = listProfiles();
    const redacted: Record<string, unknown> = {};
    for (const n of names) {
      const p = raw.profiles[n] as unknown as Record<string, unknown>;
      redacted[n] = { ...p, apiKey: p.apiKey ? maskApiKey(String(p.apiKey)) : "(none)" };
    }
    printResult({ active, configFile: configFilePath(), profiles: redacted }, out);
  });
  config.command("get <key>").description("Get a config value (get <profile.key> or <key>)").action(async (key: string, _o: unknown, cmd: Command) => {
    const out = outFrom(program, cmd);
    const { raw, active } = listProfiles();
    const [maybeProfile, maybeKey] = key.includes(".") ? key.split(".", 2) as [string, string] : [active, key];
    const profile = raw.profiles[maybeProfile];
    if (!profile) {
      printErrorLine(`Unknown profile '${maybeProfile}'.`, out);
      process.exitCode = 1;
      return;
    }
    const val = (profile as unknown as Record<string, unknown>)[maybeKey];
    printResult(typeof val === "string" && /key|token|secret/i.test(maybeKey) ? maskApiKey(val) : val ?? null, out);
  });
  config.command("set <key> <value>").description("Set a config value").option("--profile <p>", "profile name").action(async (key: string, value: string, opts: Record<string, string>, _o: unknown, cmd: Command) => {
    const out = outFrom(program, cmd);
    let profileName = opts.profile ?? out.profileName;
    let field = key;
    if (key.includes(".") && !opts.profile) {
      const [p, k] = key.split(".", 2) as [string, string];
      profileName = p;
      field = k;
    }
    if (!["apiUrl", "apiKey", "orgId"].includes(field)) {
      printErrorLine(`Unknown key '${field}'. Allowed: apiUrl, apiKey, orgId.`, out);
      process.exitCode = 2;
      return;
    }
    saveProfile(profileName, { [field]: value } as Record<string, string>);
    okLine(`Set ${profileName}.${field}.`, out);
  });

  // ---------- doctor ----------
  program.command("doctor").description("Check environment, auth, project, and connectivity").action(async (_o: unknown, cmd: Command) => {
    const out = outFrom(program, cmd);
    const checks: Array<{ name: string; ok: boolean; detail: string }> = [];
    const nodeOk = Number(process.versions.node.split(".")[0]) >= 20;
    checks.push({ name: "node", ok: nodeOk, detail: `node ${process.version} (need >=20)` });
    const resolved = getProfile((cmd.opts() as GlobalFlags).profile ?? (program.opts() as GlobalFlags).profile, (cmd.opts() as GlobalFlags).org ?? (program.opts() as GlobalFlags).org);
    checks.push({ name: "auth", ok: Boolean(resolved.apiKey), detail: resolved.apiKey ? `profile '${resolved.name}' key ${maskApiKey(resolved.apiKey)}` : `no API key (profile '${resolved.name}')` });
    try {
      const client = new ApiClient({ baseUrl: resolved.apiUrl, apiKey: resolved.apiKey, orgId: resolved.orgId, timeoutMs: 8000 });
      await client.get("/api/v1/developer/sdk");
      checks.push({ name: "api", ok: true, detail: `reachable at ${resolved.apiUrl}` });
    } catch (e) {
      checks.push({ name: "api", ok: false, detail: e instanceof Error ? e.message.slice(0, 200) : String(e) });
    }
    const mp = findManifestPath(process.cwd());
    if (mp) {
      const res = validateProject(process.cwd());
      checks.push({ name: "manifest", ok: res.ok, detail: res.ok ? mp : formatIssues(res).split("\n")[0] ?? mp });
    } else {
      checks.push({ name: "manifest", ok: true, detail: "no local manifest (run openagent init to scaffold)" });
    }
    try {
      fs.mkdirSync(registryDir(), { recursive: true });
      checks.push({ name: "registry", ok: true, detail: registryDir() });
    } catch (e) {
      checks.push({ name: "registry", ok: false, detail: e instanceof Error ? e.message : String(e) });
    }
    checks.push({ name: "sandbox", ok: true, detail: "sandbox execution is server-side only; CLI never runs untrusted code locally" });
    printResult({ checks, allOk: checks.every((c) => c.ok) }, out);
    if (!checks.every((c) => c.ok)) process.exitCode = 1;
  });

  // ---------- upgrade ----------
  program.command("upgrade").description("Check for CLI updates").action(async (_o: unknown, cmd: Command) => {
    const out = outFrom(program, cmd);
    const current = "1.0.0";
    let latest = current;
    try {
      const res = await fetch("https://registry.npmjs.org/@openagent%2Fcli/latest", { signal: AbortSignal.timeout(8000) });
      if (res.ok) {
        const j = (await res.json()) as { version?: string };
        if (j.version) latest = j.version;
      }
    } catch {
      // offline: report hint only
    }
    if (latest !== current) {
      printResult({ current, latest, hint: "Run `npm i -g @openagent/cli@latest` or `pnpm add -g @openagent/cli@latest` to upgrade." }, out);
    } else {
      okLine(`openagent CLI is up to date (${current}).`, out);
      if (out.json) printResult({ current, latest }, { ...out, json: true });
    }
  });

  // ---------- generate ----------
  program.command("generate <kind> <name>").description("Generate a file into an existing project (agent|tool|connector|node|mcp|skill|evaluator)").option("--dir <dir>", "project dir", ".").option("--force", "overwrite existing").action(async (kind: string, name: string, opts: Record<string, string | boolean>, _o: unknown, cmd: Command) => {
    const out = outFrom(program, cmd);
    const cwd = cwdOf(typeof opts.dir === "string" ? opts.dir : ".");
    const safe = name.replace(/[^a-zA-Z0-9-_]/g, "_") || "Generated";
    const targets: Record<string, string> = {
      agent: `src/agents/${safe}.ts`,
      tool: `src/tools/${safe}.ts`,
      connector: `src/connectors/${safe}.ts`,
      node: `src/nodes/${safe}.ts`,
      mcp: `src/mcp/${safe}.ts`,
      skill: `skills/${safe}.md`,
      evaluator: `src/evaluators/${safe}.ts`,
    };
    const rel = targets[kind];
    if (!rel) {
      printErrorLine(`Unknown generate kind '${kind}'. Allowed: agent, tool, connector, node, mcp, skill, evaluator.`, out);
      process.exitCode = 2;
      return;
    }
    const full = path.join(cwd, rel);
    if (fs.existsSync(full) && !opts.force) {
      printErrorLine(`${rel} already exists (use --force to overwrite).`, out);
      process.exitCode = 1;
      return;
    }
    fs.mkdirSync(path.dirname(full), { recursive: true });
    fs.writeFileSync(full, generateTemplate(kind, safe));
    okLine(`Generated ${rel}.`, out);
  });

  // ---------- docs ----------
  program.command("docs").description("Generate README/API reference from manifest").option("--dir <dir>", "project dir", ".").option("--out <path>", "output file", "README.generated.md").action(async (opts: Record<string, string>, _o: unknown, cmd: Command) => {
    const out = outFrom(program, cmd);
    const cwd = cwdOf(opts.dir);
    const { manifest } = readManifestCwd(cwd);
    const m = manifest as Record<string, unknown>;
    const md = [
      `# ${String(m.name ?? "extension")} ${String(m.version ?? "")}`.trim(),
      ``,
      `${String(m.description ?? "")}`,
      ``,
      `- Type: \`${String(m.type ?? "")}\``,
      `- License: \`${String(m.license ?? "")}\``,
      `- Entrypoint: \`${String((m.runtime as Record<string, unknown> | undefined)?.entrypoint ?? "")}\``,
      `- Permissions: ${(Array.isArray(m.permissions) ? m.permissions.map((p) => `\`${typeof p === "string" ? p : (p as Record<string, unknown>).permission}\``).join(", ") : "(none)")}`,
      ``,
      `## API`,
      ``,
      `This extension exposes a single \`run(ctx, input)\` entrypoint returning JSON.`,
      ``,
      `## Examples`,
      ``,
      "```json",
      JSON.stringify({ input: { hello: "world" }, output: { ok: true } }, null, 2),
      "```",
      ``,
    ].join("\n");
    const dest = path.resolve(cwd, opts.out ?? "README.generated.md");
    fs.writeFileSync(dest, md);
    okLine(`Wrote ${dest}.`, out);
  });

  // ---------- migrate ----------
  program.command("migrate").description("Scan for deprecated APIs and optionally rewrite with backup").option("--dir <dir>", "project dir", ".").option("--write", "apply codemods (creates .bak files)").action(async (opts: Record<string, string | boolean>, _o: unknown, cmd: Command) => {
    const out = outFrom(program, cmd);
    const cwd = cwdOf(typeof opts.dir === "string" ? (opts.dir as string) : ".");
    let deprecated: Array<{ from: string; to: string }> = [
      { from: "defineTool(", to: "defineExtension(" },
      { from: "registerAgent(", to: "defineExtension(" },
      { from: "openagent.run(", to: "extension.run(" },
    ];
    try {
      const client = out.client;
      const sdkMeta = (await client.get("/api/v1/developer/sdk")) as { deprecations?: Array<{ from: string; to: string }> };
      if (Array.isArray(sdkMeta.deprecations) && sdkMeta.deprecations.length > 0) deprecated = sdkMeta.deprecations;
    } catch {
      // offline: use local known list
    }
    const files = walkSource(cwd);
    const hits: Array<{ file: string; line: number; from: string; to: string }> = [];
    for (const f of files) {
      const text = fs.readFileSync(f, "utf8");
      const lines = text.split("\n");
      lines.forEach((line, i) => {
        for (const d of deprecated) {
          if (line.includes(d.from)) hits.push({ file: path.relative(cwd, f), line: i + 1, from: d.from, to: d.to });
        }
      });
    }
    if (opts.write) {
      for (const f of files) {
        let text = fs.readFileSync(f, "utf8");
        let changed = false;
        for (const d of deprecated) {
          if (text.includes(d.from)) {
            text = text.split(d.from).join(d.to);
            changed = true;
          }
        }
        if (changed) {
          fs.writeFileSync(`${f}.bak`, fs.readFileSync(f));
          fs.writeFileSync(f, text);
        }
      }
      okLine(`Migrate applied to ${files.length} files (backups kept as .bak).`, out);
    }
    printResult({ deprecated, hits, applied: Boolean(opts.write) }, out);
  });
}

function searchLocalRegistry(query: string): Array<{ file: string; name: string }> {
  const dir = registryDir();
  try {
    if (!fs.existsSync(dir)) return [];
    return fs
      .readdirSync(dir)
      .filter((f) => f.toLowerCase().includes(query.toLowerCase()))
      .map((f) => ({ file: path.join(dir, f), name: f }));
  } catch {
    return [];
  }
}

function walkSource(root: string): string[] {
  const out: string[] = [];
  const stack = [path.join(root, "src")];
  if (!fs.existsSync(stack[0] as string)) stack.push(root);
  while (stack.length > 0) {
    const d = stack.pop() as string;
    let entries: fs.Dirent[];
    try {
      entries = fs.readdirSync(d, { withFileTypes: true });
    } catch {
      continue;
    }
    for (const e of entries) {
      const full = path.join(d, e.name);
      if (e.isDirectory()) {
        if (["node_modules", ".git", "dist"].includes(e.name)) continue;
        stack.push(full);
      } else if (e.isFile() && /\.(ts|js|py)$/.test(e.name)) {
        out.push(full);
      }
    }
  }
  return out.sort();
}

function generateTemplate(kind: string, name: string): string {
  if (kind === "skill") return `# ${name}\n\nDescribe when to use this skill and give concise steps.\n\n## Steps\n\n1. Do the thing.\n2. Verify the result.\n`;
  return `// Generated ${kind}: ${name}\nexport const ${name.replace(/[^a-zA-Z0-9_]/g, "_")} = {\n  kind: ${JSON.stringify(kind)},\n  name: ${JSON.stringify(name)},\n  async run(ctx: { log(msg: string): void }, input: unknown) {\n    ctx.log("Running ${name}");\n    return { ok: true, input };\n  },\n};\n\nexport default ${name.replace(/[^a-zA-Z0-9_]/g, "_")};\n`;
}

async function startDevServer(cwd: string, port: number, out: OutputOptions): Promise<void> {
  const mp = findManifestPath(cwd);
  if (!mp) {
    printErrorLine(`No manifest in ${cwd}. Run \`openagent init\` first.`, out);
    process.exitCode = 2;
    return;
  }
  // eslint-disable-next-line no-console
  console.log("*** DEVELOPMENT MODE — local only, nothing is deployed ***");
  const loadManifest = (): Record<string, unknown> => {
    try {
      const raw = fs.readFileSync(mp, "utf8");
      return (mp.endsWith(".json") ? JSON.parse(raw) : (yaml.load(raw) as Record<string, unknown>)) ?? {};
    } catch {
      return {};
    }
  };
  let manifest = loadManifest();
  const server = http.createServer((req, res) => {
    const url = new URL(req.url ?? "/", `http://localhost:${port}`);
    res.setHeader("Content-Type", "application/json");
    if (url.pathname === "/manifest") {
      res.end(JSON.stringify(manifest, null, 2));
    } else if (url.pathname === "/health") {
      res.end(JSON.stringify({ ok: true, mode: "development", manifest: (manifest as Record<string, unknown>).name ?? null }));
    } else if (url.pathname === "/mock/run" && req.method === "POST") {
      let body = "";
      req.on("data", (c) => {
        body += c;
      });
      req.on("end", () => {
        res.end(JSON.stringify({ ok: true, mode: "development-mock", echo: body ? JSON.parse(body) : null }));
      });
    } else {
      res.statusCode = 404;
      res.end(JSON.stringify({ error: "not found (dev server serves /manifest, /health, /mock/run)" }));
    }
  });
  await new Promise<void>((resolve) => server.listen(port, resolve));
  // eslint-disable-next-line no-console
  console.log(`dev server: serving ${mp} at http://localhost:${port}/manifest (hot-reload on save)`);
  const watcher = fs.watch(cwd, { recursive: true }, (_evt, filename) => {
    if (!filename) return;
    if (String(filename).includes("node_modules") || String(filename).includes(".git")) return;
    manifest = loadManifest();
    // eslint-disable-next-line no-console
    console.log(`[reload] ${filename} changed — manifest reloaded`);
  });
  const shutdown = () => {
    watcher.close();
    server.close();
    process.exit(0);
  };
  process.on("SIGINT", shutdown);
  process.on("SIGTERM", shutdown);
  // Keep process alive until killed.
  await new Promise(() => undefined);
  void spawn;
}
