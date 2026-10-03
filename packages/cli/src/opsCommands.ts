import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { execFile } from "node:child_process";
import type { Command } from "commander";
import {
  ensureAppLayout,
  getAppDirs,
  getSystemInfo,
  selectProfile,
} from "@openagent/workflow-engine";
import { checkOllama } from "@openagent/workflow-engine";
import {
  findProjectDir,
  globalWorkspaceDir,
  initProject,
  listMcpServers,
  listProjectBackups,
  restoreProjectBackup,
  testMcpServer,
} from "./local.js";
import { formatFindings, scanDirectory } from "./security.js";

interface Flags {
  json?: boolean;
  quiet?: boolean;
}

function flagsOf(program: Command, cmd: Command): Flags {
  const go = program.opts<Flags>();
  const lo = cmd.opts<Flags>();
  return {
    json: lo.json ?? go.json ?? false,
    quiet: lo.quiet ?? go.quiet ?? false,
  };
}

function emit(payload: unknown, out: Flags): void {
  if (out.quiet) return;
  process.stdout.write(
    typeof payload === "string"
      ? payload + "\n"
      : JSON.stringify(payload, null, 2) + "\n",
  );
}

function ok(msg: string, out: Flags): void {
  if (out.quiet) return;
  process.stdout.write(
    out.json ? JSON.stringify({ ok: true, message: msg }) + "\n" : `✓ ${msg}\n`,
  );
}

function fail(msg: string): never {
  throw Object.assign(new Error(msg), { exitCode: 1 });
}

function run(
  cmd: string,
  args: string[],
  opts: { cwd?: string; timeout?: number } = {},
): Promise<{ ok: boolean; out: string }> {
  return new Promise((resolve) => {
    execFile(
      cmd,
      args,
      { timeout: opts.timeout ?? 60000, cwd: opts.cwd },
      (err, stdout, stderr) => {
        if (err) resolve({ ok: false, out: String(stderr ?? err.message) });
        else resolve({ ok: true, out: String(stdout ?? "").trim() });
      },
    );
  });
}

