// Central typed API client for OpenAgent.
// Single place for base URL, credentials, request-id, error parsing,
// retry (idempotent GETs), abort support, and org context.

export type ApiErrorCode =
  | 'VALIDATION_ERROR'
  | 'UNAUTHORIZED'
  | 'FORBIDDEN'
  | 'NOT_FOUND'
  | 'CONFLICT'
  | 'RATE_LIMITED'
  | 'SERVER_ERROR'
  | 'NETWORK_ERROR'
  | 'UNKNOWN_ERROR';

export interface ApiFieldError {
  field?: string;
  code: string;
  message: string;
}

export class ApiError extends Error {
  status: number;
  code: string;
  kind: ApiErrorCode;
  details?: ApiFieldError[];
  requestId?: string;

  constructor(
    message: string,
    opts: { status: number; code: string; details?: ApiFieldError[]; requestId?: string },
  ) {
    super(message);
    this.name = 'ApiError';
    this.status = opts.status;
    this.code = opts.code;
    this.details = opts.details;
    this.requestId = opts.requestId;
    this.kind = mapStatusToKind(opts.status, opts.code);
  }

  get userMessage(): string {
    return toUserMessage(this);
  }
}

function mapStatusToKind(status: number, code: string): ApiErrorCode {
  if (code === 'RATE_LIMITED' || status === 429) return 'RATE_LIMITED';
  switch (status) {
    case 400:
    case 422:
      return 'VALIDATION_ERROR';
    case 401:
      return 'UNAUTHORIZED';
    case 403:
      return 'FORBIDDEN';
    case 404:
      return 'NOT_FOUND';
    case 409:
      return 'CONFLICT';
    case 500:
    case 502:
    case 503:
    case 504:
      return 'SERVER_ERROR';
    case 0:
      return 'NETWORK_ERROR';
    default:
      return status >= 500 ? 'SERVER_ERROR' : 'UNKNOWN_ERROR';
  }
}

export function toUserMessage(err: unknown): string {
  if (err instanceof ApiError) {
    switch (err.kind) {
      case 'VALIDATION_ERROR':
        return err.details?.[0]?.message ?? err.message ?? 'Please check your input and try again.';
      case 'UNAUTHORIZED':
        return 'You are signed out. Please sign in again.';
      case 'FORBIDDEN':
        return 'You do not have permission to perform this action.';
      case 'NOT_FOUND':
        return 'The requested resource was not found.';
      case 'CONFLICT':
        return err.message || 'This conflicts with existing data.';
      case 'RATE_LIMITED':
        return 'Too many requests. Please wait a moment and retry.';
      case 'SERVER_ERROR':
        return 'Something went wrong on our side. Please retry.';
      case 'NETWORK_ERROR':
        return 'Network error. Check your connection and retry.';
      default:
        return err.message || 'Something went wrong.';
    }
  }
  if (err instanceof Error) return err.message;
  return 'Something went wrong.';
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1';

function getOrgId(): string | null {
  if (typeof window === 'undefined') return null;
  try {
    return window.localStorage.getItem('oa:org-id');
  } catch {
    return null;
  }
}

interface RequestOptions extends Omit<RequestInit, 'body'> {
  params?: Record<string, string | number | boolean | undefined | null>;
  body?: unknown;
  timeoutMs?: number;
  retry?: number;
  idempotencyKey?: string;
}

function buildUrl(endpoint: string, params?: RequestOptions['params']): string {
  const url = new URL(`${API_BASE}${endpoint}`);
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null && v !== '') url.searchParams.append(k, String(v));
    }
  }
  return url.toString();
}

function newRequestId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID();
  return `req_${Math.random().toString(36).slice(2)}${Date.now().toString(36)}`;
}

async function parseBody(res: Response): Promise<unknown> {
  const text = await res.text().catch(() => '');
  if (!text) return {};
  try {
    return JSON.parse(text);
  } catch {
    return { _raw: text };
  }
}

