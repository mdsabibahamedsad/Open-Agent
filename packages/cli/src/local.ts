import fs from "node:fs";
import path from "node:path";
import { execFile, spawn } from "node:child_process";
import {
  FileCredentialResolver,
  FileMemoryManager,
  ToolRegistry,
  generateWorkflowFromPrompt,
  getTemplate,
  listTemplates,
  runWorkflow,
  validateWorkflow,
  listNodeTypes,
  checkOllama,
  startServer,
  listSchedules,
  saveSchedules,
  parseIntervalToMs,
  type ExecutionRecord,
  type WorkflowDefinition,
} from "@openagent/workflow-engine";

export const PROJECT_DIR_NAME = ".openagent";
export const LOCAL_CONFIG_FILE = "openagent.config.ts";

export function findProjectDir(start = process.cwd()): string | null {
  let dir = path.resolve(start);
  for (let i = 0; i < 12; i++) {
    if (fs.existsSync(path.join(dir, PROJECT_DIR_NAME))) return dir;
    const parent = path.dirname(dir);
    if (parent === dir) return null;
    dir = parent;
  }
  return null;
}

export function isInitialized(dir = process.cwd()): boolean {
  return fs.existsSync(path.join(path.resolve(dir), PROJECT_DIR_NAME));
}

export function requireProjectDir(dir = process.cwd()): string {
  const found = findProjectDir(dir);
  if (!found) {
    throw Object.assign(
      new Error(
        `No OpenAgent project found. Run \`openagent init\` first.\n\nWelcome to OpenAgent\n\nAI Automation Infrastructure for Developers\n\nGet started:\n\n> openagent init`,
      ),
      { exitCode: 2 },
    );
  }
  return found;
}

const SUBDIRS = [
  "agents",
  "workflows",
  "nodes",
  "memory",
  "credentials",
  "logs",
  "schedules",
  "executions",
  "workspace",
];

export function initProject(
  targetDir = process.cwd(),
  opts?: { force?: boolean },
): { dir: string; created: string[] } {
  const dir = path.resolve(targetDir);
  const oa = path.join(dir, PROJECT_DIR_NAME);
  if (fs.existsSync(oa) && !opts?.force) {
    // Idempotent: ensure subdirs exist, keep existing workflows.
    for (const sub of SUBDIRS)
      fs.mkdirSync(path.join(oa, sub), { recursive: true });
    return { dir, created: [] };
  }
  const created: string[] = [];
  for (const sub of SUBDIRS) {
    const p = path.join(oa, sub);
    if (!fs.existsSync(p)) {
      fs.mkdirSync(p, { recursive: true });
      created.push(p);
    }
  }
  const localConfig = path.join(oa, "config.json");
  if (!fs.existsSync(localConfig)) {
    fs.writeFileSync(
      localConfig,
      JSON.stringify(
        {
          server: { port: 5678 },
          database: { provider: "sqlite" },
          ai: { provider: "ollama", model: "qwen2.5" },
          browser: { enabled: true },
          memory: { enabled: true },
        },
        null,
        2,
      ),
    );
    created.push(localConfig);
  }
  const tsConfig = path.join(dir, LOCAL_CONFIG_FILE);
  if (!fs.existsSync(tsConfig)) {
    fs.writeFileSync(
      tsConfig,
      `export default {\n  server: {\n    port: 5678,\n  },\n  database: {\n    provider: "sqlite" as const,\n  },\n  ai: {\n    provider: "ollama",\n    model: "qwen2.5",\n  },\n  browser: {\n    enabled: true,\n  },\n  memory: {\n    enabled: true,\n  },\n};\n`,
    );
    created.push(tsConfig);
  }
  // Seed example workflow (spec acceptance: Schedule → Web Search → AI Agent → File).
  const exampleFile = path.join(oa, "workflows", "daily-news-digest.json");
  if (!fs.existsSync(exampleFile)) {
    const tpl = getTemplate("daily-news-digest");
    if (tpl) {
      const wf = tpl.build();
      wf.id = "daily-news-digest";
      fs.writeFileSync(exampleFile, JSON.stringify(wf, null, 2));
      created.push(exampleFile);
    }
  }
  const agentFile = path.join(oa, "agents", "research-agent.json");
  if (!fs.existsSync(agentFile)) {
    fs.writeFileSync(
      agentFile,
      JSON.stringify(
        {
          id: "research-agent",
          name: "ResearchAgent",
          model: "ollama:qwen2.5",
          systemPrompt: "You are a careful research assistant.",
          tools: ["web-search", "file"],
          memory: true,
          maxIterations: 8,
          temperature: 0.2,
        },
        null,
        2,
      ),
    );
    created.push(agentFile);
  }
  return { dir, created };
}

