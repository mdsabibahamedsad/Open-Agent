import type { WorkflowDefinition } from "./types.js";

function pos(x: number, y: number) {
  return { x, y };
}

export interface WorkflowTemplate {
  id: string;
  name: string;
  description: string;
  build(): WorkflowDefinition;
}

export const TEMPLATES: WorkflowTemplate[] = [
  {
    id: "hello-ai",
    name: "Hello AI",
    description:
      "Built-in first-run check: manual trigger → AI agent → output.",
    build: () => ({
      id: `wf_${Date.now()}`,
      name: "Hello AI",
      version: 1,
      nodes: [
        { id: "trigger", type: "manual", position: pos(100, 100), config: {} },
        {
          id: "agent",
          type: "ai-agent",
          position: pos(350, 100),
          config: {
            model: "ollama:qwen2.5",
            goal: "Say hello to the user and confirm you are ready. Input: {{input}}",
            maxIterations: 2,
          },
        },
        {
          id: "output",
          type: "text",
          position: pos(600, 100),
          config: { text: "{{input}}" },
        },
      ],
      edges: [
        { source: "trigger", target: "agent" },
        { source: "agent", target: "output" },
      ],
    }),
  },
  {
    id: "daily-news-digest",
    name: "Daily News Digest",
    description: "Search AI news, summarize top stories, save to a file.",
    build: () => ({
      id: `wf_${Date.now()}`,
      name: "Daily News Digest",
      version: 1,
      nodes: [
        {
          id: "schedule",
          type: "schedule",
          position: pos(100, 100),
          config: { cron: "0 9 * * *" },
        },
        {
          id: "search",
          type: "web-search",
          position: pos(350, 100),
          config: { query: "latest AI news" },
        },
        {
          id: "summarize",
          type: "ai-summarizer",
          position: pos(600, 100),
          config: { model: "ollama:qwen2.5" },
        },
        {
          id: "file",
          type: "file",
          position: pos(850, 100),
          config: {
            operation: "write",
            path: "workspace/digest.md",
            content: "# Daily Digest\n\n{{input}}",
          },
        },
      ],
      edges: [
        { source: "schedule", target: "search" },
        { source: "search", target: "summarize" },
        { source: "summarize", target: "file" },
      ],
    }),
  },
  {
    id: "ai-research-agent",
    name: "AI Research Agent",
    description: "Goal-driven research: search, analyze, write report to file.",
    build: () => ({
      id: `wf_${Date.now()}`,
      name: "AI Research Agent",
      version: 1,
      nodes: [
        { id: "trigger", type: "manual", position: pos(100, 100), config: {} },
        {
          id: "search",
          type: "web-search",
          position: pos(350, 100),
          config: { query: "{{input.topic}}" },
        },
        {
          id: "agent",
          type: "ai-agent",
          position: pos(600, 100),
          config: {
            model: "ollama:qwen2.5",
            goal: "Research {{input.topic}} and write findings",
            maxIterations: 6,
          },
        },
        {
          id: "file",
          type: "file",
          position: pos(850, 100),
          config: {
            operation: "write",
            path: "workspace/research.md",
            content: "{{input}}",
          },
        },
      ],
      edges: [
        { source: "trigger", target: "search" },
        { source: "search", target: "agent" },
        { source: "agent", target: "file" },
      ],
    }),
  },
  {
    id: "website-monitoring",
    name: "Website Monitoring",
    description: "Poll a URL, check status, notify on Slack on failure.",
    build: () => ({
      id: `wf_${Date.now()}`,
      name: "Website Monitoring",
      version: 1,
      nodes: [
        {
          id: "schedule",
          type: "schedule",
          position: pos(100, 100),
          config: { interval: "5m" },
        },
        {
          id: "check",
          type: "http",
          position: pos(350, 100),
          config: { url: "https://example.com", method: "GET" },
          onError: "continue",
        },
        {
          id: "notify",
          type: "slack",
          position: pos(600, 100),
          config: { text: "Website check result: {{input}}" },
        },
      ],
      edges: [
        { source: "schedule", target: "check" },
        { source: "check", target: "notify" },
      ],
    }),
  },
  {
    id: "lead-automation",
    name: "Lead Automation",
    description: "Webhook lead intake → AI qualification → file record.",
    build: () => ({
      id: `wf_${Date.now()}`,
      name: "Lead Automation",
      version: 1,
      nodes: [
        { id: "trigger", type: "webhook", position: pos(100, 100), config: {} },
        {
          id: "agent",
          type: "ai-agent",
          position: pos(400, 100),
          config: { model: "ollama:qwen2.5", goal: "Qualify this lead" },
        },
        {
          id: "file",
          type: "file",
          position: pos(700, 100),
          config: {
            operation: "append",
            path: "workspace/leads.md",
            content: "\n{{input}}\n",
          },
        },
      ],
      edges: [
        { source: "trigger", target: "agent" },
        { source: "agent", target: "file" },
      ],
    }),
  },
  {
    id: "content-pipeline",
    name: "Social Content Pipeline",
    description: "Research topic → write post → save draft.",
    build: () => ({
      id: `wf_${Date.now()}`,
      name: "Social Content Pipeline",
      version: 1,
      nodes: [
        { id: "trigger", type: "manual", position: pos(100, 100), config: {} },
        {
          id: "search",
          type: "web-search",
          position: pos(350, 100),
          config: { query: "{{input.topic}}" },
        },
        {
          id: "write",
          type: "ai-writer",
          position: pos(600, 100),
          config: { model: "ollama:qwen2.5" },
        },
        {
          id: "file",
          type: "file",
          position: pos(850, 100),
          config: {
            operation: "write",
            path: "workspace/post.md",
            content: "{{input}}",
          },
        },
      ],
      edges: [
        { source: "trigger", target: "search" },
        { source: "search", target: "write" },
        { source: "write", target: "file" },
      ],
    }),
  },
  {
    id: "github-issue-agent",
    name: "GitHub Issue Agent",
    description: "Fetch GitHub issues and triage with AI.",
    build: () => ({
      id: `wf_${Date.now()}`,
      name: "GitHub Issue Agent",
      version: 1,
      nodes: [
        { id: "trigger", type: "manual", position: pos(100, 100), config: {} },
        {
          id: "issues",
          type: "github",
          position: pos(350, 100),
          config: { route: "/repos/{{input.owner}}/{{input.repo}}/issues" },
        },
        {
          id: "triage",
          type: "ai-classifier",
          position: pos(600, 100),
          config: { routes: ["bug", "feature", "question"] },
        },
      ],
      edges: [
        { source: "trigger", target: "issues" },
        { source: "issues", target: "triage" },
      ],
    }),
  },
];

