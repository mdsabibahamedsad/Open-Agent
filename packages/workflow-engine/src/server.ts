import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { runWorkflow } from "./engine.js";
import { validateWorkflow } from "./schema.js";
import type { ExecutionRecord, WorkflowDefinition } from "./types.js";
import { FileCredentialResolver } from "./credentials.js";
import { FileMemoryManager } from "./memory.js";
import { ToolRegistry } from "./tools.js";

export interface ServerOptions {
  projectDir: string;
  port: number;
  onLog?: (msg: string) => void;
}

function wfDir(projectDir: string): string {
  return path.join(projectDir, ".openagent", "workflows");
}

function execDir(projectDir: string): string {
  return path.join(projectDir, ".openagent", "executions");
}

export function listWorkflows(projectDir: string): WorkflowDefinition[] {
  const dir = wfDir(projectDir);
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
      // skip corrupt files
    }
  }
  return out;
}

export function saveExecution(projectDir: string, rec: ExecutionRecord): void {
  const dir = execDir(projectDir);
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(
    path.join(dir, `${rec.executionId}.json`),
    JSON.stringify(rec, null, 2),
  );
}

function sendJson(
  res: http.ServerResponse,
  status: number,
  body: unknown,
): void {
  res.statusCode = status;
  res.setHeader("content-type", "application/json");
  res.end(JSON.stringify(body));
}

function readBody(req: http.IncomingMessage): Promise<unknown> {
  return new Promise((resolve) => {
    let data = "";
    req.on("data", (c) => {
      data += c;
      if (data.length > 4 * 1024 * 1024) req.destroy();
    });
    req.on("end", () => {
      if (!data) resolve({});
      else {
        try {
          resolve(JSON.parse(data));
        } catch {
          resolve({ _raw: data });
        }
      }
    });
  });
}

function dashboardHtml(port: number): string {
  return `<!doctype html><html><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/><title>OpenAgent</title>
<style>body{font-family:ui-sans-serif,system-ui;background:#0b0e14;color:#e6edf3;margin:0}header{padding:24px 32px;border-bottom:1px solid #1c2333}h1{margin:0;font-size:22px}a{color:#7aa2f7}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px;padding:32px}.card{background:#111624;border:1px solid #1c2333;border-radius:12px;padding:20px}code{background:#0b0e14;padding:2px 6px;border-radius:6px}</style></head>
<body><header><h1>OPENAGENT — Autonomous AI Automation Engine</h1><p>API on <code>http://localhost:${port}/api</code> · Webhooks on <code>http://localhost:${port}/webhook/:workflowId</code></p></header>
<div class="grid">
<div class="card"><h3>Workflows</h3><p><a href="/api/workflows">GET /api/workflows</a></p><p>Visual editor: run <code>openagent dev</code> or open the Next.js app.</p></div>
<div class="card"><h3>Health</h3><p><a href="/health">GET /health</a></p></div>
<div class="card"><h3>Executions</h3><p><a href="/api/executions">GET /api/executions</a></p></div>
<div class="card"><h3>CLI</h3><p><code>openagent workflow list</code><br/><code>openagent workflow run &lt;id&gt;</code></p></div>
</div></body></html>`;
}

