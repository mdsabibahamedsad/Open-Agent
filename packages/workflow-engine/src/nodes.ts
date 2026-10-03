import { execFile } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { chatWithProvider } from "./providers.js";
import type {
  ExecutionContext,
  NodeResult,
  OpenAgentNode,
  WorkflowNode,
} from "./types.js";

function cfg<T>(node: WorkflowNode, key: string, fallback: T): T {
  const c = (node.config ?? {}) as Record<string, unknown>;
  return (c[key] as T) ?? fallback;
}

function renderTemplate(text: string, scope: Record<string, unknown>): string {
  // Minimal {{ json path }} interpolation: {{input}}, {{input.foo}}, {{env.KEY}}, {{nodes.<id>}}
  return text.replace(/\{\{\s*([^}]+?)\s*\}\}/g, (_, expr: string) => {
    const val = lookupPath(expr.trim(), scope);
    if (val === undefined || val === null) return "";
    return typeof val === "string" ? val : JSON.stringify(val);
  });
}

function lookupPath(expr: string, scope: Record<string, unknown>): unknown {
  const parts = expr.split(".");
  let cur: unknown = scope;
  for (const p of parts) {
    if (cur === null || cur === undefined) return undefined;
    if (typeof cur !== "object") return undefined;
    cur = (cur as Record<string, unknown>)[p];
  }
  return cur;
}

function scopeFor(
  node: WorkflowNode,
  ctx: ExecutionContext,
  extra?: unknown,
): Record<string, unknown> {
  const nodes: Record<string, unknown> = {};
  for (const [k, v] of ctx.nodeOutputs) nodes[k] = v;
  void node;
  return {
    input: extra ?? ctx.input,
    nodes,
    env: Object.fromEntries(
      Object.entries(ctx.env).map(([k, v]) => [k, v ?? ""]),
    ),
  };
}

function resolveCredentialRef(value: unknown, ctx: ExecutionContext): unknown {
  if (typeof value === "string" && value.startsWith("$cred:")) {
    return ctx.credentials.resolve(value.slice(6));
  }
  return value;
}

async function httpNode(
  node: WorkflowNode,
  ctx: ExecutionContext,
): Promise<NodeResult> {
  const scope = scopeFor(node, ctx);
  const rawUrl = renderTemplate(String(cfg(node, "url", "")), scope);
  if (!rawUrl) throw new Error("http node requires config.url");
  const method = String(cfg(node, "method", "GET")).toUpperCase();
  const headers = (cfg<Record<string, unknown>>(node, "headers", {}) ??
    {}) as Record<string, unknown>;
  const resolvedHeaders: Record<string, string> = {};
  for (const [k, v] of Object.entries(headers)) {
    const rv = resolveCredentialRef(v, ctx);
    resolvedHeaders[k] = String(rv ?? "");
  }
  let body: string | undefined;
  const payload = cfg<unknown>(node, "body", undefined);
  if (payload !== undefined && method !== "GET" && method !== "HEAD") {
    body =
      typeof payload === "string"
        ? renderTemplate(payload, scope)
        : JSON.stringify(payload);
    if (!resolvedHeaders["content-type"] && !resolvedHeaders["Content-Type"]) {
      resolvedHeaders["content-type"] = "application/json";
    }
  }
  const timeout = Number(cfg(node, "timeout", node.timeout ?? 30000));
  const ctrl = new AbortController();
  const t = setTimeout(
    () => ctrl.abort(new Error(`http timeout after ${timeout}ms`)),
    timeout,
  );
  const onAbort = () => ctrl.abort(ctx.signal.reason);
  if (ctx.signal.aborted) ctrl.abort(ctx.signal.reason);
  else ctx.signal.addEventListener("abort", onAbort, { once: true });
  try {
    const res = await fetch(rawUrl, {
      method,
      headers: resolvedHeaders,
      body,
      signal: ctrl.signal,
    });
    const text = await res.text();
    let data: unknown = text;
    try {
      data = text ? JSON.parse(text) : null;
    } catch {
      data = text;
    }
    if (!res.ok)
      throw new Error(
        `HTTP ${res.status} ${res.statusText}: ${String(text).slice(0, 500)}`,
      );
    return { output: data, logs: [`${method} ${rawUrl} -> ${res.status}`] };
  } finally {
    clearTimeout(t);
    ctx.signal.removeEventListener("abort", onAbort);
  }
}

function nodeDef(
  id: string,
  name: string,
  description: string,
  execute: OpenAgentNode["execute"],
): OpenAgentNode {
  return { id, name, description, version: "1.0.0", execute };
}