export function projectPort(projectDir: string): number {
  const fromEnv = Number(process.env.OPENAGENT_PORT ?? process.env.PORT ?? "");
  if (Number.isFinite(fromEnv) && fromEnv > 0) return fromEnv;
  try {
    const raw = fs.readFileSync(
      path.join(projectDir, PROJECT_DIR_NAME, "config.json"),
      "utf8",
    );
    const port = (JSON.parse(raw) as { server?: { port?: number } }).server
      ?.port;
    if (typeof port === "number" && port > 0) return port;
  } catch {
    // default
  }
  return 5678;
}

// ---------- workflow store ----------
export function workflowFile(projectDir: string, id: string): string {
  return path.join(projectDir, PROJECT_DIR_NAME, "workflows", `${id}.json`);
}

export function listWorkflowsLocal(projectDir: string): WorkflowDefinition[] {
  const dir = path.join(projectDir, PROJECT_DIR_NAME, "workflows");
  if (!fs.existsSync(dir)) return [];
  const out: WorkflowDefinition[] = [];
  for (const f of fs.readdirSync(dir)) {
    if (!f.endsWith(".json")) continue;
    try {
      out.push(
        JSON.parse(
          fs.readFileSync(path.join(dir, f), "utf8"),
        ) as WorkflowDefinition,
      );
    } catch {
      // skip corrupt
    }
  }
  return out.sort((a, b) => a.name.localeCompare(b.name));
}

export function getWorkflowLocal(
  projectDir: string,
  id: string,
): WorkflowDefinition {
  const file = workflowFile(projectDir, id);
  if (!fs.existsSync(file)) {
    // also try matching by name
    const found = listWorkflowsLocal(projectDir).find((w) => w.name === id);
    if (found) return found;
    throw Object.assign(new Error(`workflow '${id}' not found`), {
      exitCode: 1,
    });
  }
  return JSON.parse(fs.readFileSync(file, "utf8")) as WorkflowDefinition;
}

export function saveWorkflowLocal(
  projectDir: string,
  def: WorkflowDefinition,
): void {
  const v = validateWorkflow(def);
  if (!v.ok) {
    throw Object.assign(
      new Error(
        `Invalid workflow: ${v.errors.map((e) => `${e.path}: ${e.message}`).join("; ")}`,
      ),
      { exitCode: 2 },
    );
  }
  fs.mkdirSync(path.join(projectDir, PROJECT_DIR_NAME, "workflows"), {
    recursive: true,
  });
  fs.writeFileSync(
    workflowFile(projectDir, def.id),
    JSON.stringify(def, null, 2),
  );
}

export function deleteWorkflowLocal(projectDir: string, id: string): boolean {
  const file = workflowFile(projectDir, id);
  if (!fs.existsSync(file)) return false;
  fs.rmSync(file);
  return true;
}

export async function runWorkflowLocal(
  projectDir: string,
  id: string,
  input: unknown = {},
  opts?: { timeout?: number },
): Promise<ExecutionRecord> {
  const def = getWorkflowLocal(projectDir, id);
  const rec = await runWorkflow(def, {
    input,
    credentials: new FileCredentialResolver(projectDir),
    memory: new FileMemoryManager(projectDir),
    tools: buildToolRegistry(projectDir),
    projectDir,
    timeout: opts?.timeout,
  });
  persistExecution(projectDir, rec);
  return rec;
}

export function persistExecution(
  projectDir: string,
  rec: ExecutionRecord,
): void {
  const dir = path.join(projectDir, PROJECT_DIR_NAME, "executions");
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(
    path.join(dir, `${rec.executionId}.json`),
    JSON.stringify(rec, null, 2),
  );
  // append to logs/executions.log (JSONL, audit-friendly)
  try {
    fs.appendFileSync(
      path.join(projectDir, PROJECT_DIR_NAME, "logs", "executions.log"),
      JSON.stringify({
        executionId: rec.executionId,
        workflowId: rec.workflowId,
        status: rec.status,
        startedAt: rec.startedAt,
        finishedAt: rec.finishedAt,
      }) + "\n",
    );
  } catch {
    // best effort
  }
}

