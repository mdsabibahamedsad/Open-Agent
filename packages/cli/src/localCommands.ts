import fs from "node:fs";
import path from "node:path";
import type { Command } from "commander";
import {
  createSchedule,
  deleteSchedule,
  findProjectDir,
  getWorkflowLocal,
  initProject,
  installNodePackage,
  listAgentsLocal,
  listExecutionsLocal,
  listInstalledNodes,
  listMcpServers,
  listNodesLocal,
  listSchedules,
  listWorkflowsLocal,
  memoryGet,
  memorySearch,
  memorySet,
  persistExecution as _persist,
  projectPort,
  requireProjectDir,
  runAgentLocal,
  runWorkflowLocal,
  saveWorkflowLocal,
  deleteWorkflowLocal,
  scaffoldNode,
  startLocalPlatform,
  addMcpServer,
  removeMcpServer,
  testMcpServer,
} from "./local.js";
import {
  generateWorkflowFromPrompt,
  getTemplate,
  listTemplates,
  validateWorkflow,
} from "@openagent/workflow-engine";

void _persist;
void projectPort;

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
  if (out.json) {
    process.stdout.write(JSON.stringify(payload, null, 2) + "\n");
    return;
  }
  if (typeof payload === "string") {
    process.stdout.write(payload + "\n");
    return;
  }
  process.stdout.write(JSON.stringify(payload, null, 2) + "\n");
}

function ok(msg: string, out: Flags): void {
  if (out.quiet) return;
  if (out.json) {
    process.stdout.write(JSON.stringify({ ok: true, message: msg }) + "\n");
    return;
  }
  process.stdout.write(`✓ ${msg}\n`);
}

function fail(msg: string): never {
  throw Object.assign(new Error(msg), { exitCode: 1 });
}

function parseInput(raw?: string): unknown {
  if (!raw) return {};
  const trimmed = raw.trim();
  if (trimmed.startsWith("@")) {
    const file = path.resolve(trimmed.slice(1));
    return JSON.parse(fs.readFileSync(file, "utf8")) as unknown;
  }
  try {
    return JSON.parse(trimmed);
  } catch {
    return trimmed;
  }
}

