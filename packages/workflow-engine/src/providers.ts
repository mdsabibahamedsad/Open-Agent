// Model provider abstraction: Ollama / OpenAI-compatible / Gemini / Anthropic.
export interface ChatMessage {
  role: "system" | "user" | "assistant" | "tool";
  content: string;
  name?: string;
}

export interface ChatOptions {
  model: string;
  messages: ChatMessage[];
  temperature?: number;
  maxTokens?: number;
  tools?: Array<{
    name: string;
    description: string;
    parameters?: Record<string, unknown>;
  }>;
  signal?: AbortSignal;
  baseUrl?: string;
  apiKey?: string;
}

export interface ChatResult {
  content: string;
  toolCalls?: Array<{ name: string; arguments: unknown }>;
  provider: string;
  model: string;
  fallback?: boolean;
}

function timeoutSignal(ms: number, parent?: AbortSignal): AbortSignal {
  const c = new AbortController();
  const t = setTimeout(() => c.abort(new Error("model request timed out")), ms);
  if (parent) {
    parent.addEventListener("abort", () => {
      clearTimeout(t);
      c.abort(parent.reason);
    });
  }
  return c.signal;
}

async function postJson(
  url: string,
  body: unknown,
  headers: Record<string, string>,
  signal?: AbortSignal,
): Promise<unknown> {
  const res = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json", ...headers },
    body: JSON.stringify(body),
    signal: signal ?? timeoutSignal(60000),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`provider HTTP ${res.status}: ${text.slice(0, 500)}`);
  }
  return res.json() as Promise<unknown>;
}

function isConnectionError(e: unknown): boolean {
  const msg = (
    e instanceof Error
      ? `${e.message} ${(e as { cause?: unknown }).cause ?? ""}`
      : String(e)
  ).toLowerCase();
  return (
    msg.includes("fetch failed") ||
    msg.includes("econnrefused") ||
    msg.includes("enotfound") ||
    msg.includes("etimedout") ||
    msg.includes("eai_again") ||
    msg.includes("timed out") ||
    msg.includes("timeout") ||
    msg.includes("network")
  );
}

export async function chatWithProvider(opts: ChatOptions): Promise<ChatResult> {
  const model = opts.model.trim();
  const { provider, name } = splitModel(model);
  try {
    switch (provider) {
      case "ollama":
        return await chatOllama({ ...opts, model: name });
      case "openai":
        return await chatOpenAICompatible({ ...opts, model: name });
      case "gemini":
        return await chatGemini({ ...opts, model: name });
      case "anthropic":
        return await chatAnthropic({ ...opts, model: name });
      case "echo":
        return {
          content: heuristicAnswer(opts.messages, name),
          provider: "echo",
          model: name,
          fallback: true,
        };
      default:
        // Bare model name: try Ollama, then OpenAI-compatible env, else heuristic.
        if (process.env.OPENAI_API_KEY) {
          try {
            return await chatOpenAICompatible({ ...opts, model });
          } catch {
            // fall through
          }
        }
        try {
          return await chatOllama({ ...opts, model });
        } catch {
          return {
            content: heuristicAnswer(opts.messages, model),
            provider: "heuristic",
            model,
            fallback: true,
          };
        }
    }
  } catch (e) {
    // Local-first: when the configured provider is unreachable (no Ollama
    // running, no network), degrade to a clearly-labeled extractive fallback
    // so pipelines keep working. Config errors (missing keys, 401s) still throw.
    if (isConnectionError(e)) {
      return {
        content: heuristicAnswer(opts.messages, `${provider}:${name}`),
        provider: "heuristic",
        model: `${provider}:${name}`,
        fallback: true,
      };
    }
    throw e;
  }
}

export function splitModel(model: string): { provider: string; name: string } {
  const i = model.indexOf(":");
  if (i <= 0) return { provider: "auto", name: model };
  return {
    provider: model.slice(0, i).toLowerCase(),
    name: model.slice(i + 1),
  };
}