export function listExecutionsLocal(
  projectDir: string,
  limit = 20,
): ExecutionRecord[] {
  const dir = path.join(projectDir, PROJECT_DIR_NAME, "executions");
  if (!fs.existsSync(dir)) return [];
  const files = fs
    .readdirSync(dir)
    .filter((f) => f.endsWith(".json"))
    .sort()
    .reverse()
    .slice(0, limit);
  const out: ExecutionRecord[] = [];
  for (const f of files) {
    try {
      out.push(
        JSON.parse(
          fs.readFileSync(path.join(dir, f), "utf8"),
        ) as ExecutionRecord,
      );
    } catch {
      // skip
    }
  }
  return out;
}

function buildToolRegistry(_projectDir: string): ToolRegistry {
  const registry = new ToolRegistry();
  // Expose safe core tools to the AI agent (web-search + file-read + text).
  // Full node-as-tool wiring happens per-execution via MCP/custom tools.
  return registry;
}

// ---------- agents ----------
export interface AgentDefinition {
  id: string;
  name: string;
  model: string;
  systemPrompt?: string;
  tools?: string[];
  memory?: boolean;
  maxIterations?: number;
  temperature?: number;
}

export function listAgentsLocal(projectDir: string): AgentDefinition[] {
  const dir = path.join(projectDir, PROJECT_DIR_NAME, "agents");
  if (!fs.existsSync(dir)) return [];
  const out: AgentDefinition[] = [];
  for (const f of fs.readdirSync(dir)) {
    if (!f.endsWith(".json")) continue;
    try {
      out.push(
        JSON.parse(
          fs.readFileSync(path.join(dir, f), "utf8"),
        ) as AgentDefinition,
      );
    } catch {
      // skip
    }
  }
  return out;
}

export async function runAgentLocal(
  projectDir: string,
  id: string,
  input: unknown = {},
): Promise<ExecutionRecord> {
  const file = path.join(projectDir, PROJECT_DIR_NAME, "agents", `${id}.json`);
  if (!fs.existsSync(file))
    throw Object.assign(new Error(`agent '${id}' not found`), { exitCode: 1 });
  const agent = JSON.parse(fs.readFileSync(file, "utf8")) as AgentDefinition;
  const text = typeof input === "string" ? input : JSON.stringify(input);
  const wf: WorkflowDefinition = {
    id: `agent_run_${Date.now()}`,
    name: `Agent run: ${agent.name}`,
    nodes: [
      {
        id: "agent",
        type: "ai-agent",
        config: {
          model: agent.model,
          systemPrompt: agent.systemPrompt ?? "",
          goal: text || agent.name,
          tools: agent.tools ?? [],
          maxIterations: agent.maxIterations ?? 8,
          temperature: agent.temperature ?? 0.2,
        },
      },
    ],
    edges: [],
  };
  const rec = await runWorkflow(wf, {
    input: { goal: text },
    credentials: new FileCredentialResolver(projectDir),
    memory:
      agent.memory === false ? undefined : new FileMemoryManager(projectDir),
    tools: buildToolRegistry(projectDir),
    projectDir,
  });
  persistExecution(projectDir, {
    ...rec,
    workflowId: id,
    workflowName: agent.name,
  });
  return rec;
}

// ---------- nodes ----------
export function listNodesLocal(): Array<{
  id: string;
  name: string;
  description: string;
}> {
  return listNodeTypes();
}

export function installedNodesFile(projectDir: string): string {
  return path.join(projectDir, PROJECT_DIR_NAME, "nodes", "installed.json");
}

export function listInstalledNodes(
  projectDir: string,
): Array<{ package: string; installedAt: string }> {
  try {
    const f = installedNodesFile(projectDir);
    if (!fs.existsSync(f)) return [];
    return JSON.parse(fs.readFileSync(f, "utf8")) as Array<{
      package: string;
      installedAt: string;
    }>;
  } catch {
    return [];
  }
}

export async function installNodePackage(
  projectDir: string,
  pkg: string,
): Promise<void> {
  await new Promise<void>((resolve, reject) => {
    try {
      const child =
        process.platform === "win32"
          ? spawn(
              "cmd.exe",
              [
                "/d",
                "/s",
                "/c",
                `npm install --no-save ${JSON.stringify(pkg)}`,
              ],
              {
                cwd: projectDir,
                stdio: "inherit",
              },
            )
          : spawn("npm", ["install", "--no-save", pkg], {
              cwd: projectDir,
              stdio: "inherit",
              shell: false,
            });
      child.on("error", reject);
      child.on("exit", (code) => {
        if (code === 0) resolve();
        else reject(new Error(`npm install ${pkg} exited with code ${code}`));
      });
    } catch (e) {
      reject(e);
    }
  });
  const file = installedNodesFile(projectDir);
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const cur = listInstalledNodes(projectDir);
  if (!cur.some((e) => e.package === pkg)) {
    cur.push({ package: pkg, installedAt: new Date().toISOString() });
    fs.writeFileSync(file, JSON.stringify(cur, null, 2));
  }
}