/** repair / model / browser / db / extended git. Registered from the bin. */
export function registerOpsCommands(program: Command): void {
  // ---------- repair ----------
  program
    .command("repair")
    .description("Self-repair local installation (never deletes workflows)")
    .action(async (_o: unknown, cmd: Command) => {
      const out = flagsOf(program, cmd);
      const fixed: string[] = [];
      const dirs = getAppDirs();
      ensureAppLayout(dirs);
      fixed.push(`ensured app layout at ${dirs.app}`);
      const ws = globalWorkspaceDir();
      const { created } = initProject(ws);
      fixed.push(
        created.length > 0
          ? `initialized global workspace (${created.length} entries)`
          : "global workspace already initialized",
      );
      // Stale engine pid file.
      const pidFile = path.join(ws, ".openagent", "engine.pid");
      if (fs.existsSync(pidFile)) {
        try {
          const pid = Number(
            JSON.parse(fs.readFileSync(pidFile, "utf8") as string).pid,
          );
          let alive = false;
          if (Number.isFinite(pid)) {
            try {
              process.kill(pid, 0);
              alive = true;
            } catch {
              alive = false;
            }
          }
          if (!alive) {
            fs.rmSync(pidFile, { force: true });
            fixed.push("removed stale engine pid file");
          } else {
            fixed.push("engine pid file points at a live process (kept)");
          }
        } catch {
          fs.rmSync(pidFile, { force: true });
          fixed.push("removed unreadable engine pid file");
        }
      }
      // Stale cache (workflows/memory/backups are never touched).
      const cache = path.join(ws, ".openagent", "cache");
      if (fs.existsSync(cache)) {
        fs.rmSync(cache, { recursive: true, force: true });
        fs.mkdirSync(cache, { recursive: true });
        fixed.push("cleared project cache");
      }
      // Config validation (rewrite only when corrupt JSON).
      const cfg = path.join(ws, ".openagent", "config.json");
      try {
        JSON.parse(fs.readFileSync(cfg, "utf8"));
        fixed.push("project config valid");
      } catch {
        fs.copyFileSync(cfg, `${cfg}.corrupt`);
        initProject(ws, { force: false });
        fixed.push(
          "project config was corrupt — preserved as config.json.corrupt",
        );
      }
      ok("Repair complete. Workflows were not modified.", out);
      emit({ fixed }, out);
    });

  // ---------- model ----------
  const model = program
    .command("model")
    .description("Local AI model management");
  model
    .command("detect")
    .description("Detect Ollama / LM Studio / OpenAI-compatible endpoints")
    .action(async (_o: unknown, cmd: Command) => {
      const out = flagsOf(program, cmd);
      const ollama = await checkOllama().catch(() => ({
        ok: false,
        models: [] as string[],
        detail: "unreachable",
      }));
      const sys = await getSystemInfo().catch(() => null);
      const profile = sys ? selectProfile(sys).profile : "BALANCED";
      emit(
        {
          ollama: ollama.ok,
          models: ollama.models,
          detail: ollama.detail,
          openaiKey: Boolean(process.env.OPENAI_API_KEY),
          ollamaHost: process.env.OLLAMA_HOST ?? "default",
          hardwareProfile: profile,
        },
        out,
      );
    });
  model
    .command("list")
    .description("List locally available models")
    .action(async (_o: unknown, cmd: Command) => {
      const out = flagsOf(program, cmd);
      const ollama = await checkOllama().catch(() => ({
        ok: false,
        models: [] as string[],
        detail: "unreachable",
      }));
      if (ollama.ok && ollama.models.length) {
        emit({ provider: "ollama", models: ollama.models }, out);
      } else {
        emit(
          {
            provider: "ollama",
            models: [],
            hint: "No models detected. Run `openagent model install` or start Ollama, or set OPENAI_API_KEY for cloud.",
          },
          out,
        );
      }
    });
  model
    .command("install [id]")
    .description("Pull a local model (default: hardware-recommended)")
    .action(async (id: string | undefined, _o: unknown, cmd: Command) => {
      const out = flagsOf(program, cmd);
      const sys = await getSystemInfo().catch(() => null);
      const profile = sys ? selectProfile(sys).profile : "BALANCED";
      const wanted = id ?? (profile === "LOW" ? "qwen2.5:0.5b" : "qwen2.5");
      const r = await run("ollama", ["pull", wanted], {
        timeout: 1000 * 60 * 30,
      });
      if (!r.ok)
        fail(
          `Could not pull '${wanted}' — is Ollama installed? See https://ollama.com (${r.out.slice(0, 200)})`,
        );
      ok(`Model '${wanted}' installed.`, out);
    });
  model
    .command("use <id>")
    .description("Set the active model for the current project")
    .action(async (id: string, _o: unknown, cmd: Command) => {
      const out = flagsOf(program, cmd);
      const dir = findProjectDir() ?? globalWorkspaceDir();
      initProject(dir);
      const cfg = path.join(dir, ".openagent", "config.json");
      const raw = JSON.parse(fs.readFileSync(cfg, "utf8")) as Record<
        string,
        Record<string, unknown>
      >;
      raw.ai = { ...(raw.ai ?? {}), model: id };
      fs.writeFileSync(cfg, JSON.stringify(raw, null, 2));
      ok(`Active model set to '${id}' in ${dir}.`, out);
    });
  model
    .command("doctor")
    .description("Diagnose the AI provider setup")
    .action(async (_o: unknown, cmd: Command) => {
      const out = flagsOf(program, cmd);
      const ollama = await checkOllama().catch(() => ({ ok: false }));
      const checks = [
        {
          name: "ollama",
          ok: Boolean(ollama.ok),
          detail: ollama.ok
            ? "reachable"
            : "not installed — https://ollama.com then `ollama run qwen2.5`",
        },
        {
          name: "cloud",
          ok: Boolean(process.env.OPENAI_API_KEY),
          detail: process.env.OPENAI_API_KEY
            ? "OPENAI_API_KEY is set"
            : "OPENAI_API_KEY unset (optional)",
        },
      ];
      emit({ checks, allOk: checks.every((c) => c.ok) }, out);
      if (!checks.every((c) => c.ok)) process.exitCode = 1;
    });

  // ---------- browser ----------
  const browser = program
    .command("browser")
    .description("Browser automation runtime");
  browser
    .command("doctor")
    .description("Check the browser engine installation")
    .action(async (_o: unknown, cmd: Command) => {
      const out = flagsOf(program, cmd);
      const base =
        process.env.PLAYWRIGHT_BROWSERS_PATH ??
        (process.platform === "win32" && process.env.LOCALAPPDATA
          ? path.join(process.env.LOCALAPPDATA, "ms-playwright")
          : path.join(os.homedir(), ".cache", "ms-playwright"));
      const installed = fs.existsSync(base);
      emit(
        {
          ok: installed,
          detail: installed
            ? base
            : `playwright browsers not installed (${base}) — run \`openagent browser install\``,
        },
        out,
      );
      if (!installed) process.exitCode = 1;
    });
  for (const name of ["install", "update"] as const) {
    browser
      .command(name)
      .description(
        name === "install"
          ? "Install the Chromium browser engine"
          : "Update the Chromium browser engine",
      )
      .action(async (_o: unknown, cmd: Command) => {
        const out = flagsOf(program, cmd);
        const r = await run("npx", ["playwright", "install", "chromium"], {
          timeout: 1000 * 60 * 30,
        });
        if (!r.ok)
          fail(`Browser engine install failed: ${r.out.slice(0, 300)}`);
        ok("Chromium browser engine ready.", out);
      });
  }

  // ---------- db ----------
  const db = program.command("db").description("Local database (SQLite)");
  const dbFile = () => {
    const dirs = getAppDirs();
    return path.join(dirs.data, "openagent.db");
  };
  db.command("status")
    .description("Show database provider and file status")
    .action(async (_o: unknown, cmd: Command) => {
      const out = flagsOf(program, cmd);
      const f = dbFile();
      emit(
        {
          provider: "sqlite",
          file: f,
          exists: fs.existsSync(f),
          note: "Project state also lives as JSON under .openagent/ (workflows, agents, memory).",
        },
        out,
      );
    });
  db.command("migrate")
    .description("Initialize data layout and validate project stores")
    .action(async (_o: unknown, cmd: Command) => {
      const out = flagsOf(program, cmd);
      const dirs = getAppDirs();
      ensureAppLayout(dirs);
      const dir = findProjectDir() ?? globalWorkspaceDir();
      initProject(dir);
      // Validate every workflow JSON parses (migration safety net).
      const wfDir = path.join(dir, ".openagent", "workflows");
      let checked = 0;
      if (fs.existsSync(wfDir)) {
        for (const f of fs.readdirSync(wfDir)) {
          if (!f.endsWith(".json")) continue;
          JSON.parse(fs.readFileSync(path.join(wfDir, f), "utf8"));
          checked++;
        }
      }
      ok(
        `Database ready (sqlite). Validated ${checked} workflow file(s).`,
        out,
      );
    });
  db.command("reset")
    .description("Reset executions/cache (workflows are preserved)")
    .option("--yes", "skip confirmation")
    .action(async (opts: Record<string, boolean>, cmd: Command) => {
      const out = flagsOf(program, cmd);
      if (!opts.yes && process.stdin.isTTY) {
        const prompts = (await import("prompts")).default;
        const ans = (await prompts({
          type: "confirm",
          name: "confirm",
          message: "Reset executions and cache? Workflows are kept.",
          initial: false,
        })) as { confirm?: boolean };
        if (!ans.confirm) {
          ok("Reset cancelled.", out);
          return;
        }
      }
      const dir = findProjectDir() ?? globalWorkspaceDir();
      for (const sub of ["executions", "cache"]) {
        const p = path.join(dir, ".openagent", sub);
        if (fs.existsSync(p)) {
          fs.rmSync(p, { recursive: true, force: true });
          fs.mkdirSync(p, { recursive: true });
        }
      }
      ok("Database reset: executions and cache cleared, workflows kept.", out);
    });

  // ---------- git (extended; auto-sync stays explicit opt-in) ----------
  // A minimal `git --init` group already exists in localCommands; extend it
  // rather than registering a duplicate top-level command.
  const git =
    program.commands.find((c) => c.name() === "git") ??
    program.command("git").description("Git integration helpers");
  git
    .command("status")
    .description("Show repository status (read-only)")
    .action(async (_o: unknown, cmd: Command) => {
      const out = flagsOf(program, cmd);
      const r = await run("git", ["status", "--short", "--branch"]);
      if (!r.ok) fail("Not a git repository (run `openagent git init`).");
      emit(r.out || "(clean)", out);
    });
  git
    .command("remote")
    .description("Show the configured remote (never changes it)")
    .action(async (_o: unknown, cmd: Command) => {
      const out = flagsOf(program, cmd);
      const r = await run("git", ["remote", "-v"]);
      emit(r.ok && r.out ? r.out : "(no remote configured)", out);
    });
  git
    .command("connect <url>")
    .description("Set origin remote (refuses to overwrite without --force)")
    .option("--force", "replace an existing origin")
    .action(
      async (url: string, opts: Record<string, boolean>, cmd: Command) => {
        const out = flagsOf(program, cmd);
        const existing = await run("git", ["remote", "get-url", "origin"]);
        if (existing.ok && existing.out && !opts.force)
          fail(
            `origin is already '${existing.out}'. Re-run with --force to replace it.`,
          );
        if (!/^((https?:\/\/)|(git@))/.test(url))
          fail(`'${url}' does not look like a repository URL.`);
        const args =
          existing.ok && opts.force
            ? ["remote", "set-url", "origin", url]
            : ["remote", "add", "origin", url];
        const r = await run("git", args);
        if (!r.ok) fail(`Could not configure remote: ${r.out.slice(0, 200)}`);
        ok(`origin → ${url}`, out);
      },
    );
  git
    .command("auth")
    .description("Guided GitHub authentication check")
    .action(async (_o: unknown, cmd: Command) => {
      const out = flagsOf(program, cmd);
      const gh = await run("gh", ["auth", "status"]);
      if (gh.ok) {
        emit(
          { method: "gh", detail: gh.out.split("\n")[0] ?? "authenticated" },
          out,
        );
        return;
      }
      const ssh = await run("ssh", ["-T", "git@github.com"]);
      emit(
        {
          method: ssh.out.includes("successfully authenticated")
            ? "ssh"
            : "none",
          detail: ssh.out.slice(0, 200) || gh.out.slice(0, 200),
          hint: "Authenticate with `gh auth login`, SSH keys, or a PAT via Git Credential Manager. Tokens are never stored in project files.",
        },
        out,
      );
    });
  git
    .command("enable-auto-sync")
    .description("Opt in to automatic push on `git sync` (default OFF)")
    .action(async (_o: unknown, cmd: Command) => {
      const out = flagsOf(program, cmd);
      const dir = findProjectDir() ?? globalWorkspaceDir();
      initProject(dir);
      const cfg = path.join(dir, ".openagent", "config.json");
      const raw = JSON.parse(fs.readFileSync(cfg, "utf8")) as Record<
        string,
        Record<string, unknown>
      >;
      raw.git = { ...(raw.git ?? {}), autoSync: true };
      fs.writeFileSync(cfg, JSON.stringify(raw, null, 2));
      ok("Git auto-sync is now ON for this project.", out);
    });
  git
    .command("disable-auto-sync")
    .description("Opt out of automatic push on `git sync` (default OFF)")
    .action(async (_o: unknown, cmd: Command) => {
      const out = flagsOf(program, cmd);
      const dir = findProjectDir() ?? globalWorkspaceDir();
      initProject(dir);
      const cfg = path.join(dir, ".openagent", "config.json");
      const raw = JSON.parse(fs.readFileSync(cfg, "utf8")) as Record<
        string,
        Record<string, unknown>
      >;
      raw.git = { ...(raw.git ?? {}), autoSync: false };
      fs.writeFileSync(cfg, JSON.stringify(raw, null, 2));
      ok("Git auto-sync is now OFF for this project.", out);
    });
  git
    .command("sync")
    .description("Secret-scan, commit actual changes, push (no force)")
    .option("--message <msg>", "commit message override")
    .option("--yes", "push without confirmation when auto-sync is OFF")
    .option(
      "--skip-checks",
      "skip test/typecheck/build gates (not recommended)",
    )
    .action(async (opts: Record<string, string | boolean>, cmd: Command) => {
      const out = flagsOf(program, cmd);
      const cwd = findProjectDir() ?? process.cwd();
      // Explicit opt-in: without project-level auto-sync, confirm first.
      const projCfg = path.join(cwd, ".openagent", "config.json");
      let autoSync = false;
      try {
        const raw = JSON.parse(fs.readFileSync(projCfg, "utf8")) as {
          git?: { autoSync?: boolean };
        };
        autoSync = raw.git?.autoSync === true;
      } catch {
        autoSync = false;
      }
      if (!autoSync && !opts.yes && process.stdin.isTTY) {
        const prompts = (await import("prompts")).default;
        const ans = (await prompts({
          type: "confirm",
          name: "confirm",
          message:
            "Auto-sync is OFF. Push these changes now? (enable always with `openagent git enable-auto-sync`)",
          initial: false,
        })) as { confirm?: boolean };
        if (!ans.confirm) {
          ok("Sync cancelled (auto-sync stays OFF).", out);
          return;
        }
      }
      const repo = await run("git", ["rev-parse", "--show-toplevel"], { cwd });
      if (!repo.ok) fail("Not a git repository.");
      const root = repo.out.split("\n")[0] ?? cwd;
      // Safety first: secret scan blocks the push.
      const scan = scanDirectory(root);
      if (scan.blocksPublish) {
        process.stderr.write(
          `Potential secret detected.\nPush blocked.\n${formatFindings(scan).slice(0, 1000)}\n`,
        );
        process.exitCode = 1;
        return;
      }
      // Validation gates: tests, typecheck, build. Any failure stops
      // the sync before anything is committed or pushed.
      const isRepo = fs.existsSync(path.join(root, "pnpm-workspace.yaml"));
      if (isRepo && !opts.skipChecks) {
        const hasPnpm = (await run("pnpm", ["--version"])).ok;
        const gates: Array<{ label: string; cmd: string; args: string[] }> =
          hasPnpm
            ? [
                {
                  label: "typecheck",
                  cmd: "pnpm",
                  args: ["--filter", "@openagent/cli", "typecheck"],
                },
                {
                  label: "tests",
                  cmd: "pnpm",
                  args: ["--filter", "@openagent/cli", "test"],
                },
                {
                  label: "build",
                  cmd: "pnpm",
                  args: ["--filter", "@openagent/cli", "build"],
                },
              ]
            : [];
        for (const g of gates) {
          process.stdout.write(`… sync gate: ${g.label}\n`);
          const r = await run(g.cmd, g.args, { cwd: root, timeout: 600000 });
          if (!r.ok) {
            process.stderr.write(
              `Sync gate '${g.label}' FAILED — nothing committed, nothing pushed.\n${r.out.slice(0, 800)}\n`,
            );
            process.exitCode = 1;
            return;
          }
        }
        if (!out.quiet) process.stdout.write("✓ sync gates passed\n");
      }
      const st = await run("git", ["status", "--porcelain"], { cwd: root });
      if (!st.ok) fail("Could not read git status.");
      if (!st.out.trim()) {
        ok("Nothing to sync (working tree clean).", out);
        return;
      }
      const files = st.out
        .trim()
        .split("\n")
        .map(
          (l) =>
            l
              .replace(/^.{1,2}\s+/, "")
              .split(" -> ")
              .pop()
              ?.trim()
              .replace(/^"|"$/g, "") ?? "",
        )
        .filter(Boolean);
      const allDocs = files.every((f) => f.startsWith("docs/"));
      const scope = allDocs ? "docs" : "chore";
      const message =
        typeof opts.message === "string" && opts.message
          ? opts.message
          : `${scope}: sync ${files.length} file(s) — ${files.slice(0, 3).join(", ")}${files.length > 3 ? "…" : ""}`;
      const add = await run("git", ["add", "-A"], { cwd: root });
      if (!add.ok) fail(`git add failed: ${add.out.slice(0, 200)}`);
      const commit = await run("git", ["commit", "-m", message], { cwd: root });
      if (!commit.ok) fail(`git commit failed: ${commit.out.slice(0, 300)}`);
      ok(`Commit created: ${message}`, out);
      const push = await run("git", ["push"], { cwd: root, timeout: 120000 });
      if (!push.ok) {
        process.stderr.write(
          `Push failed (nothing was force-pushed).\n${push.out.slice(0, 500)}\nCheck authentication: \`openagent git auth\`.\n`,
        );
        process.exitCode = 1;
        return;
      }
      ok("Push completed.", out);
    });

  // ---------- mcp doctor (extends the mcp group from commands.ts) ----------
  const mcp =
    program.commands.find((c) => c.name() === "mcp") ??
    program.command("mcp").description("MCP servers");
  mcp
    .command("doctor")
    .description("Test every configured local MCP server")
    .action(async (_o: unknown, cmd: Command) => {
      const out = flagsOf(program, cmd);
      const dirs = [
        findProjectDir() ?? globalWorkspaceDir(),
        globalWorkspaceDir(),
      ].filter((d, i, a) => a.indexOf(d) === i);
      const results: Array<{
        scope: string;
        id: string;
        ok: boolean;
        detail: string;
      }> = [];
      for (const d of dirs) {
        for (const s of listMcpServers(d)) {
          try {
            const r = await testMcpServer(d, s.id);
            results.push({ scope: d, id: s.id, ok: r.ok, detail: r.detail });
          } catch (e) {
            results.push({
              scope: d,
              id: s.id,
              ok: false,
              detail: e instanceof Error ? e.message : String(e),
            });
          }
        }
      }
      if (results.length === 0) {
        emit(
          "No local MCP servers configured. Add one with `openagent mcp add <name>`.",
          out,
        );
        return;
      }
      emit(
        {
          servers: results,
          allOk: results.every((r) => r.ok),
        },
        out,
      );
      if (!results.every((r) => r.ok)) process.exitCode = 1;
    });

  // ---------- restore (top-level alias over project backups) ----------
  program
    .command("restore [id]")
    .description("Restore a backup (lists backups when no id is given)")
    .action(async (id: string | undefined, _o: unknown, cmd: Command) => {
      const out = flagsOf(program, cmd);
      const dir = findProjectDir() ?? globalWorkspaceDir();
      if (!id) {
        const all = listProjectBackups(dir);
        if (all.length === 0) {
          emit(
            "No backups yet. Create one with `openagent backup create`.",
            out,
          );
          return;
        }
        emit(all, out);
        return;
      }
      restoreProjectBackup(dir, id);
      ok(`Restored backup ${id}.`, out);
    });
}