async function chatOllama(opts: ChatOptions): Promise<ChatResult> {
  const base =
    opts.baseUrl ?? process.env.OLLAMA_HOST ?? "http://127.0.0.1:11434";
  const body = {
    model: opts.model,
    messages: opts.messages.map((m) => ({ role: m.role, content: m.content })),
    stream: false,
    options: {
      temperature: opts.temperature ?? 0.2,
      num_predict: opts.maxTokens ?? 1024,
    },
  };
  const json = (await postJson(
    `${base.replace(/\/$/, "")}/api/chat`,
    body,
    {},
    opts.signal,
  )) as { message?: { content?: string } };
  const content = json.message?.content ?? "";
  if (!content) throw new Error("empty response from Ollama");
  return { content, provider: "ollama", model: opts.model };
}

async function chatOpenAICompatible(opts: ChatOptions): Promise<ChatResult> {
  const base =
    opts.baseUrl ?? process.env.OPENAI_BASE_URL ?? "https://api.openai.com/v1";
  const key = opts.apiKey ?? process.env.OPENAI_API_KEY;
  if (!key) throw new Error("OPENAI_API_KEY is not set");
  const tools = opts.tools?.map((t) => ({
    type: "function",
    function: {
      name: t.name,
      description: t.description,
      parameters: t.parameters ?? { type: "object", properties: {} },
    },
  }));
  const json = (await postJson(
    `${base.replace(/\/$/, "")}/chat/completions`,
    {
      model: opts.model,
      messages: opts.messages,
      temperature: opts.temperature ?? 0.2,
      max_tokens: opts.maxTokens ?? 1024,
      tools: tools?.length ? tools : undefined,
    },
    { authorization: `Bearer ${key}` },
    opts.signal,
  )) as {
    choices?: Array<{
      message?: {
        content?: string;
        tool_calls?: Array<{
          function?: { name?: string; arguments?: string };
        }>;
      };
    }>;
  };
  const msg = json.choices?.[0]?.message;
  return {
    content: msg?.content ?? "",
    toolCalls: (msg?.tool_calls ?? [])
      .map((c) => ({
        name: c.function?.name ?? "",
        arguments: safeJsonParse(c.function?.arguments ?? "{}"),
      }))
      .filter((c) => c.name),
    provider: "openai",
    model: opts.model,
  };
}

async function chatGemini(opts: ChatOptions): Promise<ChatResult> {
  const key =
    opts.apiKey ?? process.env.GEMINI_API_KEY ?? process.env.GOOGLE_API_KEY;
  if (!key) throw new Error("GEMINI_API_KEY is not set");
  const prompt = opts.messages
    .map((m) => `${m.role.toUpperCase()}: ${m.content}`)
    .join("\n\n");
  const url = `https://generativelanguage.googleapis.com/v1beta/models/${encodeURIComponent(opts.model || "gemini-1.5-flash")}:generateContent?key=${encodeURIComponent(key)}`;
  const json = (await postJson(
    url,
    { contents: [{ parts: [{ text: prompt }] }] },
    {},
    opts.signal,
  )) as {
    candidates?: Array<{ content?: { parts?: Array<{ text?: string }> } }>;
  };
  const content =
    json.candidates?.[0]?.content?.parts?.map((p) => p.text ?? "").join("") ??
    "";
  if (!content) throw new Error("empty response from Gemini");
  return { content, provider: "gemini", model: opts.model };
}

async function chatAnthropic(opts: ChatOptions): Promise<ChatResult> {
  const key = opts.apiKey ?? process.env.ANTHROPIC_API_KEY;
  if (!key) throw new Error("ANTHROPIC_API_KEY is not set");
  const system = opts.messages
    .filter((m) => m.role === "system")
    .map((m) => m.content)
    .join("\n");
  const rest = opts.messages
    .filter((m) => m.role !== "system")
    .map((m) => ({
      role: m.role === "tool" ? "user" : m.role,
      content: m.content,
    }));
  const json = (await postJson(
    "https://api.anthropic.com/v1/messages",
    {
      model: opts.model || "claude-3-5-sonnet-latest",
      max_tokens: opts.maxTokens ?? 1024,
      system: system || undefined,
      messages: rest,
    },
    { "x-api-key": key, "anthropic-version": "2023-06-01" },
    opts.signal,
  )) as { content?: Array<{ text?: string }> };
  const content = (json.content ?? []).map((c) => c.text ?? "").join("");
  if (!content) throw new Error("empty response from Anthropic");
  return { content, provider: "anthropic", model: opts.model };
}