export const CORE_NODES: OpenAgentNode[] = [
  nodeDef(
    "manual",
    "Manual Trigger",
    "Starts with the workflow input payload.",
    async (_n, ctx) => ({
      output: ctx.input ?? {},
    }),
  ),
  nodeDef(
    "webhook",
    "Webhook Trigger",
    "Starts from an incoming webhook payload.",
    async (_n, ctx) => ({
      output: ctx.input ?? {},
    }),
  ),
  nodeDef(
    "schedule",
    "Schedule Trigger",
    "Starts on a schedule tick.",
    async (_n, ctx) => ({
      output: {
        ...(typeof ctx.input === "object"
          ? (ctx.input as object)
          : { input: ctx.input }),
        tick: new Date().toISOString(),
      },
    }),
  ),
  nodeDef(
    "cron",
    "Cron Trigger",
    "Alias for schedule trigger.",
    async (_n, ctx) => ({
      output: ctx.input ?? { tick: new Date().toISOString() },
    }),
  ),
  nodeDef(
    "http-trigger",
    "HTTP Trigger",
    "Starts from an HTTP call.",
    async (_n, ctx) => ({
      output: ctx.input ?? {},
    }),
  ),
  nodeDef(
    "event",
    "Event Trigger",
    "Starts from a named event.",
    async (node, ctx) => ({
      output: { event: cfg(node, "event", "default"), payload: ctx.input },
    }),
  ),
  nodeDef(
    "file-watcher",
    "File Watcher",
    "Starts when a file changes (passes input through).",
    async (_n, ctx) => ({
      output: ctx.input ?? {},
    }),
  ),
  nodeDef(
    "email-trigger",
    "Email Trigger",
    "Starts from an inbound email (passes input through).",
    async (_n, ctx) => ({
      output: ctx.input ?? {},
    }),
  ),
  nodeDef("http", "HTTP Request", "Performs an HTTP request.", httpNode),
  nodeDef("rest", "REST API", "Alias for HTTP request.", httpNode),
  nodeDef(
    "graphql",
    "GraphQL",
    "Executes a GraphQL operation.",
    async (node, ctx) => {
      const scope = scopeFor(node, ctx);
      const endpoint = renderTemplate(
        String(cfg(node, "endpoint", cfg(node, "url", ""))),
        scope,
      );
      const query = renderTemplate(String(cfg(node, "query", "")), scope);
      if (!endpoint || !query)
        throw new Error(
          "graphql node requires config.endpoint and config.query",
        );
      const res = await fetch(endpoint, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ query, variables: cfg(node, "variables", {}) }),
        signal: ctx.signal,
      });
      const json = (await res.json()) as { errors?: unknown; data?: unknown };
      if (!res.ok || json.errors)
        throw new Error(
          `GraphQL error: ${JSON.stringify(json.errors ?? res.status).slice(0, 500)}`,
        );
      return { output: json.data };
    },
  ),
  nodeDef(
    "web-search",
    "Web Search",
    "Searches the web via DuckDuckGo instant answers (no key required).",
    async (node, ctx) => {
      const scope = scopeFor(node, ctx);
      const query =
        renderTemplate(String(cfg(node, "query", cfg(node, "q", ""))), scope) ||
        String(ctx.input ?? "");
      if (!query) throw new Error("web-search requires config.query");
      const url = `https://api.duckduckgo.com/?q=${encodeURIComponent(query)}&format=json&no_html=1&skip_disambig=1`;
      const res = await fetch(url, {
        signal: ctx.signal,
        headers: { "user-agent": "openagent/1.0" },
      });
      if (!res.ok) throw new Error(`web search HTTP ${res.status}`);
      const json = (await res.json()) as {
        AbstractText?: string;
        AbstractURL?: string;
        RelatedTopics?: Array<{ Text?: string; FirstURL?: string }>;
      };
      const results = (json.RelatedTopics ?? [])
        .slice(0, 5)
        .map((t) => ({ text: t.Text ?? "", url: t.FirstURL ?? "" }));
      return {
        output: {
          query,
          abstract: json.AbstractText ?? "",
          abstractUrl: json.AbstractURL ?? "",
          results,
        },
      };
    },
  ),
  nodeDef(
    "transform",
    "Transform",
    "Maps data with a template or field mapping.",
    async (node, ctx) => {
      const scope = scopeFor(
        node,
        ctx,
        ctx.nodeOutputs.get(prevOutputKey(ctx)) ?? ctx.input,
      );
      const template = cfg<unknown>(
        node,
        "template",
        cfg(node, "mapping", undefined),
      );
      if (template === undefined) return { output: scope.input };
      if (typeof template === "string") {
        return { output: renderTemplate(template, scope) };
      }
      const out: Record<string, unknown> = {};
      for (const [k, v] of Object.entries(
        template as Record<string, unknown>,
      )) {
        out[k] = typeof v === "string" ? renderTemplate(v, scope) : v;
      }
      return { output: out };
    },
  ),
  nodeDef("json", "JSON", "Parses or stringifies JSON.", async (node, ctx) => {
    const input = lastOutput(ctx);
    const op = String(cfg(node, "operation", "parse"));
    if (op === "stringify") return { output: JSON.stringify(input) };
    if (typeof input === "string") return { output: JSON.parse(input) };
    return { output: input };
  }),
  nodeDef(
    "csv",
    "CSV",
    "Parses simple CSV text into rows.",
    async (node, ctx) => {
      const input = String(lastOutput(ctx) ?? "");
      const delim = String(cfg(node, "delimiter", ","));
      const lines = input.split(/\r?\n/).filter((l) => l.length > 0);
      if (lines.length === 0) return { output: [] };
      const headers = (lines[0] as string).split(delim).map((h) => h.trim());
      const rows = lines.slice(1).map((l) => {
        const cells = l.split(delim);
        const row: Record<string, string> = {};
        headers.forEach((h, i) => {
          row[h] = (cells[i] ?? "").trim();
        });
        return row;
      });
      return { output: rows };
    },
  ),
  nodeDef("text", "Text", "Renders a text template.", async (node, ctx) => {
    const scope = scopeFor(node, ctx);
    return {
      output: renderTemplate(
        String(cfg(node, "text", cfg(node, "template", ""))),
        scope,
      ),
    };
  }),
  nodeDef(
    "javascript",
    "JavaScript",
    "Runs sandboxed JavaScript (vm) with `input`.",
    async (node, ctx) => {
      const code = String(cfg(node, "code", "return input;"));
      const input = lastOutput(ctx);
      const sandbox = {
        input,
        env: Object.fromEntries(
          Object.entries(ctx.env).map(([k, v]) => [k, v ?? ""]),
        ),
        JSON,
        Math,
        Date,
      };
      const script = new vm.Script(`(function(){ ${code} })()`);
      const context = vm.createContext(sandbox);
      const output = script.runInContext(context, {
        timeout: Number(cfg(node, "timeout", node.timeout ?? 5000)),
      });
      if (
        output !== undefined &&
        typeof (output as unknown as { then?: unknown }).then === "function"
      ) {
        throw new Error(
          "async JavaScript nodes are not supported; return a plain value",
        );
      }
      return { output: output === undefined ? input : output };
    },
  ),
  nodeDef("code", "Code", "Alias for JavaScript.", async (node, ctx) => {
    return executeNode("javascript", node, ctx);
  }),
  nodeDef(
    "python",
    "Python",
    "Runs a Python snippet via python3 with JSON on stdin.",
    async (node, ctx) => {
      const code = String(
        cfg(
          node,
          "code",
          "import sys,json; print(json.dumps(json.load(sys.stdin)))",
        ),
      );
      const input = lastOutput(ctx);
      const output = await new Promise<string>((resolve, reject) => {
        const child = execFile(
          "python3",
          ["-c", code],
          {
            timeout: Number(cfg(node, "timeout", node.timeout ?? 15000)),
            maxBuffer: 4 * 1024 * 1024,
          },
          (err, stdout, stderr) => {
            if (err)
              reject(
                new Error(
                  `python failed: ${String(stderr || err.message).slice(0, 1000)}`,
                ),
              );
            else resolve(stdout);
          },
        );
        child.stdin?.write(JSON.stringify(input ?? null));
        child.stdin?.end();
      });
      const trimmed = output.trim();
      try {
        return { output: trimmed ? JSON.parse(trimmed) : null };
      } catch {
        return { output: trimmed };
      }
    },
  ),
  nodeDef(
    "shell",
    "Shell",
    "Runs a shell command with allowlist enforcement.",
    async (node, ctx) => {
      const scope = scopeFor(node, ctx);
      const command = renderTemplate(String(cfg(node, "command", "")), scope);
      if (!command) throw new Error("shell node requires config.command");
      const allow = process.env.OPENAGENT_SHELL_ALLOW ?? "";
      const denied = [
        "rm -rf",
        "mkfs",
        ":(){",
        "shutdown",
        "reboot",
        "format ",
      ];
      if (denied.some((d) => command.includes(d)))
        throw new Error("shell command denied by policy");
      if (
        allow &&
        !allow.split(",").some((p) => command.trim().startsWith(p.trim()))
      ) {
        throw new Error(
          `shell command not in OPENAGENT_SHELL_ALLOW (${allow})`,
        );
      }
      if (process.env.OPENAGENT_SHELL_DENY_ALL === "1")
        throw new Error(
          "shell execution is disabled (OPENAGENT_SHELL_DENY_ALL=1)",
        );
      const output = await new Promise<string>((resolve, reject) => {
        const isWin = process.platform === "win32";
        const child = execFile(
          isWin ? "cmd.exe" : "sh",
          isWin ? ["/d", "/s", "/c", command] : ["-c", command],
          {
            timeout: Number(cfg(node, "timeout", node.timeout ?? 15000)),
            maxBuffer: 4 * 1024 * 1024,
          },
          (err, stdout, stderr) => {
            if (err)
              reject(
                new Error(
                  `shell failed: ${String(stderr || err.message).slice(0, 1000)}`,
                ),
              );
            else resolve(stdout);
          },
        );
        void child;
      });
      return { output: output.trim() };
    },
  ),
  nodeDef("terminal", "Terminal", "Alias for Shell.", async (node, ctx) =>
    executeNode("shell", node, ctx),
  ),
  nodeDef(
    "file",
    "File",
    "Reads or writes files inside the project workspace.",
    async (node, ctx) => {
      const op = String(cfg(node, "operation", "read"));
      const rel = String(cfg(node, "path", ""));
      if (!rel) throw new Error("file node requires config.path");
      const base = path.resolve(process.cwd());
      const full = path.resolve(base, rel);
      if (!full.startsWith(base))
        throw new Error("file path escapes workspace");
      if (op === "write") {
        const scope = scopeFor(node, ctx);
        const content = renderTemplate(String(cfg(node, "content", "")), scope);
        fs.mkdirSync(path.dirname(full), { recursive: true });
        fs.writeFileSync(full, content);
        return { output: { path: rel, bytes: content.length } };
      }
      if (op === "append") {
        const scope = scopeFor(node, ctx);
        const content = renderTemplate(String(cfg(node, "content", "")), scope);
        fs.mkdirSync(path.dirname(full), { recursive: true });
        fs.appendFileSync(full, content);
        return { output: { path: rel, appended: content.length } };
      }
      if (op === "list") {
        return { output: fs.readdirSync(full) };
      }
      const text = fs.readFileSync(full, "utf8");
      return { output: text };
    },
  ),
  nodeDef("delay", "Delay", "Waits before continuing.", async (node, ctx) => {
    const ms = Number(
      cfg(node, "ms", cfg(node, "seconds", 1)) as unknown as number,
    );
    const wait =
      String(cfg(node, "seconds", "")).length > 0 &&
      cfg(node, "ms", undefined) === undefined
        ? Number(cfg(node, "seconds", 1)) * 1000
        : ms;
    await new Promise<void>((resolve, reject) => {
      const t = setTimeout(resolve, Math.min(Math.max(wait || 0, 0), 300000));
      ctx.signal.addEventListener(
        "abort",
        () => {
          clearTimeout(t);
          reject(new Error("cancelled"));
        },
        { once: true },
      );
    });
    return { output: lastOutput(ctx) };
  }),
  nodeDef("if", "IF", "Routes by condition expression.", async (node, ctx) => {
    const cond = String(
      cfg(node, "condition", cfg(node, "expression", "true")),
    );
    const scope = scopeFor(node, ctx);
    const rendered = renderTemplate(cond, scope);
    const result = evaluateCondition(rendered, scope.input);
    return {
      output: { branch: result ? "true" : "false", value: scope.input },
    };
  }),
  nodeDef("condition", "Condition", "Alias for IF.", async (node, ctx) =>
    executeNode("if", node, ctx),
  ),
  nodeDef(
    "switch",
    "Switch",
    "Selects a branch by value matching.",
    async (node, ctx) => {
      const scope = scopeFor(node, ctx);
      const value = renderTemplate(
        String(cfg(node, "value", "{{input}}")),
        scope,
      );
      const cases = cfg<Record<string, unknown>>(node, "cases", {});
      for (const [k, v] of Object.entries(cases ?? {})) {
        if (String(v) === value)
          return { output: { branch: k, value: scope.input } };
      }
      return {
        output: {
          branch: String(cfg(node, "default", "default")),
          value: scope.input,
        },
      };
    },
  ),
  nodeDef(
    "router",
    "Router",
    "Fans out the same payload to all branches.",
    async (_n, ctx) => ({
      output: lastOutput(ctx),
    }),
  ),
  nodeDef(
    "merge",
    "Merge",
    "Merges all upstream outputs into one array.",
    async (_n, ctx) => ({
      output: [...ctx.nodeOutputs.values()],
    }),
  ),
  nodeDef(
    "filter",
    "Filter",
    "Filters an array with a condition.",
    async (node, ctx) => {
      const input = lastOutput(ctx);
      const arr = Array.isArray(input) ? input : [input];
      const cond = String(cfg(node, "condition", "true"));
      return {
        output: arr.filter((item) =>
          evaluateCondition(
            renderTemplate(cond, { ...scopeFor(node, ctx), item }),
            item,
          ),
        ),
      };
    },
  ),
  nodeDef(
    "loop",
    "Loop",
    "Iterates downstream per item (unrolled as array output).",
    async (_n, ctx) => ({
      output: lastOutput(ctx),
    }),
  ),
  nodeDef(
    "batch",
    "Batch",
    "Chunks an array into batches.",
    async (node, ctx) => {
      const input = lastOutput(ctx);
      const arr = Array.isArray(input) ? input : [input];
      const size = Math.max(1, Number(cfg(node, "size", 10)));
      const batches: unknown[][] = [];
      for (let i = 0; i < arr.length; i += size)
        batches.push(arr.slice(i, i + size));
      return { output: batches };
    },
  ),
  nodeDef(
    "retry",
    "Retry",
    "Pass-through marker carrying retry policy.",
    async (_n, ctx) => ({
      output: lastOutput(ctx),
    }),
  ),
  nodeDef(
    "error-handler",
    "Error Handler",
    "Returns the upstream error payload if any.",
    async (_n, ctx) => ({
      output: ctx.input,
    }),
  ),
  nodeDef(
    "database",
    "Database",
    "Executes SQL against SQLite file (local-first).",
    async (node, ctx) => {
      void node;
      void ctx;
      throw new Error(
        "TODO: database node needs a configured provider — set config and install the matching driver (sqlite/postgres).",
      );
    },
  ),
  nodeDef("sqlite", "SQLite", "Alias for Database.", async (node, ctx) =>
    executeNode("database", node, ctx),
  ),
  nodeDef("postgres", "PostgreSQL", "Alias for Database.", async (node, ctx) =>
    executeNode("database", node, ctx),
  ),
  nodeDef(
    "email",
    "Email",
    "Sends email via SMTP env or webhook.",
    async (node, ctx) => {
      const scope = scopeFor(node, ctx);
      const to = renderTemplate(String(cfg(node, "to", "")), scope);
      const subject = renderTemplate(
        String(cfg(node, "subject", "OpenAgent notification")),
        scope,
      );
      const bodyText = renderTemplate(
        String(cfg(node, "body", cfg(node, "text", "{{input}}"))),
        scope,
      );
      const webhook = process.env.OPENAGENT_EMAIL_WEBHOOK;
      if (!to) throw new Error("email node requires config.to");
      if (webhook) {
        await fetch(webhook, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ to, subject, text: bodyText }),
          signal: ctx.signal,
        });
        return { output: { sent: true, to, via: "webhook" } };
      }
      throw new Error(
        "TODO: configure OPENAGENT_EMAIL_WEBHOOK or an SMTP provider to send email.",
      );
    },
  ),
  nodeDef(
    "slack",
    "Slack",
    "Posts a message to Slack via webhook.",
    async (node, ctx) => {
      const scope = scopeFor(node, ctx);
      const text = renderTemplate(
        String(cfg(node, "text", "{{input}}")),
        scope,
      );
      const url = String(
        resolveCredentialRef(
          cfg(node, "webhookUrl", process.env.SLACK_WEBHOOK_URL ?? ""),
          ctx,
        ) ?? "",
      );
      if (!url)
        throw new Error(
          "slack node requires config.webhookUrl or SLACK_WEBHOOK_URL",
        );
      await fetch(url, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ text }),
        signal: ctx.signal,
      });
      return { output: { sent: true } };
    },
  ),
  nodeDef(
    "telegram",
    "Telegram",
    "Sends a Telegram message via bot API.",
    async (node, ctx) => {
      const scope = scopeFor(node, ctx);
      const text = renderTemplate(
        String(cfg(node, "text", "{{input}}")),
        scope,
      );
      const token = String(
        resolveCredentialRef(
          cfg(node, "botToken", process.env.TELEGRAM_BOT_TOKEN ?? ""),
          ctx,
        ) ?? "",
      );
      const chatId = renderTemplate(
        String(cfg(node, "chatId", process.env.TELEGRAM_CHAT_ID ?? "")),
        scope,
      );
      if (!token || !chatId)
        throw new Error("telegram node requires botToken and chatId");
      await fetch(`https://api.telegram.org/bot${token}/sendMessage`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ chat_id: chatId, text }),
        signal: ctx.signal,
      });
      return { output: { sent: true, chatId } };
    },
  ),
  nodeDef(
    "discord",
    "Discord",
    "Posts to a Discord webhook.",
    async (node, ctx) => {
      const scope = scopeFor(node, ctx);
      const content = renderTemplate(
        String(cfg(node, "content", cfg(node, "text", "{{input}}"))),
        scope,
      );
      const url = String(
        resolveCredentialRef(
          cfg(node, "webhookUrl", process.env.DISCORD_WEBHOOK_URL ?? ""),
          ctx,
        ) ?? "",
      );
      if (!url)
        throw new Error(
          "discord node requires config.webhookUrl or DISCORD_WEBHOOK_URL",
        );
      await fetch(url, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ content }),
        signal: ctx.signal,
      });
      return { output: { sent: true } };
    },
  ),
  nodeDef(
    "whatsapp",
    "WhatsApp",
    "Sends via a WhatsApp-compatible provider.",
    async () => {
      throw new Error(
        "TODO: configure a WhatsApp-compatible provider (Twilio/Meta) to enable this node.",
      );
    },
  ),
  nodeDef(
    "git",
    "Git",
    "Runs allowlisted git commands in the workspace.",
    async (node, ctx) => {
      const scope = scopeFor(node, ctx);
      const args = String(
        renderTemplate(
          String(cfg(node, "args", cfg(node, "command", "status"))),
          scope,
        ),
      );
      if (!/^(status|log|diff|branch|rev-parse|remote)/.test(args.trim())) {
        throw new Error(
          "git node only allows read-only subcommands by default (status, log, diff, branch, rev-parse, remote)",
        );
      }
      const out = await new Promise<string>((resolve, reject) => {
        execFile(
          "git",
          args.split(/\s+/),
          { timeout: 15000 },
          (err, stdout, stderr) => {
            if (err)
              reject(new Error(String(stderr || err.message).slice(0, 1000)));
            else resolve(stdout);
          },
        );
      });
      return { output: out.trim() };
    },
  ),
  nodeDef("github", "GitHub", "Calls the GitHub API.", async (node, ctx) => {
    const scope = scopeFor(node, ctx);
    const route = renderTemplate(
      String(cfg(node, "route", "/repos/{owner}/{repo}/issues")),
      scope,
    );
    const token = String(
      resolveCredentialRef(
        cfg(node, "token", process.env.GITHUB_TOKEN ?? ""),
        ctx,
      ) ?? "",
    );
    const res = await fetch(
      `https://api.github.com${route.startsWith("/") ? route : `/${route}`}`,
      {
        headers: {
          accept: "application/vnd.github+json",
          ...(token ? { authorization: `Bearer ${token}` } : {}),
        },
        signal: ctx.signal,
      },
    );
    const json = await res.json();
    if (!res.ok)
      throw new Error(
        `GitHub HTTP ${res.status}: ${JSON.stringify(json).slice(0, 500)}`,
      );
    return { output: json };
  }),
  nodeDef(
    "browser",
    "Browser",
    "Browser automation (requires Playwright; falls back to fetch+extract).",
    async (node, ctx) => {
      const scope = scopeFor(node, ctx);
      const action = String(cfg(node, "action", "extract"));
      const url = renderTemplate(String(cfg(node, "url", "")), scope);
      if (
        action === "open" ||
        action === "extract" ||
        action === "screenshot-text"
      ) {
        if (!url) throw new Error("browser node requires config.url");
        try {
          // Optional peer: resolved at runtime only so the engine works without it.
          const loadPw = new Function(
            "return import('playwright')",
          ) as () => Promise<unknown>;
          const mod = (await loadPw().catch(() => null)) as {
            chromium?: {
              launch: (o?: unknown) => Promise<{
                newPage: () => Promise<{
                  goto: (u: string) => Promise<void>;
                  content: () => Promise<string>;
                  close: () => Promise<void>;
                }>;
                close: () => Promise<void>;
              }>;
            };
          } | null;
          if (mod?.chromium) {
            const browser = await mod.chromium.launch({ headless: true });
            const page = await browser.newPage();
            await page.goto(url);
            const html = await page.content();
            await browser.close();
            return {
              output: { url, html: html.slice(0, 20000), via: "playwright" },
            };
          }
        } catch {
          // fall through to fetch fallback
        }
        const res = await fetch(url, {
          signal: ctx.signal,
          headers: { "user-agent": "openagent/1.0" },
        });
        const html = await res.text();
        const text = html
          .replace(/<script[\s\S]*?<\/script>/gi, " ")
          .replace(/<style[\s\S]*?<\/style>/gi, " ")
          .replace(/<[^>]+>/g, " ")
          .replace(/\s+/g, " ")
          .trim()
          .slice(0, 20000);
        return {
          output: {
            url,
            text,
            via: "fetch-fallback",
            note: "install playwright for full automation",
          },
        };
      }
      throw new Error(
        `TODO: browser action '${action}' needs Playwright wired with click/type/scroll/session support.`,
      );
    },
  ),
  nodeDef(
    "scraper",
    "Scraper",
    "Alias for Browser extract.",
    async (node, ctx) =>
      executeNode(
        "browser",
        { ...node, config: { ...(node.config ?? {}), action: "extract" } },
        ctx,
      ),
  ),
  nodeDef(
    "embeddings",
    "Embeddings",
    "Creates an embedding vector for text.",
    async (node, ctx) => {
      const scope = scopeFor(node, ctx);
      const text = renderTemplate(
        String(cfg(node, "text", "{{input}}")),
        scope,
      );
      const { embedText } = await import("./providers.js");
      return { output: { embedding: await embedText(text) } };
    },
  ),
  nodeDef(
    "vector-search",
    "Vector Search",
    "Searches project memory semantically.",
    async (node, ctx) => {
      const scope = scopeFor(node, ctx);
      const query = renderTemplate(
        String(cfg(node, "query", "{{input}}")),
        scope,
      );
      if (!ctx.memory) return { output: [] };
      return {
        output: await ctx.memory.search(query, Number(cfg(node, "limit", 5))),
      };
    },
  ),
  nodeDef(
    "memory",
    "Memory",
    "Reads/writes agent memory.",
    async (node, ctx) => {
      if (!ctx.memory)
        throw new Error("memory is not enabled for this execution");
      const op = String(cfg(node, "operation", "get"));
      const key = String(cfg(node, "key", "default"));
      if (op === "set") {
        await ctx.memory.set(key, lastOutput(ctx));
        return { output: { ok: true, key } };
      }
      if (op === "append") {
        await ctx.memory.append(key, lastOutput(ctx));
        return { output: { ok: true, key } };
      }
      return { output: await ctx.memory.get(key) };
    },
  ),
  nodeDef(
    "mcp",
    "MCP",
    "Calls an MCP-registered tool (local stub registry).",
    async (node, ctx) => {
      const tool = String(cfg(node, "tool", ""));
      if (!tool) throw new Error("mcp node requires config.tool");
      if (!ctx.tools)
        throw new Error("no tool registry available for MCP call");
      return {
        output: await ctx.tools.execute(
          tool,
          cfg(node, "input", lastOutput(ctx)),
        ),
      };
    },
  ),
  nodeDef(
    "ollama",
    "Ollama",
    "Runs a chat completion against Ollama.",
    async (node, ctx) => executeNode("llm", node, ctx),
  ),
  nodeDef(
    "openai",
    "OpenAI",
    "Runs a chat completion against an OpenAI-compatible API.",
    async (node, ctx) => executeNode("llm", node, ctx),
  ),
  nodeDef(
    "gemini",
    "Gemini",
    "Runs a chat completion against Gemini.",
    async (node, ctx) => executeNode("llm", node, ctx),
  ),
  nodeDef(
    "anthropic",
    "Anthropic",
    "Runs a chat completion against Anthropic.",
    async (node, ctx) => executeNode("llm", node, ctx),
  ),
  nodeDef("llm", "LLM", "Runs a single LLM completion.", async (node, ctx) => {
    const scope = scopeFor(node, ctx);
    const prompt = renderTemplate(
      String(cfg(node, "prompt", cfg(node, "input", "{{input}}"))),
      scope,
    );
    const systemPrompt = renderTemplate(
      String(cfg(node, "systemPrompt", cfg(node, "system", ""))),
      scope,
    );
    const model = String(
      cfg(node, "model", process.env.OPENAGENT_MODEL ?? "ollama:qwen2.5"),
    );
    const res = await chatWithProvider({
      model,
      temperature: Number(cfg(node, "temperature", 0.2)),
      maxTokens: Number(cfg(node, "maxTokens", 1024)),
      messages: [
        ...(systemPrompt
          ? [{ role: "system" as const, content: systemPrompt }]
          : []),
        {
          role: "user" as const,
          content: prompt || JSON.stringify(lastOutput(ctx)),
        },
      ],
      signal: ctx.signal,
    });
    return {
      output: res.content,
      logs: [
        `llm ${res.provider}:${res.model}${res.fallback ? " (heuristic fallback)" : ""}`,
      ],
      tokenUsage: { total: res.content.length },
    };
  }),
  nodeDef(
    "ai-agent",
    "AI Agent",
    "Goal-driven agent with planning, tools, reflection and correction.",
    async (node, ctx) => {
      const scope = scopeFor(node, ctx);
      const goal = renderTemplate(
        String(cfg(node, "goal", cfg(node, "prompt", "{{input}}"))),
        scope,
      );
      const systemPrompt = renderTemplate(
        String(
          cfg(
            node,
            "systemPrompt",
            "You are OpenAgent, a careful automation agent. Use tools when needed.",
          ),
        ),
        scope,
      );
      const model = String(
        cfg(node, "model", process.env.OPENAGENT_MODEL ?? "ollama:qwen2.5"),
      );
      const maxIterations = Math.min(
        Math.max(Number(cfg(node, "maxIterations", 6)), 1),
        20,
      );
      const toolNames = (cfg<string[]>(node, "tools", []) ?? []) as string[];
      let observation =
        typeof scope.input === "string"
          ? scope.input
          : JSON.stringify(scope.input);
      let lastAnswer = "";
      const transcript: string[] = [];
      for (let i = 1; i <= maxIterations; i++) {
        const toolList =
          toolNames.length > 0 && ctx.tools
            ? `\nAvailable tools: ${toolNames.join(", ")}. To use one, reply with TOOL:<name> JSON:<args>.`
            : "";
        const res = await chatWithProvider({
          model,
          temperature: Number(cfg(node, "temperature", 0.2)),
          maxTokens: Number(cfg(node, "maxTokens", 1024)),
          messages: [
            {
              role: "system",
              content: `${systemPrompt}\nIteration ${i}/${maxIterations}. Goal: ${goal}${toolList}\nWhen done, reply with FINAL:<answer>.`,
            },
            {
              role: "user",
              content: `Observation:\n${observation.slice(0, 6000)}\n\nPlan, act, and reflect. If finished, prefix with FINAL:`,
            },
          ],
          signal: ctx.signal,
        });
        transcript.push(
          `--- iteration ${i} (${res.provider}:${res.model}) ---\n${res.content}`,
        );
        const toolMatch = res.content.match(
          /TOOL:([a-zA-Z0-9_-]+)\s*JSON:(.+)/s,
        );
        if (
          toolMatch &&
          ctx.tools &&
          toolNames.includes(toolMatch[1] as string)
        ) {
          let args: unknown = {};
          try {
            args = JSON.parse((toolMatch[2] as string).trim());
          } catch {
            args = { text: (toolMatch[2] as string).trim() };
          }
          try {
            const out = await ctx.tools.execute(
              toolMatch[1] as string,
              args,
              ctx,
            );
            observation = `Tool ${toolMatch[1]} returned: ${JSON.stringify(out).slice(0, 4000)}`;
            continue;
          } catch (e) {
            observation = `Tool ${toolMatch[1]} failed: ${e instanceof Error ? e.message : String(e)}. Correct and continue.`;
            continue;
          }
        }
        const finalMatch = res.content.match(/FINAL:(.+)/s);
        lastAnswer = (finalMatch?.[1] ?? res.content).trim();
        if (finalMatch || i === maxIterations) break;
        observation = `Previous answer draft: ${lastAnswer.slice(0, 3000)}\nValidate, correct gaps, and finalize.`;
      }
      if (ctx.memory) {
        await ctx.memory
          .append("agent:episodic", { goal, answer: lastAnswer })
          .catch(() => undefined);
      }
      return { output: lastAnswer || observation, logs: transcript.slice(-3) };
    },
  ),
  nodeDef(
    "ai-router",
    "AI Router",
    "Routes to a branch by LLM classification.",
    async (node, ctx) => {
      const scope = scopeFor(node, ctx);
      const routes = cfg<string[]>(node, "routes", ["a", "b"]) as string[];
      const text = renderTemplate(
        String(cfg(node, "input", "{{input}}")),
        scope,
      );
      const model = String(
        cfg(node, "model", process.env.OPENAGENT_MODEL ?? "ollama:qwen2.5"),
      );
      try {
        const res = await chatWithProvider({
          model,
          messages: [
            {
              role: "user",
              content: `Classify into exactly one of [${routes.join(", ")}]. Text: ${text.slice(0, 2000)}. Reply with only the label.`,
            },
          ],
          signal: ctx.signal,
        });
        const label =
          routes.find((r) =>
            res.content.toLowerCase().includes(r.toLowerCase()),
          ) ?? routes[0];
        return { output: { branch: label, value: scope.input } };
      } catch {
        return { output: { branch: routes[0], value: scope.input } };
      }
    },
  ),
  nodeDef(
    "ai-classifier",
    "AI Classifier",
    "Classifies input text.",
    async (node, ctx) => executeNode("ai-router", node, ctx),
  ),
  nodeDef(
    "ai-summarizer",
    "AI Summarizer",
    "Summarizes input text.",
    async (node, ctx) => {
      return executeNode(
        "llm",
        {
          ...node,
          config: {
            ...(node.config ?? {}),
            systemPrompt: "Summarize concisely in at most 5 bullet points.",
          },
        },
        ctx,
      );
    },
  ),
  nodeDef(
    "ai-extractor",
    "AI Extractor",
    "Extracts structured data.",
    async (node, ctx) => {
      return executeNode(
        "llm",
        {
          ...node,
          config: {
            ...(node.config ?? {}),
            systemPrompt: "Extract structured JSON. Reply with JSON only.",
          },
        },
        ctx,
      );
    },
  ),
  nodeDef(
    "ai-writer",
    "AI Writer",
    "Writes content from a brief.",
    async (node, ctx) => {
      return executeNode(
        "llm",
        {
          ...node,
          config: {
            ...(node.config ?? {}),
            systemPrompt:
              "You are a skilled writer. Write clearly and concisely.",
          },
        },
        ctx,
      );
    },
  ),
  nodeDef(
    "ai-code",
    "AI Code Generator",
    "Generates code from a description.",
    async (node, ctx) => {
      return executeNode(
        "llm",
        {
          ...node,
          config: {
            ...(node.config ?? {}),
            systemPrompt:
              "You are a senior engineer. Output code with brief explanation.",
          },
        },
        ctx,
      );
    },
  ),
  nodeDef(
    "ai-decision",
    "AI Decision",
    "Makes a structured decision.",
    async (node, ctx) => {
      return executeNode(
        "llm",
        {
          ...node,
          config: {
            ...(node.config ?? {}),
            systemPrompt: "Decide and explain: DECISION then REASONS.",
          },
        },
        ctx,
      );
    },
  ),
  nodeDef(
    "ai-planner",
    "AI Planner",
    "Breaks a goal into steps.",
    async (node, ctx) => {
      return executeNode(
        "llm",
        {
          ...node,
          config: {
            ...(node.config ?? {}),
            systemPrompt: "Break the goal into numbered executable steps.",
          },
        },
        ctx,
      );
    },
  ),
  nodeDef("ai-critic", "AI Critic", "Critiques a draft.", async (node, ctx) => {
    return executeNode(
      "llm",
      {
        ...node,
        config: {
          ...(node.config ?? {}),
          systemPrompt: "Critique the draft and list concrete improvements.",
        },
      },
      ctx,
    );
  }),
  nodeDef(
    "ai-validator",
    "AI Validator",
    "Validates output against criteria.",
    async (node, ctx) => {
      return executeNode(
        "llm",
        {
          ...node,
          config: {
            ...(node.config ?? {}),
            systemPrompt:
              "Validate against the criteria. Reply VALID or INVALID plus reasons.",
          },
        },
        ctx,
      );
    },
  ),
];