/** Local-first commands required by the OpenAgent spec (no server needed). */
export function registerLocalCommands(program: Command): void {
  // ---------- start ----------
  program
    .command("start")
    .description("Start the OpenAgent platform (API, scheduler, dashboard)")
    .option("--port <port>", "port to listen on")
    .option("--no-open", "do not open the browser automatically")
    .action(async (opts: Record<string, string | boolean>, cmd: Command) => {
      const out = flagsOf(program, cmd);
      void out;
      const projectDir = requireProjectDir();
      const port = opts.port ? Number(opts.port) : undefined;
      await startLocalPlatform(projectDir, { port, open: opts.open !== false });
    });

  // ---------- run (shorthand for workflow run) ----------
  program
    .command("run <workflowId>")
    .description("Run a workflow by id (shorthand for `workflow run`)")
    .option("--input <json>", "JSON input or @file")
    .option("--timeout <ms>", "execution timeout in ms")
    .action(async (id: string, opts: Record<string, string>, cmd: Command) => {
      const out = flagsOf(program, cmd);
      const projectDir = requireProjectDir();
      const rec = await runWorkflowLocal(
        projectDir,
        id,
        parseInput(opts.input),
        {
          timeout: opts.timeout ? Number(opts.timeout) : undefined,
        },
      );
      ok(`Execution ${rec.executionId} finished: ${rec.status}`, out);
      emit(rec, out);
      if (rec.status !== "SUCCESS") process.exitCode = 1;
    });

  // ---------- ask (natural language) ----------
  program
    .command("ask <prompt...>")
    .description("Natural language command mode (generate/run/list workflows)")
    .option("--run", "run the generated or matched workflow immediately")
    .action(
      async (parts: string[], opts: Record<string, boolean>, cmd: Command) => {
        const out = flagsOf(program, cmd);
        const projectDir = requireProjectDir();
        const prompt = parts.join(" ");
        const low = prompt.toLowerCase();
        const runMatch = low.match(/run (?:my |the )?(.+?) workflow/);
        if (low.startsWith("run ") || (runMatch && !low.includes("create"))) {
          const name = (runMatch?.[1] ?? low.replace(/^run\s+/, "")).trim();
          const all = listWorkflowsLocal(projectDir);
          const found =
            all.find((w) => w.id === name) ??
            all.find((w) => w.name.toLowerCase().includes(name));
          if (!found)
            fail(
              `No workflow matching '${name}'. Try \`openagent workflow list\`.`,
            );
          const rec = await runWorkflowLocal(
            projectDir,
            (found as { id: string }).id,
            {},
          );
          ok(`Ran '${(found as { name: string }).name}': ${rec.status}`, out);
          emit(rec, out);
          return;
        }
        if (low.includes("list ")) {
          emit(listWorkflowsLocal(projectDir), out);
          return;
        }
        const wf = generateWorkflowFromPrompt(prompt);
        saveWorkflowLocal(projectDir, wf);
        ok(
          `Generated workflow '${wf.name}' (${wf.id}) with ${wf.nodes.length} nodes.`,
          out,
        );
        emit(wf, out);
        if (opts.run) {
          const rec = await runWorkflowLocal(projectDir, wf.id, {});
          ok(`Execution ${rec.executionId}: ${rec.status}`, out);
          emit(rec, out);
        }
      },
    );

  // ---------- autonomous ----------
  program
    .command("autonomous <goal...>")
    .description("Run an autonomous goal-driven agent with guardrails")
    .option(
      "--model <model>",
      "model id (prefix with provider, e.g. ollama:qwen2.5)",
    )
    .option("--max-steps <n>", "max agent iterations", "10")
    .option("--timeout <ms>", "overall timeout in ms", "120000")
    .option(
      "--approve",
      "require human approval for tool calls (not supported non-interactively; denies tools)",
    )
    .action(
      async (
        parts: string[],
        opts: Record<string, string | boolean>,
        cmd: Command,
      ) => {
        const out = flagsOf(program, cmd);
        const projectDir = requireProjectDir();
        process.env.OPENAGENT_AUTO_APPROVE = opts.approve ? "0" : "1";
        const rec = await runAgentLocal(
          projectDir,
          ensureAutonomousAgent(projectDir, String(opts.model ?? "")),
          {
            goal: parts.join(" "),
          },
        );
        void opts;
        ok(`Autonomous run finished: ${rec.status}`, out);
        emit(rec, out);
        if (rec.status !== "SUCCESS") process.exitCode = 1;
      },
    );

  // ---------- workflow ----------
  const workflow = program
    .command("workflow")
    .description("Manage local workflows");
  workflow
    .command("list")
    .description("List local workflows")
    .action(async (_o: unknown, cmd: Command) => {
      const out = flagsOf(program, cmd);
      emit(listWorkflowsLocal(requireProjectDir()), out);
    });
  workflow
    .command("get <id>")
    .description("Show a workflow definition")
    .action(async (id: string, _o: unknown, cmd: Command) => {
      emit(getWorkflowLocal(requireProjectDir(), id), flagsOf(program, cmd));
    });
  workflow
    .command("create")
    .description("Create a workflow (blank, from template, prompt, or file)")
    .option("--name <name>", "workflow name")
    .option("--template <id>", "template id (see `workflow templates`)")
    .option("--prompt <text>", "natural-language description to generate from")
    .option("--file <path>", "JSON workflow file to import")
    .action(async (opts: Record<string, string>, cmd: Command) => {
      const out = flagsOf(program, cmd);
      const projectDir = requireProjectDir();
      let wf;
      if (opts.file) {
        wf = JSON.parse(
          fs.readFileSync(path.resolve(opts.file), "utf8"),
        ) as ReturnType<typeof getTemplate> extends never
          ? never
          : import("@openagent/workflow-engine").WorkflowDefinition;
      } else if (opts.template) {
        const tpl = getTemplate(opts.template);
        if (!tpl)
          fail(
            `Unknown template '${opts.template}'. Run \`openagent workflow templates\`.`,
          );
        wf = (tpl as NonNullable<typeof tpl>).build();
      } else if (opts.prompt) {
        wf = generateWorkflowFromPrompt(opts.prompt);
      } else {
        const id = `wf_${Date.now().toString(36)}`;
        wf = {
          id,
          name: opts.name ?? "Untitled workflow",
          version: 1,
          nodes: [
            {
              id: "trigger",
              type: "manual",
              position: { x: 100, y: 100 },
              config: {},
            },
          ],
          edges: [],
        };
      }
      if (opts.name) wf.name = opts.name;
      saveWorkflowLocal(projectDir, wf);
      ok(`Created workflow '${wf.name}' (${wf.id}).`, out);
      emit(wf, out);
    });
  workflow
    .command("run <id>")
    .description("Execute a workflow locally")
    .option("--input <json>", "JSON input or @file")
    .option("--timeout <ms>", "execution timeout in ms")
    .action(async (id: string, opts: Record<string, string>, cmd: Command) => {
      const out = flagsOf(program, cmd);
      const rec = await runWorkflowLocal(
        requireProjectDir(),
        id,
        parseInput(opts.input),
        {
          timeout: opts.timeout ? Number(opts.timeout) : undefined,
        },
      );
      ok(`Execution ${rec.executionId} finished: ${rec.status}`, out);
      emit(rec, out);
      if (rec.status !== "SUCCESS") process.exitCode = 1;
    });
  workflow
    .command("delete <id>")
    .description("Delete a workflow")
    .action(async (id: string, _o: unknown, cmd: Command) => {
      const out = flagsOf(program, cmd);
      if (!deleteWorkflowLocal(requireProjectDir(), id))
        fail(`workflow '${id}' not found`);
      ok(`Deleted workflow '${id}'.`, out);
    });
  workflow
    .command("export <id> [file]")
    .description("Export a workflow to JSON (stdout or file)")
    .action(
      async (
        id: string,
        file: string | undefined,
        _o: unknown,
        cmd: Command,
      ) => {
        const out = flagsOf(program, cmd);
        const wf = getWorkflowLocal(requireProjectDir(), id);
        const text = JSON.stringify(wf, null, 2);
        if (file) {
          fs.writeFileSync(path.resolve(file), text);
          ok(`Exported to ${file}.`, out);
        } else {
          process.stdout.write(text + "\n");
        }
      },
    );
  workflow
    .command("import <file>")
    .description("Import a workflow from JSON")
    .action(async (file: string, _o: unknown, cmd: Command) => {
      const out = flagsOf(program, cmd);
      const projectDir = requireProjectDir();
      const wf = JSON.parse(
        fs.readFileSync(path.resolve(file), "utf8"),
      ) as import("@openagent/workflow-engine").WorkflowDefinition;
      saveWorkflowLocal(projectDir, wf);
      ok(`Imported workflow '${wf.name}' (${wf.id}).`, out);
    });
  workflow
    .command("templates")
    .description("List available workflow templates")
    .action(async (_o: unknown, cmd: Command) => {
      emit(listTemplates(), flagsOf(program, cmd));
    });
  workflow
    .command("validate <id>")
    .description("Validate a workflow definition")
    .action(async (id: string, _o: unknown, cmd: Command) => {
      const out = flagsOf(program, cmd);
      const wf = getWorkflowLocal(requireProjectDir(), id);
      const v = validateWorkflow(wf);
      emit(v, out);
      if (!v.ok) process.exitCode = 2;
    });
  workflow
    .command("generate <prompt...>")
    .description("Generate a workflow from natural language")
    .option("--run", "run immediately after generating")
    .action(
      async (parts: string[], opts: Record<string, boolean>, cmd: Command) => {
        const out = flagsOf(program, cmd);
        const projectDir = requireProjectDir();
        const wf = generateWorkflowFromPrompt(parts.join(" "));
        saveWorkflowLocal(projectDir, wf);
        ok(`Generated workflow '${wf.name}' (${wf.id}).`, out);
        emit(wf, out);
        if (opts.run) emit(await runWorkflowLocal(projectDir, wf.id, {}), out);
      },
    );

  // ---------- agent ----------
  const agent = program.command("agent").description("Manage local AI agents");
  agent
    .command("list")
    .description("List local agents")
    .action(async (_o: unknown, cmd: Command) => {
      emit(listAgentsLocal(requireProjectDir()), flagsOf(program, cmd));
    });
  agent
    .command("create")
    .description("Create an agent")
    .option("--name <name>", "agent name")
    .option("--model <model>", "model id", "ollama:qwen2.5")
    .option("--system <text>", "system prompt")
    .action(async (opts: Record<string, string>, cmd: Command) => {
      const out = flagsOf(program, cmd);
      const projectDir = requireProjectDir();
      const id = `agent_${Date.now().toString(36)}`;
      const def = {
        id,
        name: opts.name ?? "My Agent",
        model: opts.model ?? "ollama:qwen2.5",
        systemPrompt: opts.system ?? "You are a helpful automation agent.",
        tools: [],
        memory: true,
        maxIterations: 8,
        temperature: 0.2,
      };
      fs.mkdirSync(path.join(projectDir, ".openagent", "agents"), {
        recursive: true,
      });
      fs.writeFileSync(
        path.join(projectDir, ".openagent", "agents", `${id}.json`),
        JSON.stringify(def, null, 2),
      );
      ok(`Created agent '${def.name}' (${id}).`, out);
      emit(def, out);
    });
  agent
    .command("run <id>")
    .description("Run an agent with input")
    .option("--input <json>", "JSON input or raw text")
    .action(async (id: string, opts: Record<string, string>, cmd: Command) => {
      const out = flagsOf(program, cmd);
      const rec = await runAgentLocal(
        requireProjectDir(),
        id,
        parseInput(opts.input) ?? opts.input ?? {},
      );
      ok(`Agent run finished: ${rec.status}`, out);
      emit(rec, out);
      if (rec.status !== "SUCCESS") process.exitCode = 1;
    });

  // ---------- node ----------
  const node = program.command("node").description("Inspect and manage nodes");
  node
    .command("list")
    .description("List built-in node types")
    .action(async (_o: unknown, cmd: Command) => {
      const out = flagsOf(program, cmd);
      const projectDir = findProjectDir() ?? process.cwd();
      emit(
        {
          builtin: listNodesLocal(),
          installed: listInstalledNodes(projectDir),
        },
        out,
      );
    });
  node
    .command("install <package>")
    .description("Install a node package (npm) and record it")
    .action(async (pkg: string, _o: unknown, cmd: Command) => {
      const out = flagsOf(program, cmd);
      const projectDir = requireProjectDir();
      await installNodePackage(projectDir, pkg);
      ok(`Installed node package '${pkg}'.`, out);
    });
  node
    .command("create <name>")
    .description("Scaffold a custom node")
    .action(async (name: string, _o: unknown, cmd: Command) => {
      const out = flagsOf(program, cmd);
      const dest = scaffoldNode(requireProjectDir(), name);
      ok(`Created node scaffold at ${dest}.`, out);
    });

  // ---------- memory ----------
  const memory = program.command("memory").description("Local agent memory");
  memory
    .command("get <key>")
    .description("Read a memory key")
    .action(async (key: string, _o: unknown, cmd: Command) => {
      emit(await memoryGet(requireProjectDir(), key), flagsOf(program, cmd));
    });
  memory
    .command("set <key> <value>")
    .description("Write a memory key (JSON or text)")
    .action(async (key: string, value: string, _o: unknown, cmd: Command) => {
      const out = flagsOf(program, cmd);
      let parsed: unknown = value;
      try {
        parsed = JSON.parse(value);
      } catch {
        parsed = value;
      }
      await memorySet(requireProjectDir(), key, parsed);
      ok(`Set memory key '${key}'.`, out);
    });
  memory
    .command("search <query>")
    .description("Semantic search over memory")
    .option("--limit <n>", "max results", "5")
    .action(
      async (query: string, opts: Record<string, string>, cmd: Command) => {
        emit(
          await memorySearch(
            requireProjectDir(),
            query,
            Number(opts.limit ?? 5),
          ),
          flagsOf(program, cmd),
        );
      },
    );

  // ---------- schedule ----------
  const schedule = program
    .command("schedule")
    .description("Schedules (cron/interval)");
  schedule
    .command("list")
    .description("List schedules")
    .action(async (_o: unknown, cmd: Command) => {
      emit(listSchedules(requireProjectDir()), flagsOf(program, cmd));
    });
  schedule
    .command("create")
    .description("Create a schedule for a workflow")
    .option("--workflow <id>", "workflow id")
    .option("--cron <expr>", "cron expression (e.g. '0 9 * * *')")
    .option("--interval <expr>", "interval (e.g. 5m, 1h)")
    .action(async (opts: Record<string, string>, cmd: Command) => {
      const out = flagsOf(program, cmd);
      if (!opts.workflow) fail("Missing --workflow <id>.");
      if (!opts.cron && !opts.interval) fail("Provide --cron or --interval.");
      const { id } = createSchedule(requireProjectDir(), {
        workflowId: opts.workflow,
        cron: opts.cron,
        interval: opts.interval,
      });
      ok(`Created schedule ${id}.`, out);
    });
  schedule
    .command("delete <id>")
    .description("Delete a schedule")
    .action(async (id: string, _o: unknown, cmd: Command) => {
      const out = flagsOf(program, cmd);
      if (!deleteSchedule(requireProjectDir(), id))
        fail(`schedule '${id}' not found`);
      ok(`Deleted schedule '${id}'.`, out);
    });

  // ---------- update ----------
  program
    .command("update")
    .description("Check for updates and show the safe update flow")
    .action(async (_o: unknown, cmd: Command) => {
      const out = flagsOf(program, cmd);
      const current = "1.0.0";
      let latest = current;
      try {
        const res = await fetch(
          "https://registry.npmjs.org/@openagent%2Fcli/latest",
          {
            signal: AbortSignal.timeout(8000),
          },
        );
        if (res.ok) {
          const j = (await res.json()) as { version?: string };
          if (j.version) latest = j.version;
        }
      } catch {
        // offline
      }
      if (latest !== current) {
        emit(
          {
            current,
            latest,
            hint: "Workflows are stored as JSON in .openagent/ and are never touched by updates. Run `npm i -g @openagent/cli@latest`.",
          },
          out,
        );
      } else {
        ok(
          `Already up to date (${current}). Workflows are preserved across updates.`,
          out,
        );
      }
    });

  // ---------- version ----------
  program
    .command("version")
    .description("Show CLI version")
    .action(async (_o: unknown, cmd: Command) => {
      emit(
        { version: "1.0.0", package: "@openagent/cli" },
        flagsOf(program, cmd),
      );
    });

  // ---------- git ----------
  program
    .command("git")
    .description("Version-control helpers for workflows")
    .option("--init", "git-init the project with an OpenAgent .gitignore")
    .action(async (opts: Record<string, boolean>, cmd: Command) => {
      const out = flagsOf(program, cmd);
      const projectDir = requireProjectDir();
      if (!opts.init) fail("Usage: `openagent git --init`.");
      const { execFile: ef } = await import("node:child_process");
      await new Promise<void>((resolve, reject) => {
        ef("git", ["init"], { cwd: projectDir }, (err) =>
          err ? reject(err) : resolve(),
        );
      }).catch((e: unknown) => {
        fail(`git init failed: ${e instanceof Error ? e.message : String(e)}`);
      });
      const ignore = path.join(projectDir, ".gitignore");
      const snippet =
        "\n# OpenAgent secrets — never commit\n.openagent/credentials/\n.openagent/memory/\n*.oaext\n";
      if (!fs.existsSync(ignore)) fs.writeFileSync(ignore, snippet.trimStart());
      else if (
        !fs.readFileSync(ignore, "utf8").includes(".openagent/credentials")
      )
        fs.appendFileSync(ignore, snippet);
      ok("Git initialized (secrets excluded via .gitignore).", out);
    });
}