export function getTemplate(id: string): WorkflowTemplate | undefined {
  return TEMPLATES.find((t) => t.id === id);
}

export function listTemplates(): Array<{
  id: string;
  name: string;
  description: string;
}> {
  return TEMPLATES.map((t) => ({
    id: t.id,
    name: t.name,
    description: t.description,
  }));
}

/** Minimal NL → workflow generator (rule-based; LLM upgrade path documented). */
export function generateWorkflowFromPrompt(prompt: string): WorkflowDefinition {
  const p = prompt.toLowerCase();
  const id = `wf_${Date.now()}`;
  const has = (...words: string[]) => words.some((w) => p.includes(w));
  const nodes: WorkflowDefinition["nodes"] = [];
  const edges: WorkflowDefinition["edges"] = [];
  let x = 100;
  const add = (
    nid: string,
    type: string,
    config: Record<string, unknown> = {},
  ) => {
    nodes.push({ id: nid, type, position: pos(x, 100), config });
    x += 250;
    if (nodes.length > 1) {
      edges.push({
        source: nodes[nodes.length - 2]?.id as string,
        target: nid,
      });
    }
  };
  add(
    has("webhook")
      ? "webhook"
      : has("hour", "daily", "morning", "every", "schedule", "cron")
        ? "schedule"
        : "trigger",
    has("webhook")
      ? "webhook"
      : has("hour", "daily", "morning", "every", "schedule", "cron")
        ? "schedule"
        : "manual",
    {},
  );
  if (has("search", "research", "news", "monitor", "competitor", "seo")) {
    add("search", "web-search", { query: prompt.slice(0, 140) });
  }
  if (has("summar", "digest", "tldr")) add("summarize", "ai-summarizer", {});
  if (has("writ", "post", "linkedin", "blog", "content", "draft"))
    add("write", "ai-writer", {});
  if (has("extract", "scrape", "parse")) add("extract", "ai-extractor", {});
  if (has("browser", "click", "website", "page"))
    add("browser", "browser", {
      action: "extract",
      url: "https://example.com",
    });
  if (has("email", "mail"))
    add("email", "email", { to: "", subject: "OpenAgent automation" });
  if (has("slack")) add("notify", "slack", { text: "{{input}}" });
  if (has("github", "issue", "pr", "code review"))
    add("github", "github", { route: "/repos/{owner}/{repo}/issues" });
  const lastIsFile = nodes[nodes.length - 1]?.type === "file";
  if (
    !lastIsFile &&
    has("save", "file", "write", "store", "report", "digest", "post")
  ) {
    add("file", "file", {
      operation: "write",
      path: "workspace/output.md",
      content: "{{input}}",
    });
  }
  if (nodes.length === 1) {
    add("agent", "ai-agent", { goal: prompt.slice(0, 300) });
  }
  return {
    id,
    name: prompt.slice(0, 60) || "Generated workflow",
    version: 1,
    description: `Generated from: ${prompt}`,
    nodes,
    edges,
  };
}