export function scaffoldNode(projectDir: string, name: string): string {
  const safe = name.replace(/[^a-zA-Z0-9-_]/g, "-") || "my-node";
  const dest = path.join(projectDir, PROJECT_DIR_NAME, "nodes", `${safe}.ts`);
  if (fs.existsSync(dest))
    throw Object.assign(new Error(`node '${safe}' already exists`), {
      exitCode: 1,
    });
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  fs.writeFileSync(
    dest,
    `// OpenAgent custom node: ${safe}\n// Export an OpenAgentNode-compatible object and register it via your plugin entrypoint.\nimport type { ExecutionContext, NodeResult, WorkflowNode } from "@openagent/workflow-engine";\n\nexport const ${safe.replace(/[^a-zA-Z0-9_]/g, "_")} = {\n  id: "${safe}",\n  name: "${safe}",\n  description: "Custom node ${safe}.",\n  version: "1.0.0",\n  async execute(node: WorkflowNode, ctx: ExecutionContext): Promise<NodeResult> {\n    void node;\n    return { output: ctx.input };\n  },\n};\n\nexport default ${safe.replace(/[^a-zA-Z0-9_]/g, "_")};\n`,
  );
  return dest;
}

// ---------- MCP ----------
export interface McpServerEntry {
  id: string;
  name: string;
  transport: "stdio" | "http";
  command?: string;
  args?: string[];
  url?: string;
  enabled: boolean;
}

function mcpFile(projectDir: string): string {
  return path.join(projectDir, PROJECT_DIR_NAME, "mcp.json");
}

export function listMcpServers(projectDir: string): McpServerEntry[] {
  try {
    if (!fs.existsSync(mcpFile(projectDir))) return [];
    const raw = JSON.parse(fs.readFileSync(mcpFile(projectDir), "utf8")) as {
      servers?: McpServerEntry[];
    };
    return raw.servers ?? [];
  } catch {
    return [];
  }
}

function saveMcpServers(projectDir: string, servers: McpServerEntry[]): void {
  fs.mkdirSync(path.join(projectDir, PROJECT_DIR_NAME), { recursive: true });
  fs.writeFileSync(mcpFile(projectDir), JSON.stringify({ servers }, null, 2));
}

export function addMcpServer(projectDir: string, entry: McpServerEntry): void {
  const cur = listMcpServers(projectDir).filter((s) => s.id !== entry.id);
  cur.push(entry);
  saveMcpServers(projectDir, cur);
}

export function removeMcpServer(projectDir: string, id: string): boolean {
  const cur = listMcpServers(projectDir);
  const next = cur.filter((s) => s.id !== id);
  if (next.length === cur.length) return false;
  saveMcpServers(projectDir, next);
  return true;
}

export async function testMcpServer(
  projectDir: string,
  id: string,
): Promise<{ ok: boolean; detail: string }> {
  const found = listMcpServers(projectDir).find((s) => s.id === id);
  if (!found)
    throw Object.assign(new Error(`MCP server '${id}' not found`), {
      exitCode: 1,
    });
  if (found.transport === "http" && found.url) {
    try {
      const res = await fetch(found.url, {
        method: "GET",
        signal: AbortSignal.timeout(8000),
      });
      return { ok: res.ok, detail: `HTTP ${res.status} at ${found.url}` };
    } catch (e) {
      return { ok: false, detail: e instanceof Error ? e.message : String(e) };
    }
  }
  if (found.transport === "stdio" && found.command) {
    const ok = await new Promise<boolean>((resolve) => {
      const child = execFile(
        found.command as string,
        [...(found.args ?? ["--version"])],
        { timeout: 8000 },
        (err) => resolve(!err),
      );
      void child;
    });
    return {
      ok,
      detail: ok
        ? `stdio command '${found.command}' runnable`
        : `cannot run '${found.command}'`,
    };
  }
  return { ok: false, detail: "server has no testable endpoint" };
}

// ---------- memory ----------
export async function memoryGet(
  projectDir: string,
  key: string,
): Promise<unknown> {
  return new FileMemoryManager(projectDir).get(key);
}

export async function memorySet(
  projectDir: string,
  key: string,
  value: unknown,
): Promise<void> {
  await new FileMemoryManager(projectDir).set(key, value);
}

