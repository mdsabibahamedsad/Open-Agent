import pc from "picocolors";

export class OpenAgentError extends Error {
  code: string;
  status?: number;
  requestId?: string;
  details?: unknown;
  exitCode: number;
  constructor(message: string, opts?: { code?: string; status?: number; requestId?: string; details?: unknown; exitCode?: number }) {
    super(message);
    this.name = "OpenAgentError";
    this.code = opts?.code ?? "UNKNOWN";
    this.status = opts?.status;
    this.requestId = opts?.requestId;
    this.details = opts?.details;
    this.exitCode = opts?.exitCode ?? 1;
  }
}

export class AuthenticationError extends OpenAgentError {
  constructor(message: string, extra?: { requestId?: string; status?: number }) {
    super(message, { code: "AUTHENTICATION_ERROR", status: extra?.status ?? 401, requestId: extra?.requestId, exitCode: 3 });
    this.name = "AuthenticationError";
  }
}

export class AuthorizationError extends OpenAgentError {
  constructor(message: string, extra?: { requestId?: string; status?: number }) {
    super(message, { code: "AUTHORIZATION_ERROR", status: extra?.status ?? 403, requestId: extra?.requestId, exitCode: 3 });
    this.name = "AuthorizationError";
  }
}

export class NotFoundError extends OpenAgentError {
  constructor(message: string, extra?: { requestId?: string }) {
    super(message, { code: "NOT_FOUND", status: 404, requestId: extra?.requestId, exitCode: 1 });
    this.name = "NotFoundError";
  }
}

export class ValidationError extends OpenAgentError {
  constructor(message: string, details?: unknown, extra?: { requestId?: string }) {
    super(message, { code: "VALIDATION_ERROR", status: 422, requestId: extra?.requestId, details, exitCode: 2 });
    this.name = "ValidationError";
  }
}

export class RateLimitError extends OpenAgentError {
  retryAfterMs?: number;
  constructor(message: string, retryAfterMs?: number, extra?: { requestId?: string }) {
    super(message, { code: "RATE_LIMITED", status: 429, requestId: extra?.requestId, exitCode: 1 });
    this.name = "RateLimitError";
    this.retryAfterMs = retryAfterMs;
  }
}

export class NetworkError extends OpenAgentError {
  constructor(message: string, extra?: { requestId?: string }) {
    super(message, { code: "NETWORK_ERROR", requestId: extra?.requestId, exitCode: 4 });
    this.name = "NetworkError";
  }
}

export class ServerError extends OpenAgentError {
  constructor(message: string, status: number, extra?: { requestId?: string; details?: unknown }) {
    super(message, { code: "SERVER_ERROR", status, requestId: extra?.requestId, details: extra?.details, exitCode: 1 });
    this.name = "ServerError";
  }
}

export function toExitCode(err: unknown): number {
  if (err instanceof OpenAgentError) return err.exitCode;
  return 1;
}

export interface ClientOptions {
  baseUrl: string;
  apiKey?: string;
  orgId?: string;
  timeoutMs?: number;
  maxRetries?: number;
  verbose?: boolean;
}

export interface RequestOptions {
  method?: string;
  body?: unknown;
  query?: Record<string, string | number | boolean | undefined>;
  headers?: Record<string, string>;
  idempotencyKey?: string;
  timeoutMs?: number;
  retry?: boolean;
}

function newRequestId(): string {
  const c = globalThis.crypto as unknown as { randomUUID?: () => string } | undefined;
  if (c && typeof c.randomUUID === "function") return c.randomUUID();
  return `req_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 10)}`;
}

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

export function newIdempotencyKey(): string {
  return newRequestId();
}

export class ApiClient {
  baseUrl: string;
  apiKey?: string;
  orgId?: string;
  timeoutMs: number;
  maxRetries: number;
  verbose: boolean;

  constructor(opts: ClientOptions) {
    this.baseUrl = opts.baseUrl.replace(/\/+$/, "");
    this.apiKey = opts.apiKey;
    this.orgId = opts.orgId;
    this.timeoutMs = opts.timeoutMs ?? 30_000;
    this.maxRetries = opts.maxRetries ?? 3;
    this.verbose = opts.verbose ?? false;
  }

  orgPath(suffix: string): string {
    if (!this.orgId) throw new AuthenticationError("Organization ID is required. Use --org, OPENAGENT_ORG_ID, or `openagent config set orgId <id>`.");
    return `/api/v1/organizations/${encodeURIComponent(this.orgId)}${suffix}`;
  }

