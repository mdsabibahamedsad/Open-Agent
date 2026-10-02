// @openagent/api-client — stable REST client abstraction (§8).
// API versioning, request IDs, auth, safe retries, timeouts, idempotency,
// pagination, streaming, webhook verification, structured errors,
// rate-limit handling, backward compatibility. Never silently retries
// unsafe non-idempotent operations.

import type { Paginated } from '@openagent/sdk-types';

export const API_CLIENT_VERSION = '1.0.0';
export const DEFAULT_API_VERSION = 'v1';

export type ErrorCode =
  | 'AUTHENTICATION_ERROR' | 'AUTHORIZATION_ERROR' | 'VALIDATION_ERROR'
  | 'NOT_FOUND' | 'CONFLICT' | 'RATE_LIMITED' | 'TIMEOUT'
  | 'POLICY_DENIED' | 'APPROVAL_REQUIRED' | 'COMPATIBILITY_ERROR'
  | 'EXTENSION_ERROR' | 'TOOL_EXECUTION_ERROR' | 'CONNECTOR_ERROR'
  | 'MCP_ERROR' | 'SANDBOX_ERROR' | 'DEPLOYMENT_ERROR' | 'SERVER_ERROR'
  | 'NETWORK_ERROR' | 'UNKNOWN_ERROR';

export class OpenAgentApiError extends Error {
  code: ErrorCode;
  status: number;
  requestId: string;
  retryAfterSeconds?: number;
  rateLimit?: { limit?: number; remaining?: number; reset?: number };
  constructor(message: string, opts: {
    code?: ErrorCode; status?: number; requestId?: string;
    retryAfterSeconds?: number; rateLimit?: OpenAgentApiError['rateLimit'];
  } = {}) {
    super(message);
    this.name = 'OpenAgentApiError';
    this.code = opts.code ?? 'UNKNOWN_ERROR';
    this.status = opts.status ?? 0;
    this.requestId = opts.requestId ?? '';
    this.retryAfterSeconds = opts.retryAfterSeconds;
    this.rateLimit = opts.rateLimit;
  }
}

export const AuthenticationError = (m: string, o = {}) =>
  new OpenAgentApiError(m, { ...o, code: 'AUTHENTICATION_ERROR', status: 401 });
export const AuthorizationError = (m: string, o = {}) =>
  new OpenAgentApiError(m, { ...o, code: 'AUTHORIZATION_ERROR', status: 403 });

export interface ApiClientConfig {
  baseUrl: string; // e.g. https://api.example.com (no trailing slash)
  apiKey?: string;
  organizationId?: string;
  apiVersion?: string; // default 'v1'
  timeoutMs?: number; // default 30_000
  maxRetries?: number; // default 3 (safe methods / idempotent writes only)
  retryBaseMs?: number; // default 250
  userAgent?: string;
  fetchImpl?: typeof fetch;
}

export interface RequestOptions {
  method?: string;
  body?: unknown;
  query?: Record<string, string | number | boolean | undefined>;
  headers?: Record<string, string>;
  idempotencyKey?: string;
  requestId?: string;
  timeoutMs?: number;
  signal?: AbortSignal;
  retry?: boolean; // default true for safe requests
}

function newRequestId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID();
  return `req_${Date.now().toString(36)}_${Math.floor(Math.random() * 1e9).toString(36)}`;
}

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

function parseErrorPayload(payload: unknown): { code: ErrorCode; message: string } {
  if (payload && typeof payload === 'object') {
    const err = (payload as Record<string, unknown>).error;
    if (err && typeof err === 'object') {
      const e = err as Record<string, unknown>;
      return {
        code: (typeof e.code === 'string' ? e.code : 'UNKNOWN_ERROR') as ErrorCode,
        message: typeof e.message === 'string' ? e.message : 'Request failed',
      };
    }
    const detail = (payload as Record<string, unknown>).detail;
    if (typeof detail === 'string') return { code: 'VALIDATION_ERROR', message: detail };
  }
  return { code: 'UNKNOWN_ERROR', message: 'Request failed' };
}

export class ApiClient {
  readonly config: Required<Omit<ApiClientConfig, 'apiKey' | 'organizationId' | 'fetchImpl'>> &
    Pick<ApiClientConfig, 'apiKey' | 'organizationId' | 'fetchImpl'>;

  constructor(config: ApiClientConfig) {
    if (!config.baseUrl) throw new Error('ApiClient requires baseUrl');
    this.config = {
      baseUrl: config.baseUrl.replace(/\/+$/, ''),
      apiVersion: config.apiVersion ?? DEFAULT_API_VERSION,
      timeoutMs: config.timeoutMs ?? 30_000,
      maxRetries: config.maxRetries ?? 3,
      retryBaseMs: config.retryBaseMs ?? 250,
      userAgent: config.userAgent ?? `openagent-api-client/${API_CLIENT_VERSION}`,
      apiKey: config.apiKey,
      organizationId: config.organizationId,
      fetchImpl: config.fetchImpl,
    };
  }