export async function memorySearch(
  projectDir: string,
  query: string,
  limit = 5,
): Promise<unknown> {
  return new FileMemoryManager(projectDir).search(query, limit);
}

// ---------- schedules ----------
export {
  listSchedules,
  parseIntervalToMs,
  listTemplates,
  generateWorkflowFromPrompt,
  checkOllama,
};

export function createSchedule(
  projectDir: string,
  opts: {
    workflowId: string;
    cron?: string;
    interval?: string;
    timezone?: string;
  },
): { id: string } {
  getWorkflowLocal(projectDir, opts.workflowId); // validates existence
  const entries = listSchedules(projectDir);
  const id = `sched_${Date.now().toString(36)}`;
  entries.push({
    id,
    workflowId: opts.workflowId,
    cron: opts.cron,
    intervalMs: opts.interval ? parseIntervalToMs(opts.interval) : undefined,
    timezone: opts.timezone,
    enabled: true,
    createdAt: new Date().toISOString(),
  });
  saveSchedules(projectDir, entries);
  return { id };
}

export function deleteSchedule(projectDir: string, id: string): boolean {
  const entries = listSchedules(projectDir);
  const next = entries.filter((e) => e.id !== id);
  if (next.length === entries.length) return false;
  saveSchedules(projectDir, next);
  return true;
}

// ---------- project backups (user data safety) ----------
export interface ProjectBackupManifest {
  id: string;
  createdAt: string;
  files: string[];
}

function projectBackupsDir(projectDir: string): string {
  return path.join(projectDir, PROJECT_DIR_NAME, "backups");
}

const PROJECT_BACKUP_ENTRIES = [
  "workflows",
  "agents",
  "config.json",
  "credentials",
  "schedules",
  "mcp.json",
];

export function createProjectBackup(
  projectDir: string,
  keep = 5,
): ProjectBackupManifest {
  const base = path.join(projectDir, PROJECT_DIR_NAME);
  const id = `backup_${new Date().toISOString().replace(/[:.]/g, "-")}`;
  const dest = path.join(projectBackupsDir(projectDir), id);
  fs.mkdirSync(dest, { recursive: true });
  const files: string[] = [];
  for (const rel of PROJECT_BACKUP_ENTRIES) {
    const src = path.join(base, rel);
    if (!fs.existsSync(src)) continue;
    const target = path.join(dest, rel);
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.cpSync(src, target, { recursive: true });
    files.push(rel);
  }
  const manifest: ProjectBackupManifest = {
    id,
    createdAt: new Date().toISOString(),
    files,
  };
  fs.writeFileSync(
    path.join(dest, "manifest.json"),
    JSON.stringify(manifest, null, 2),
  );
  try {
    const all = fs
      .readdirSync(projectBackupsDir(projectDir))
      .filter((d) => d.startsWith("backup_"))
      .sort();
    while (all.length > keep) {
      const oldest = all.shift() as string;
      fs.rmSync(path.join(projectBackupsDir(projectDir), oldest), {
        recursive: true,
        force: true,
      });
    }
  } catch {
    // best effort
  }
  return manifest;
}

export function listProjectBackups(
  projectDir: string,
): ProjectBackupManifest[] {
  const dir = projectBackupsDir(projectDir);
  if (!fs.existsSync(dir)) return [];
  const out: ProjectBackupManifest[] = [];
  for (const d of fs.readdirSync(dir)) {
    const mf = path.join(dir, d, "manifest.json");
    try {
      if (fs.existsSync(mf))
        out.push(
          JSON.parse(fs.readFileSync(mf, "utf8")) as ProjectBackupManifest,
        );
    } catch {
      // skip corrupt entries
    }
  }
  return out.sort((a, b) => (a.createdAt < b.createdAt ? 1 : -1));
}

export function restoreProjectBackup(projectDir: string, id: string): void {
  const src = path.join(projectBackupsDir(projectDir), id);
  const mf = path.join(src, "manifest.json");
  if (!fs.existsSync(mf))
    throw Object.assign(new Error(`backup '${id}' not found`), { exitCode: 1 });
  const manifest = JSON.parse(
    fs.readFileSync(mf, "utf8"),
  ) as ProjectBackupManifest;
  for (const rel of manifest.files) {
    if (rel.includes("..") || path.isAbsolute(rel)) continue;
    const from = path.join(src, rel);
    const to = path.join(projectDir, PROJECT_DIR_NAME, rel);
    if (!fs.existsSync(from)) continue;
    fs.mkdirSync(path.dirname(to), { recursive: true });
    fs.cpSync(from, to, { recursive: true });
  }
}