  buildUrl(path: string, query?: RequestOptions["query"]): string {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(query ?? {})) {
      if (v !== undefined) qs.set(k, String(v));
    }
    const s = qs.toString();
    return `${this.baseUrl}${path}${s ? `?${s}` : ""}`;
  }

  async request<T = unknown>(path: string, opts: RequestOptions = {}): Promise<T> {
    const method = (opts.method ?? "GET").toUpperCase();
    const url = this.buildUrl(path, opts.query);
    const requestId = newRequestId();
    const idempotencyKey = opts.idempotencyKey ?? (["POST", "PUT", "PATCH", "DELETE"].includes(method) ? undefined : undefined);
    const retryableMethod = method === "GET" || method === "HEAD" || !!opts.idempotencyKey || !!idempotencyKey;
    const allowRetry = opts.retry ?? retryableMethod;
    const maxAttempts = allowRetry ? this.maxRetries + 1 : 1;

    let lastErr: unknown;
    for (let attempt = 1; attempt <= maxAttempts; attempt++) {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), opts.timeoutMs ?? this.timeoutMs);
      try {
        if (this.verbose) {
          process.stderr.write(pc.gray(`→ ${method} ${url} [${requestId} attempt ${attempt}]`) + "\n");
        }
        const res = await fetch(url, {
          method,
          signal: controller.signal,
          headers: {
            "Content-Type": "application/json",
            Accept: "application/json",
            "X-Request-ID": requestId,
            ...(this.apiKey ? { Authorization: `Bearer ${this.apiKey}` } : {}),
            ...(this.orgId ? { "X-Organization-ID": this.orgId } : {}),
            ...(opts.idempotencyKey ? { "Idempotency-Key": opts.idempotencyKey } : {}),
            ...(idempotencyKey ? { "Idempotency-Key": idempotencyKey } : {}),
            ...opts.headers,
          },
          body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
        });
        if (this.verbose) {
          process.stderr.write(pc.gray(`← ${res.status} ${method} ${url} [${requestId}]`) + "\n");
        }
        if (res.status === 429) {
          const retryAfter = res.headers.get("retry-after");
          const waitMs = retryAfter ? Number(retryAfter) * 1000 : 1000 * attempt;
          const bodyText = await res.text().catch(() => "");
          if (attempt < maxAttempts) {
            await sleep(Number.isFinite(waitMs) ? Math.min(waitMs, 30_000) : 1000 * attempt);
            lastErr = new RateLimitError(`Rate limited by server (429).${retryAfter ? ` Retry-After: ${retryAfter}s.` : ""}`, Number.isFinite(waitMs) ? waitMs : undefined, { requestId });
            continue;
          }
          throw new RateLimitError(`Rate limited by server (429): ${bodyText.slice(0, 500)}`, Number.isFinite(waitMs) ? waitMs : undefined, { requestId });
        }
        if (res.status === 401) {
          const t = await res.text().catch(() => "");
          throw new AuthenticationError(`Authentication failed (401). Check your API key and profile. ${t.slice(0, 300)}`, { requestId, status: 401 });
        }
        if (res.status === 403) {
          const t = await res.text().catch(() => "");
          throw new AuthorizationError(`Forbidden (403). ${t.slice(0, 300)}`, { requestId, status: 403 });
        }
        if (res.status === 404) {
          const t = await res.text().catch(() => "");
          throw new NotFoundError(`Not found (404): ${path}. ${t.slice(0, 300)}`);
        }
        if (res.status === 422) {
          const t = await res.text().catch(() => "");
          throw new ValidationError(`Validation failed (422): ${t.slice(0, 1000)}`, t, { requestId });
        }
        if (res.status >= 500) {
          const t = await res.text().catch(() => "");
          if (attempt < maxAttempts && (method === "GET" || method === "HEAD")) {
            await sleep(250 * 2 ** (attempt - 1));
            lastErr = new ServerError(`Server error (${res.status}): ${t.slice(0, 500)}`, res.status, { requestId });
            continue;
          }
          throw new ServerError(`Server error (${res.status}): ${t.slice(0, 1000)}`, res.status, { requestId, details: t.slice(0, 2000) });
        }
        if (!res.ok) {
          const t = await res.text().catch(() => "");
          throw new OpenAgentError(`Request failed (${res.status}): ${t.slice(0, 1000) || res.statusText}`, { code: "HTTP_ERROR", status: res.status, requestId, details: t.slice(0, 2000), exitCode: 1 });
        }
        const text = await res.text();
        if (text.trim() === "") return undefined as T;
        try {
          return JSON.parse(text) as T;
        } catch {
          return text as unknown as T;
        }
      } catch (err) {
        if (err instanceof OpenAgentError) throw err;
        const msg = err instanceof Error ? err.message : String(err);
        const isAbort = /abort/i.test(msg);
        lastErr = new NetworkError(`${isAbort ? "Request timed out" : "Network error"}: ${msg} [${requestId}]`, { requestId });
        if (attempt < maxAttempts && retryableMethod) {
          await sleep(250 * 2 ** (attempt - 1));
          continue;
        }
        throw lastErr;
      } finally {
        clearTimeout(timeout);
      }
    }
    throw lastErr instanceof OpenAgentError ? lastErr : new NetworkError("Request failed after retries");
  }

  get<T = unknown>(path: string, query?: RequestOptions["query"], opts?: Omit<RequestOptions, "method" | "query">): Promise<T> {
    return this.request<T>(path, { ...opts, method: "GET", query });
  }
  post<T = unknown>(path: string, body?: unknown, opts?: Omit<RequestOptions, "method" | "body">): Promise<T> {
    return this.request<T>(path, { ...opts, method: "POST", body });
  }
  put<T = unknown>(path: string, body?: unknown, opts?: Omit<RequestOptions, "method" | "body">): Promise<T> {
    return this.request<T>(path, { ...opts, method: "PUT", body });
  }
  patch<T = unknown>(path: string, body?: unknown, opts?: Omit<RequestOptions, "method" | "body">): Promise<T> {
    return this.request<T>(path, { ...opts, method: "PATCH", body });
  }
  delete<T = unknown>(path: string, opts?: Omit<RequestOptions, "method">): Promise<T> {
    return this.request<T>(path, { ...opts, method: "DELETE" });
  }

  /** Follow page/page_size or cursor pagination. Returns concatenated items. */
  async paginate<T = unknown>(path: string, opts?: { params?: Record<string, string | number | boolean | undefined>; limit?: number }): Promise<T[]> {
    const items: T[] = [];
    const limit = opts?.limit ?? 200;
    let page = 1;
    let cursor: string | undefined;
    for (;;) {
      const query: Record<string, string | number | boolean | undefined> = { ...(opts?.params ?? {}) };
      if (cursor) {
        query.cursor = cursor;
      } else {
        query.page = page;
        if (query.page_size === undefined) query.page_size = 50;
      }
      const res = await this.get<unknown>(path, query);
      const { batch, nextCursor, totalPages } = extractPage<T>(res);
      items.push(...batch);
      if (items.length >= limit) return items.slice(0, limit);
      if (nextCursor) {
        cursor = nextCursor;
        if (!nextCursor) break;
      } else {
        if (totalPages !== undefined) {
          if (page >= totalPages) break;
          page += 1;
        } else {
          if (batch.length === 0) break;
          // If server does not paginate, stop after first page.
          if (!isPaginatedResponse(res)) break;
          page += 1;
        }
      }
      if (page > 100) break;
    }
    return items;
  }
}