const REGISTRY = new Map<string, OpenAgentNode>();
for (const n of CORE_NODES) REGISTRY.set(n.id, n);

export function listNodeTypes(): Array<{
  id: string;
  name: string;
  description: string;
}> {
  return CORE_NODES.map((n) => ({
    id: n.id,
    name: n.name,
    description: n.description,
  }));
}

export function hasNodeType(type: string): boolean {
  return REGISTRY.has(normalizeType(type));
}

export function executeNode(
  type: string,
  node: WorkflowNode,
  ctx: ExecutionContext,
): Promise<NodeResult> {
  const impl = REGISTRY.get(normalizeType(type));
  if (!impl)
    throw new Error(
      `unknown node type '${type}' (run 'openagent node list' for available types)`,
    );
  return impl.execute(node, ctx);
}

function normalizeType(t: string): string {
  const low = t.toLowerCase().replace(/[^a-z0-9]+/g, "-");
  const aliases: Record<string, string> = {
    "manual-trigger": "manual",
    webhook: "webhook",
    ai: "ai-agent",
    agent: "ai-agent",
    "ai-agent": "ai-agent",
    "http-request": "http",
    "java-script": "javascript",
    js: "javascript",
    "ai-summariser": "ai-summarizer",
    "code-generator": "ai-code",
  };
  return aliases[low] ?? low;
}