  private fetchFn(): typeof fetch {
    if (this.config.fetchImpl) return this.config.fetchImpl;
    if (typeof fetch === 'undefined') throw new Error('fetch is not available in this runtime');
    return fetch.bind(globalThis);
  }

  apiPath(path: string): string {
    if (path.startsWith('/api/')) return path;
    return `/api/${this.config.apiVersion}${path.startsWith('/') ? path : `/${path}`}`;
  }

  async request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
    const method = (opts.method ?? 'GET').toUpperCase();
    const requestId = opts.requestId ?? newRequestId();
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(opts.query ?? {})) {
      if (v !== undefined) qs.set(k, String(v));
    }
    const url = `${this.config.baseUrl}${this.apiPath(path)}${qs.size ? `?${qs}` : ''}`;
    const safe = method === 'GET' || method === 'HEAD' || Boolean(opts.idempotencyKey);
    const attempts = opts.retry === false ? 1 : (safe ? this.config.maxRetries + 1 : 1);

    let lastError: unknown = null;
    for (let attempt = 0; attempt < attempts; attempt++) {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), opts.timeoutMs ?? this.config.timeoutMs);
      const onAbort = () => controller.abort();
      opts.signal?.addEventListener('abort', onAbort, { once: true });
      try {
        const res = await this.fetchFn()(url, {
          method,
          signal: opts.signal ?? controller.signal,
          headers: {
            'Content-Type': 'application/json',
            Accept: 'application/json',
            'User-Agent': this.config.userAgent,
            'X-Request-ID': requestId,
            ...(this.config.apiKey ? { Authorization: `Bearer ${this.config.apiKey}` } : {}),
            ...(this.config.organizationId ? { 'X-Organization-ID': this.config.organizationId } : {}),
            ...(opts.idempotencyKey ? { 'Idempotency-Key': opts.idempotencyKey } : {}),
            ...opts.headers,
          },
          body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
        });
        if (res.status === 429 || (res.status >= 500 && res.status < 600)) {
          if (attempt + 1 < attempts) {
            const retryAfter = Number(res.headers.get('Retry-After') ?? 0);
            await sleep(
              Number.isFinite(retryAfter) && retryAfter > 0
                ? retryAfter * 1000
                : this.config.retryBaseMs * 2 ** attempt,
            );
            continue;
          }
        }
        if (!res.ok) {
          let payload: unknown = null;
          try { payload = await res.json(); } catch { /* text error */ }
          const parsed = parseErrorPayload(payload);
          const code: ErrorCode =
            res.status === 401 ? 'AUTHENTICATION_ERROR'
            : res.status === 403 ? 'AUTHORIZATION_ERROR'
            : res.status === 404 ? 'NOT_FOUND'
            : res.status === 409 ? 'CONFLICT'
            : res.status === 429 ? 'RATE_LIMITED'
            : res.status === 408 ? 'TIMEOUT'
            : parsed.code;
          throw new OpenAgentApiError(parsed.message, {
            code, status: res.status, requestId,
            retryAfterSeconds: res.status === 429 ? Number(res.headers.get('Retry-After') ?? 0) || undefined : undefined,
            rateLimit: {
              limit: Number(res.headers.get('X-RateLimit-Limit') ?? 0) || undefined,
              remaining: Number(res.headers.get('X-RateLimit-Remaining') ?? 0) || undefined,
              reset: Number(res.headers.get('X-RateLimit-Reset') ?? 0) || undefined,
            },
          });
        }
        if (res.status === 204) return undefined as T;
        return (await res.json()) as T;
      } catch (err) {
        lastError = err;
        if (err instanceof OpenAgentApiError) throw err;
        if (attempt + 1 >= attempts) {
          throw new OpenAgentApiError(
            err instanceof Error && err.name === 'AbortError' ? 'Request timed out' : 'Network error',
            { code: err instanceof Error && err.name === 'AbortError' ? 'TIMEOUT' : 'NETWORK_ERROR', requestId },
          );
        }
        await sleep(this.config.retryBaseMs * 2 ** attempt);
      } finally {
        clearTimeout(timeout);
        opts.signal?.removeEventListener('abort', onAbort);
      }
    }
    throw lastError instanceof Error ? lastError : new Error('Request failed');
  }

  get<T>(path: string, opts?: RequestOptions): Promise<T> {
    return this.request<T>(path, { ...opts, method: 'GET' });
  }
  post<T>(path: string, body?: unknown, opts?: RequestOptions): Promise<T> {
    return this.request<T>(path, { ...opts, method: 'POST', body });
  }
  patch<T>(path: string, body?: unknown, opts?: RequestOptions): Promise<T> {
    return this.request<T>(path, { ...opts, method: 'PATCH', body });
  }
  put<T>(path: string, body?: unknown, opts?: RequestOptions): Promise<T> {
    return this.request<T>(path, { ...opts, method: 'PUT', body });
  }
  delete<T>(path: string, opts?: RequestOptions): Promise<T> {
    return this.request<T>(path, { ...opts, method: 'DELETE' });
  }

  /** Iterate all pages of a list endpoint returning {items, has_more,...} or plain arrays. */
  async *iterate<T>(path: string, opts?: RequestOptions & { pageSize?: number }): AsyncGenerator<T> {
    let page = 1;
    for (;;) {
      const res = await this.get<Paginated<T> | T[] | { items: T[] }>(path, {
        ...opts, query: { ...opts?.query, page, page_size: opts?.pageSize ?? 100 },
      });
      const items = Array.isArray(res) ? res : (res as { items?: T[] }).items ?? [];
      for (const item of items) yield item;
      if (Array.isArray(res) || !(res as Paginated<T>).has_more) return;
      if (items.length === 0) return;
      page += 1;
    }
  }

  /** Open an SSE/HTTP-stream GET and yield decoded events. */
  async *stream<T = unknown>(path: string, opts?: RequestOptions): AsyncGenerator<T> {
    const requestId = newRequestId();
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(opts?.query ?? {})) {
      if (v !== undefined) qs.set(k, String(v));
    }
    const url = `${this.config.baseUrl}${this.apiPath(path)}${qs.size ? `?${qs}` : ''}`;
    const res = await this.fetchFn()(url, {
      headers: {
        Accept: 'text/event-stream',
        'X-Request-ID': requestId,
        ...(this.config.apiKey ? { Authorization: `Bearer ${this.config.apiKey}` } : {}),
        ...(this.config.organizationId ? { 'X-Organization-ID': this.config.organizationId } : {}),
      },
      signal: opts?.signal,
    });
    if (!res.ok || !res.body) {
      throw new OpenAgentApiError(`Stream failed (${res.status})`, { status: res.status, requestId });
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const frames = buffer.split('\n\n');
      buffer = frames.pop() ?? '';
      for (const frame of frames) {
        const dataLine = frame.split('\n').find((l) => l.startsWith('data:'));
        if (!dataLine) continue;
        try { yield JSON.parse(dataLine.slice(5).trim()) as T; } catch { /* keep-alive */ }
      }
    }
  }
}