export function printWelcome(): void {
  const noColor = process.env.NO_COLOR !== undefined;
  const title = noColor
    ? "Welcome to OpenAgent\n\nAI Automation Infrastructure for Developers\n\nGet started:\n\n> openagent init"
    : "Welcome to OpenAgent\n\nAI Automation Infrastructure for Developers\n\nGet started:\n\n> openagent init";
  process.stdout.write(title + "\n");
}

function ensureAutonomousAgent(projectDir: string, model: string): string {
  const dir = path.join(projectDir, ".openagent", "agents");
  fs.mkdirSync(dir, { recursive: true });
  const file = path.join(dir, "autonomous.json");
  if (!fs.existsSync(file)) {
    fs.writeFileSync(
      file,
      JSON.stringify(
        {
          id: "autonomous",
          name: "AutonomousAgent",
          model: model || "ollama:qwen2.5",
          systemPrompt:
            "You are an autonomous agent. Plan, use tools when available, observe results, validate, retry on failure, then complete with FINAL:.",
          tools: [],
          memory: true,
          maxIterations: 10,
          temperature: 0.2,
        },
        null,
        2,
      ),
    );
  }
  void initProject;
  return "autonomous";
}

export {
  listMcpServers,
  addMcpServer,
  removeMcpServer,
  testMcpServer,
  listExecutionsLocal,
};