function prevOutputKey(ctx: ExecutionContext): string {
  const keys = [...ctx.nodeOutputs.keys()];
  return keys[keys.length - 1] ?? "";
}

function lastOutput(ctx: ExecutionContext): unknown {
  const keys = [...ctx.nodeOutputs.keys()];
  if (keys.length === 0) return ctx.input;
  const v = ctx.nodeOutputs.get(keys[keys.length - 1] as string);
  // Special-case IF/router wrappers: unwrap {value} for downstream data flow.
  if (
    v &&
    typeof v === "object" &&
    "value" in (v as object) &&
    "branch" in (v as object)
  ) {
    return (v as { value: unknown }).value;
  }
  return v;
}

function evaluateCondition(rendered: string, input: unknown): boolean {
  const t = rendered.trim().toLowerCase();
  if (t === "true" || t === "yes" || t === "1") return true;
  if (t === "false" || t === "no" || t === "0" || t === "") return false;
  // comparisons like `5 > 3`, `{{input.status}} == ok` (already rendered)
  const m = t.match(
    /^(.+?)\s*(==|!=|>=|<=|>|<|contains|startswith|endswith)\s*(.+)$/,
  );
  if (m) {
    const [, l, op, r] = m as [string, string, string, string];
    const clean = (s: string) => s.trim().replace(/^['"]|['"]$/g, "");
    const lv = clean(l);
    const rv = clean(r);
    const ln = Number(lv);
    const rn = Number(rv);
    const numeric = !Number.isNaN(ln) && !Number.isNaN(rn);
    switch (op) {
      case "==":
        return lv === rv;
      case "!=":
        return lv !== rv;
      case "contains":
        return lv.includes(rv);
      case "startswith":
        return lv.startsWith(rv);
      case "endswith":
        return lv.endsWith(rv);
      case ">":
        return numeric ? ln > rn : lv > rv;
      case "<":
        return numeric ? ln < rn : lv < rv;
      case ">=":
        return numeric ? ln >= rn : lv >= rv;
      case "<=":
        return numeric ? ln <= rn : lv <= rv;
      default:
        return false;
    }
  }
  // non-empty rendered truthy check, or JSON-truthiness of input
  if (t.length > 0 && t !== "true") {
    if (typeof input === "boolean") return input;
    if (typeof input === "number") return input !== 0;
    if (typeof input === "string") return input.length > 0;
    return input !== null && input !== undefined;
  }
  return true;
}