// --- webhook helpers (mirror backend algorithm) ----------------------------

export async function sha256Hex(data: Uint8Array | string): Promise<string> {
  const bytes = typeof data === 'string' ? new TextEncoder().encode(data) : data;
  const digest = await crypto.subtle.digest('SHA-256', bytes);
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, '0')).join('');
}

async function hmacHex(secret: string, message: string): Promise<string> {
  const key = await crypto.subtle.importKey(
    'raw', new TextEncoder().encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign'],
  );
  const sig = await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(message));
  return [...new Uint8Array(sig)].map((b) => b.toString(16).padStart(2, '0')).join('');
}

export async function signWebhook(secret: string, body: Uint8Array | string, opts: {
  deliveryId: string; timestamp?: number;
}): Promise<string> {
  const ts = opts.timestamp ?? Math.floor(Date.now() / 1000);
  const bodyHash = await sha256Hex(body);
  const digest = await hmacHex(secret, `v1.${ts}.${opts.deliveryId}.${bodyHash}`);
  return `v1,t=${ts},id=${opts.deliveryId},sig=${digest}`;
}

export async function verifyWebhook(secret: string, body: Uint8Array | string, header: string, opts: {
  now?: number; tolerance?: number;
} = {}): Promise<{ ok: boolean; reason: string; deliveryId: string }> {
  const parts: Record<string, string> = {};
  for (const chunk of header.split(',')) {
    const c = chunk.trim();
    if (c === 'v1') parts.v = c;
    else if (c.includes('=')) {
      const i = c.indexOf('=');
      parts[c.slice(0, i).trim()] = c.slice(i + 1).trim();
    }
  }
  if (parts.v !== 'v1' || !parts.sig || !parts.t) {
    return { ok: false, reason: 'malformed signature header', deliveryId: parts.id ?? '' };
  }
  const ts = Number(parts.t);
  const current = opts.now ?? Math.floor(Date.now() / 1000);
  if (!Number.isFinite(ts) || Math.abs(current - ts) > (opts.tolerance ?? 300)) {
    return { ok: false, reason: 'timestamp outside tolerance', deliveryId: parts.id ?? '' };
  }
  const expected = await signWebhook(secret, body, { deliveryId: parts.id ?? '', timestamp: ts });
  const a = new TextEncoder().encode(expected);
  const b = new TextEncoder().encode(header.trim());
  if (a.length !== b.length) return { ok: false, reason: 'signature mismatch', deliveryId: parts.id ?? '' };
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a[i] ^ b[i];
  if (diff !== 0) return { ok: false, reason: 'signature mismatch', deliveryId: parts.id ?? '' };
  return { ok: true, reason: '', deliveryId: parts.id ?? '' };
}

export function parseWebhook(body: string): Record<string, unknown> {
  let data: unknown;
  try { data = JSON.parse(body); } catch (err) {
    throw new OpenAgentApiError(`invalid webhook JSON: ${err}`, { code: 'VALIDATION_ERROR', status: 422 });
  }
  if (!data || typeof data !== 'object' || !('event' in data)) {
    throw new OpenAgentApiError("webhook body must be a JSON object with an 'event' field", {
      code: 'VALIDATION_ERROR', status: 422,
    });
  }
  return data as Record<string, unknown>;
}