export function startServer(opts: ServerOptions): http.Server {
  const { projectDir, port } = opts;
  const log = opts.onLog ?? (() => undefined);
  const server = http.createServer(async (req, res) => {
    const url = new URL(req.url ?? "/", `http://localhost:${port}`);
    // CORS for local dashboard.
    res.setHeader("access-control-allow-origin", "*");
    res.setHeader("access-control-allow-methods", "GET,POST,OPTIONS");
    res.setHeader("access-control-allow-headers", "content-type,authorization");
    if (req.method === "OPTIONS") {
      res.statusCode = 204;
      res.end();
      return;
    }
    try {
      if (url.pathname === "/" && req.method === "GET") {
        res.setHeader("content-type", "text/html");
        res.end(dashboardHtml(port));
        return;
      }
      if (url.pathname === "/health" && req.method === "GET") {
        sendJson(res, 200, {
          ok: true,
          service: "openagent",
          ts: new Date().toISOString(),
        });
        return;
      }
      if (url.pathname === "/api/workflows" && req.method === "GET") {
        sendJson(res, 200, { workflows: listWorkflows(projectDir) });
        return;
      }
      if (url.pathname === "/api/workflows" && req.method === "POST") {
        const body = (await readBody(req)) as Record<string, unknown>;
        const def = (body.workflow ?? body) as WorkflowDefinition;
        const v = validateWorkflow(def);
        if (!v.ok) {
          sendJson(res, 400, { error: "invalid workflow", issues: v.errors });
          return;
        }
        fs.mkdirSync(wfDir(projectDir), { recursive: true });
        fs.writeFileSync(
          path.join(wfDir(projectDir), `${def.id}.json`),
          JSON.stringify(def, null, 2),
        );
        sendJson(res, 201, { ok: true, workflow: def });
        return;
      }
      if (url.pathname === "/api/executions" && req.method === "GET") {
        const dir = execDir(projectDir);
        const items: ExecutionRecord[] = [];
        if (fs.existsSync(dir)) {
          for (const f of fs.readdirSync(dir).slice(-50)) {
            try {
              items.push(
                JSON.parse(
                  fs.readFileSync(path.join(dir, f), "utf8"),
                ) as ExecutionRecord,
              );
            } catch {
              // skip
            }
          }
        }
        sendJson(res, 200, {
          executions: items.sort((a, b) =>
            a.startedAt < b.startedAt ? 1 : -1,
          ),
        });
        return;
      }
      const runMatch = url.pathname.match(/^\/api\/workflows\/([^/]+)\/run$/);
      if (runMatch && req.method === "POST") {
        const id = decodeURIComponent(runMatch[1] as string);
        const file = path.join(wfDir(projectDir), `${id}.json`);
        if (!fs.existsSync(file)) {
          sendJson(res, 404, { error: `workflow '${id}' not found` });
          return;
        }
        const def = JSON.parse(
          fs.readFileSync(file, "utf8"),
        ) as WorkflowDefinition;
        const body = (await readBody(req)) as { input?: unknown };
        const rec = await runWorkflow(def, {
          input: body.input ?? {},
          credentials: new FileCredentialResolver(projectDir),
          memory: new FileMemoryManager(projectDir),
          tools: new ToolRegistry(),
          projectDir,
        });
        saveExecution(projectDir, rec);
        sendJson(res, 200, { execution: rec });
        return;
      }
      const execMatch = url.pathname.match(/^\/api\/executions\/([^/]+)$/);
      if (execMatch && req.method === "GET") {
        const file = path.join(
          execDir(projectDir),
          `${decodeURIComponent(execMatch[1] as string)}.json`,
        );
        if (!fs.existsSync(file)) {
          sendJson(res, 404, { error: "execution not found" });
          return;
        }
        sendJson(res, 200, {
          execution: JSON.parse(fs.readFileSync(file, "utf8")),
        });
        return;
      }
      const hookMatch = url.pathname.match(/^\/webhook\/([^/]+)$/);
      if (hookMatch && (req.method === "POST" || req.method === "GET")) {
        const id = decodeURIComponent(hookMatch[1] as string);
        const file = path.join(wfDir(projectDir), `${id}.json`);
        if (!fs.existsSync(file)) {
          sendJson(res, 404, { error: `workflow '${id}' not found` });
          return;
        }
        const def = JSON.parse(
          fs.readFileSync(file, "utf8"),
        ) as WorkflowDefinition;
        const body =
          req.method === "POST"
            ? await readBody(req)
            : Object.fromEntries(url.searchParams);
        const rec = await runWorkflow(def, {
          input: body,
          credentials: new FileCredentialResolver(projectDir),
          memory: new FileMemoryManager(projectDir),
          tools: new ToolRegistry(),
          projectDir,
        });
        saveExecution(projectDir, rec);
        sendJson(res, 200, {
          executionId: rec.executionId,
          status: rec.status,
        });
        return;
      }
      sendJson(res, 404, {
        error: "not found",
        hint: "GET /health, /api/workflows, POST /webhook/:workflowId",
      });
    } catch (e) {
      log(`request error: ${e instanceof Error ? e.message : String(e)}`);
      sendJson(res, 500, { error: e instanceof Error ? e.message : String(e) });
    }
  });
  server.listen(port, () =>
    log(`OpenAgent API listening on http://localhost:${port}`),
  );
  return server;
}