function safeJsonParse(s: string): unknown {
  try {
    return JSON.parse(s);
  } catch {
    return s;
  }
}

/** Deterministic extractive fallback — clearly marked, never pretends to be an LLM. */
function heuristicAnswer(messages: ChatMessage[], model: string): string {
  const last = [...messages].reverse().find((m) => m.role === "user");
  const text = last?.content ?? "";
  const sentences = text
    .split(/(?<=[.!?])\s+/)
    .filter(Boolean)
    .slice(0, 5);
  return [
    `[heuristic fallback — no model '${model}' reachable]`,
    ``,
    sentences.length > 0 ? sentences.join(" ") : "(no input provided)",
  ].join("\n");
}

export async function checkOllama(baseUrl?: string): Promise<{
  ok: boolean;
  models: string[];
  detail: string;
}> {
  const base = baseUrl ?? process.env.OLLAMA_HOST ?? "http://127.0.0.1:11434";
  try {
    const res = await fetch(`${base.replace(/\/$/, "")}/api/tags`, {
      signal: timeoutSignal(8000),
    });
    if (!res.ok) return { ok: false, models: [], detail: `HTTP ${res.status}` };
    const json = (await res.json()) as { models?: Array<{ name?: string }> };
    return {
      ok: true,
      models: (json.models ?? []).map((m) => m.name ?? "").filter(Boolean),
      detail: `reachable at ${base}`,
    };
  } catch (e) {
    return {
      ok: false,
      models: [],
      detail: e instanceof Error ? e.message : String(e),
    };
  }
}

export async function embedText(
  text: string,
  opts?: { provider?: string; model?: string },
): Promise<number[]> {
  // Try Ollama embeddings, then OpenAI, else deterministic hash embedding (for local semantic memory).
  const provider = opts?.provider ?? "auto";
  if (provider === "auto" || provider === "ollama") {
    try {
      const base = process.env.OLLAMA_HOST ?? "http://127.0.0.1:11434";
      const json = (await postJson(
        `${base.replace(/\/$/, "")}/api/embeddings`,
        { model: opts?.model ?? "nomic-embed-text", prompt: text },
        {},
      )) as { embedding?: number[] };
      if (Array.isArray(json.embedding) && json.embedding.length > 0)
        return json.embedding;
    } catch {
      // fall through to hash embedding
    }
  }
  if (
    (provider === "auto" || provider === "openai") &&
    process.env.OPENAI_API_KEY
  ) {
    try {
      const json = (await postJson(
        `${(process.env.OPENAI_BASE_URL ?? "https://api.openai.com/v1").replace(/\/$/, "")}/embeddings`,
        { model: opts?.model ?? "text-embedding-3-small", input: text },
        { authorization: `Bearer ${process.env.OPENAI_API_KEY}` },
      )) as { data?: Array<{ embedding?: number[] }> };
      const emb = json.data?.[0]?.embedding;
      if (Array.isArray(emb) && emb.length > 0) return emb;
    } catch {
      // fall through
    }
  }
  return hashEmbedding(text);
}

/** Stable 64-dim hashed embedding for offline semantic memory. */
export function hashEmbedding(text: string, dim = 64): number[] {
  const vec = new Array<number>(dim).fill(0);
  const tokens = text
    .toLowerCase()
    .split(/[^a-z0-9]+/)
    .filter(Boolean);
  for (const tok of tokens) {
    let h = 2166136261;
    for (let i = 0; i < tok.length; i++) {
      h ^= tok.charCodeAt(i);
      h = Math.imul(h, 16777619);
    }
    vec[Math.abs(h) % dim] += 1;
  }
  const norm = Math.sqrt(vec.reduce((a, b) => a + b * b, 0)) || 1;
  return vec.map((v) => v / norm);
}