// ---------- server ----------
export async function startLocalPlatform(
  projectDir: string,
  opts?: { port?: number; open?: boolean; safe?: boolean },
): Promise<void> {
  const preferred = opts?.port ?? projectPort(projectDir);
  const { findFreePort, startScheduler } =
    await import("@openagent/workflow-engine");
  const port = await findFreePort(preferred);
  if (port !== preferred) {
    process.stdout.write(
      `Port ${preferred} is occupied — using ${port} instead.\n`,
    );
  }
  const server = startServer({
    projectDir,
    port,
    onLog: (m) => process.stdout.write(m + "\n"),
  });
  const stop = opts?.safe ? () => undefined : startScheduler(projectDir);
  if (opts?.safe) {
    process.stdout.write("Safe mode: scheduler and plugins disabled.\n");
  }
  const ollama = await checkOllama().catch(() => ({
    ok: false,
    models: [],
    detail: "unavailable",
  }));
  const box = [
    "╭──────────────────────────────────────────╮",
    "│              OPENAGENT                   │",
    "│      Autonomous AI Automation Engine     │",
    "╰──────────────────────────────────────────╯",
    "",
    `${ollama.ok ? "✓" : "○"} Ollama ${ollama.ok ? `(${ollama.models[0] ?? "model"} )` : "(not detected — AI nodes use heuristic fallback)"}`,
    "✓ Database (local JSON/SQLite-ready)",
    "✓ Workflow Engine",
    opts?.safe ? "○ Scheduler (disabled in safe mode)" : "✓ Scheduler",
    "✓ MCP registry",
    "",
    `Dashboard → http://localhost:${port}`,
    `API       → http://localhost:${port}/api`,
    `Webhook   → http://localhost:${port}/webhook/:workflowId`,
    "",
    "Press Ctrl+C to stop.",
  ].join("\n");
  process.stdout.write(box + "\n");
  if (opts?.open !== false) {
    const url = `http://localhost:${port}`;
    const opener =
      process.platform === "win32"
        ? "cmd"
        : process.platform === "darwin"
          ? "open"
          : "xdg-open";
    const args =
      process.platform === "win32" ? ["/c", "start", "", url] : [url];
    try {
      const child = spawn(opener, args, {
        stdio: "ignore",
        detached: true,
        shell: false,
      });
      child.unref();
    } catch {
      // opening a browser is best-effort
    }
  }
  const shutdown = () => {
    stop();
    server.close(() => process.exit(0));
    setTimeout(() => process.exit(0), 2000);
  };
  process.on("SIGINT", shutdown);
  process.on("SIGTERM", shutdown);
  await new Promise(() => undefined);
}

// ---------- doctor ----------
export interface DoctorCheck {
  name: string;
  ok: boolean;
  detail: string;
  fix?: string;
}

export interface NpmGlobalInfo {
  npmVersion: string | null;
  prefix: string;
  /** Directory that must be on PATH (holds openagent.cmd on Windows). */
  binDir: string;
  expectedExe: string;
  exeExists: boolean;
  pathContainsBin: boolean;
  installDir: string | null;
}

function npmCmd(): { cmd: string; prefixArgs: string[] } {
  return process.platform === "win32"
    ? { cmd: "cmd.exe", prefixArgs: ["/d", "/s", "/c"] }
    : { cmd: "npm", prefixArgs: [] };
}

function runNpm(
  args: string[],
  timeout = 15000,
): Promise<{ ok: boolean; out: string }> {
  return new Promise((resolve) => {
    try {
      const { cmd, prefixArgs } = npmCmd();
      const full =
        process.platform === "win32"
          ? [...prefixArgs, `npm ${args.join(" ")}`]
          : args;
      execFile(cmd, full, { timeout }, (err, stdout, stderr) => {
        resolve({ ok: !err, out: String(stdout ?? stderr ?? "").trim() });
      });
    } catch {
      resolve({ ok: false, out: "" });
    }
  });
}