async function request<T>(endpoint: string, options: RequestOptions = {}): Promise<T> {
  const { params, body, headers, timeoutMs = 30000, retry, signal, idempotencyKey, ...rest } = options;
  const url = buildUrl(endpoint, params);
  const requestId = newRequestId();
  const orgId = getOrgId();

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const onAbort = () => controller.abort();
  if (signal) {
    if (signal.aborted) controller.abort();
    else signal.addEventListener('abort', onAbort, { once: true });
  }

  const attempts = retry ?? (rest.method === undefined || rest.method === 'GET' ? 1 : 0);

  let lastError: unknown = null;
  for (let attempt = 0; attempt <= attempts; attempt++) {
    try {
      const res = await fetch(url, {
        ...rest,
        signal: controller.signal,
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
          'X-Request-ID': requestId,
          ...(orgId ? { 'X-Organization-ID': orgId } : {}),
          ...(idempotencyKey ? { 'Idempotency-Key': idempotencyKey } : {}),
          ...headers,
        },
        body: body === undefined ? undefined : typeof body === 'string' ? body : JSON.stringify(body),
      });

      const data = (await parseBody(res)) as Record<string, unknown>;

      if (!res.ok) {
        const errObj = (data?.error as Record<string, unknown>) ?? {};
        const detail = data?.detail as unknown;
        const message =
          (typeof errObj.message === 'string' && errObj.message) ||
          (typeof detail === 'string' && detail) ||
          (typeof data?.message === 'string' && (data.message as string)) ||
          `Request failed (${res.status})`;
        throw new ApiError(message, {
          status: res.status,
          code: (errObj.code as string) || (data?.code as string) || `HTTP_${res.status}`,
          details: (errObj.details as ApiFieldError[]) ?? undefined,
          requestId:
            (errObj.request_id as string) || res.headers.get('x-request-id') || requestId,
        });
      }
      clearTimeout(timer);
      if (signal) signal.removeEventListener('abort', onAbort);
      return data as T;
    } catch (e) {
      lastError = e;
      if (e instanceof ApiError) {
        // Do not retry 4xx (except 429/408).
        if (e.status < 500 && e.status !== 429 && e.status !== 408) break;
      }
      if (e instanceof DOMException && e.name === 'AbortError') {
        // If user aborted, don't retry.
        if (signal?.aborted) break;
      }
      if (attempt < attempts) {
        await new Promise((r) => setTimeout(r, 250 * (attempt + 1)));
        continue;
      }
      break;
    }
  }
  clearTimeout(timer);
  if (signal) signal.removeEventListener('abort', onAbort);

  if (lastError instanceof ApiError) throw lastError;
  if (lastError instanceof DOMException && lastError.name === 'AbortError') {
    throw new ApiError('Request timed out or was cancelled.', {
      status: 0,
      code: 'NETWORK_ERROR',
      requestId,
    });
  }
  throw new ApiError(lastError instanceof Error ? lastError.message : 'Network error', {
    status: 0,
    code: 'NETWORK_ERROR',
    requestId,
  });
}

export const api = {
  get: <T>(endpoint: string, params?: RequestOptions['params'], opts?: RequestOptions) =>
    request<T>(endpoint, { ...opts, method: 'GET', params }),
  post: <T>(endpoint: string, body?: unknown, opts?: RequestOptions) =>
    request<T>(endpoint, { ...opts, method: 'POST', body }),
  put: <T>(endpoint: string, body?: unknown, opts?: RequestOptions) =>
    request<T>(endpoint, { ...opts, method: 'PUT', body }),
  patch: <T>(endpoint: string, body?: unknown, opts?: RequestOptions) =>
    request<T>(endpoint, { ...opts, method: 'PATCH', body }),
  delete: <T>(endpoint: string, opts?: RequestOptions) =>
    request<T>(endpoint, { ...opts, method: 'DELETE' }),
};

export { API_BASE };