function isPaginatedResponse(res: unknown): boolean {
  if (res && typeof res === "object") {
    const o = res as Record<string, unknown>;
    return "items" in o || "results" in o || "data" in o;
  }
  return false;
}

function extractPage<T>(res: unknown): { batch: T[]; nextCursor?: string; totalPages?: number } {
  if (Array.isArray(res)) return { batch: res as T[] };
  if (res && typeof res === "object") {
    const o = res as Record<string, unknown>;
    const arr = (o.items ?? o.results ?? o.data ?? o.extensions ?? o.projects) as unknown;
    const batch = Array.isArray(arr) ? (arr as T[]) : [];
    const nextCursor =
      (o.next_cursor as string | undefined) ??
      (o.nextCursor as string | undefined) ??
      (o.cursor as string | undefined) ??
      undefined;
    const totalPages = (o.total_pages as number | undefined) ?? (o.totalPages as number | undefined);
    // If payload is a single object (not a list envelope), treat as one batch item only when caller expects raw.
    if (batch.length === 0 && !("items" in o) && !("results" in o) && !("data" in o)) {
      return { batch: [], nextCursor: undefined };
    }
    return { batch, nextCursor, totalPages };
  }
  return { batch: [] };
}

export interface OutputOptions {
  json?: boolean;
  quiet?: boolean;
  verbose?: boolean;
  noColor?: boolean;
}

export function printResult(data: unknown, opts: OutputOptions = {}): void {
  if (opts.quiet) return;
  if (opts.json) {
    process.stdout.write(JSON.stringify(data, null, 2) + "\n");
    return;
  }
  if (typeof data === "string") {
    process.stdout.write(data + (data.endsWith("\n") ? "" : "\n"));
    return;
  }
  process.stdout.write(JSON.stringify(data, null, 2) + "\n");
}

export function printSuccess(message: string, opts: OutputOptions = {}): void {
  if (opts.quiet) return;
  if (opts.json) {
    process.stdout.write(JSON.stringify({ ok: true, message }) + "\n");
    return;
  }
  const useColor = !opts.noColor && !process.env.NO_COLOR;
  process.stdout.write((useColor ? pc.green("✓ ") : "ok: ") + message + "\n");
}

export function printErrorLine(message: string, opts: OutputOptions = {}): void {
  const useColor = !opts.noColor && !process.env.NO_COLOR;
  process.stderr.write((useColor ? pc.red("✖ ") : "error: ") + message + "\n");
}