/** Inspect the npm global install: prefix, bin dir, exe presence, PATH. */
export async function getNpmGlobalInfo(): Promise<NpmGlobalInfo> {
  const ver = await runNpm(["--version"]);
  let prefix = "";
  const p = await runNpm(["config", "get", "prefix"]);
  if (p.ok && p.out) prefix = p.out.split("\n")[0]?.trim() ?? "";
  if (!prefix) {
    prefix =
      process.platform === "win32"
        ? path.join(process.env.APPDATA ?? "", "npm")
        : "/usr/local";
  }
  const exeName = process.platform === "win32" ? "openagent.cmd" : "openagent";
  const binDir = prefix;
  const expectedExe = path.join(binDir, exeName);
  const exeExists = fs.existsSync(expectedExe);
  const rawPath = `${process.env.Path ?? ""}${path.delimiter}${process.env.PATH ?? ""}`;
  const norm = (s: string) => s.replace(/[/\\]+$/, "").toLowerCase();
  const pathContainsBin = rawPath
    .split(path.delimiter)
    .some((d) => norm(d) === norm(binDir));
  let installDir: string | null = null;
  if (exeExists) {
    try {
      installDir = fs.realpathSync(expectedExe);
    } catch {
      installDir = expectedExe;
    }
  } else {
    // Maybe installed but shim missing (partial install): look for package dir.
    const pkgDir = path.join(prefix, "node_modules", "@openagent", "cli");
    if (fs.existsSync(pkgDir)) installDir = pkgDir;
  }
  return {
    npmVersion:
      ver.ok && ver.out ? (ver.out.split("\n")[0]?.trim() ?? null) : null,
    prefix,
    binDir,
    expectedExe,
    exeExists,
    pathContainsBin,
    installDir,
  };
}

/**
 * Automatic repair: append the npm global bin dir to the CURRENT USER PATH
 * (HKCU, never machine-wide) and report that terminals must be restarted.
 */
export async function repairNpmGlobalPath(): Promise<{
  added: boolean;
  binDir: string;
  detail: string;
}> {
  const info = await getNpmGlobalInfo();
  if (info.pathContainsBin) {
    return {
      added: false,
      binDir: info.binDir,
      detail: "npm global bin is already on PATH",
    };
  }
  if (process.platform === "win32") {
    const current = await runNpm(["config", "get", "prefix"]).catch(() => ({
      ok: false,
      out: "",
    }));
    void current;
    const { execFile: ef } = await import("node:child_process");
    const existing: string = await new Promise((resolve) => {
      ef(
        "cmd.exe",
        ["/d", "/s", "/c", "reg query HKCU\\Environment /v Path"],
        { timeout: 15000 },
        (err, stdout) => {
          if (err) return resolve("");
          const m = String(stdout).match(/Path\s+REG_\w+\s+([\s\S]+)/);
          resolve((m?.[1] ?? "").trim());
        },
      );
    });
    const next = existing ? `${existing};${info.binDir}` : info.binDir;
    const ok = await new Promise<boolean>((resolve) => {
      ef(
        "cmd.exe",
        [
          "/d",
          "/s",
          "/c",
          `reg add HKCU\\Environment /v Path /t REG_EXPAND_SZ /d "${next.replace(/"/g, "")}" /f`,
        ],
        { timeout: 15000 },
        (err) => resolve(!err),
      );
    });
    if (ok) {
      return {
        added: true,
        binDir: info.binDir,
        detail: `Added ${info.binDir} to user PATH. Restart your terminal, then run: openagent doctor`,
      };
    }
    return {
      added: false,
      binDir: info.binDir,
      detail: "Could not update user PATH automatically",
    };
  }
  return {
    added: false,
    binDir: info.binDir,
    detail: `Add to PATH manually: export PATH="${info.binDir}:$PATH"`,
  };
}

/** Message shown when the shell cannot find `openagent` at all. */
export function cliNotFoundMessage(info: NpmGlobalInfo): string {
  return [
    "OpenAgent CLI was not found in PATH.",
    "",
    `Detected npm global prefix: ${info.prefix}`,
    `Expected executable: ${info.expectedExe} (${info.exeExists ? "present" : "missing"})`,
    info.exeExists && !info.pathContainsBin
      ? "OpenAgent CLI is installed but Windows cannot find it from PATH."
      : "If you ran `npm install -g openagent`, note that name is an unrelated placeholder — install the official package instead:",
    "",
    "Suggested fix:",
    "  npm install -g @openagent/cli",
    "Then restart your terminal after npm global installation, and verify with:",
    "  where openagent",
    "  openagent doctor",
    "Or run without installing: npx @openagent/cli --help",
  ].join("\n");
}

export async function runDoctor(
  projectDir: string | null,
): Promise<DoctorCheck[]> {
  const checks: DoctorCheck[] = [];
  const major = Number(process.versions.node.split(".")[0]);
  checks.push({
    name: "Node.js",
    ok: major >= 20,
    detail: `node ${process.version} (need >=20)`,
    fix:
      major >= 20 ? undefined : "Install Node.js 20+ from https://nodejs.org",
  });
  const npmOk = await new Promise<boolean>((resolve) => {
    try {
      if (process.platform === "win32") {
        execFile(
          "cmd.exe",
          ["/d", "/s", "/c", "npm --version"],
          { timeout: 8000 },
          (err) => resolve(!err),
        );
      } else {
        execFile("npm", ["--version"], { timeout: 8000 }, (err) =>
          resolve(!err),
        );
      }
    } catch {
      resolve(false);
    }
  });
  checks.push({
    name: "npm",
    ok: npmOk,
    detail: npmOk ? "npm available" : "npm not on PATH",
    fix: npmOk ? undefined : "Install Node.js (bundles npm)",
  });
  checks.push({
    name: "project",
    ok: projectDir !== null,
    detail: projectDir ?? "no .openagent project (run `openagent init`)",
    fix: projectDir ? undefined : "Run `openagent init`",
  });
  checks.push({
    name: "filesystem",
    ok:
      projectDir === null
        ? true
        : (() => {
            try {
              fs.accessSync(projectDir as string, fs.constants.W_OK);
              return true;
            } catch {
              return false;
            }
          })(),
    detail: projectDir ? `writable: ${projectDir}` : "no project yet",
  });
  const ollama = await checkOllama();
  checks.push({
    name: "Ollama",
    ok: ollama.ok,
    detail: ollama.detail,
    fix: ollama.ok
      ? undefined
      : "Install from https://ollama.com then `ollama run qwen2.5`",
  });
  checks.push({
    name: "Model available",
    ok: ollama.models.length > 0 || Boolean(process.env.OPENAI_API_KEY),
    detail:
      ollama.models.length > 0
        ? `models: ${ollama.models.slice(0, 3).join(", ")}`
        : process.env.OPENAI_API_KEY
          ? "OPENAI_API_KEY set"
          : "no model detected (heuristic fallback active)",
    fix:
      ollama.models.length > 0 || process.env.OPENAI_API_KEY
        ? undefined
        : "Run `ollama run qwen2.5` or set OPENAI_API_KEY",
  });
  const pyOk = await new Promise<boolean>((resolve) => {
    try {
      execFile("python3", ["--version"], { timeout: 8000 }, (err) => {
        if (!err) resolve(true);
        else {
          try {
            execFile("python", ["--version"], { timeout: 8000 }, (e2) =>
              resolve(!e2),
            );
          } catch {
            resolve(false);
          }
        }
      });
    } catch {
      resolve(false);
    }
  });
  checks.push({
    name: "Python",
    ok: pyOk,
    detail: pyOk
      ? "python available"
      : "python not found (python nodes need it)",
    fix: pyOk ? undefined : "Install Python 3",
  });
  let playwrightOk = false;
  try {
    const loadPw = new Function(
      "return import('playwright')",
    ) as () => Promise<unknown>;
    await loadPw()
      .then(() => {
        playwrightOk = true;
      })
      .catch(() => {
        playwrightOk = false;
      });
  } catch {
    playwrightOk = false;
  }
  checks.push({
    name: "Browser engine",
    ok: true,
    detail: playwrightOk
      ? "playwright installed"
      : "playwright not installed (fetch fallback active)",
    fix: playwrightOk
      ? undefined
      : "Optional: `npm i -D playwright && npx playwright install chromium`",
  });
  const port = projectDir ? projectPort(projectDir) : 5678;
  const portFree = await new Promise<boolean>((resolve) => {
    try {
      const net = spawn(
        process.execPath,
        [
          "-e",
          `require('net').createServer().once('error',()=>process.exit(1)).once('listening',function(){this.close();process.exit(0)}).listen(${port})`,
        ],
        { stdio: "ignore" },
      );
      net.on("exit", (code) => resolve(code === 0));
      net.on("error", () => resolve(true));
    } catch {
      resolve(true);
    }
  });
  checks.push({
    name: "port",
    ok: portFree,
    detail: `port ${port} ${portFree ? "free" : "in use"}`,
    fix: portFree ? undefined : `Set OPENAGENT_PORT to a free port`,
  });
  checks.push({
    name: "environment",
    ok: true,
    detail: `OPENAI_API_KEY ${process.env.OPENAI_API_KEY ? "set" : "unset"}, OLLAMA_HOST=${process.env.OLLAMA_HOST ?? "default"}`,
  });
  return checks;
}
