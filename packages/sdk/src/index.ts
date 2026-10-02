// SDK Package — public SDK for OpenAgent (provider-neutral).

export const SDK_VERSION = '1.0.0';
export const API_VERSION = 'v1';

export interface SDKConfig {
  apiUrl: string;
  apiKey?: string;
  organizationId?: string;
  timeoutMs?: number;
  maxRetries?: number;
  // Accept both spellings: `apiUrl` (canonical) and `baseUrl`.
  baseUrl?: string;
}

export interface OpenAgentConfig {
  apiKey?: string;
  baseUrl?: string;
  apiUrl?: string;
  organizationId?: string;
  timeoutMs?: number;
  maxRetries?: number;
}

interface RequestOptions {
  idempotencyKey?: string;
  requestId?: string;
  timeoutMs?: number;
  signal?: AbortSignal;
}

export type ErrorCode =
  | 'AUTHENTICATION_ERROR' | 'AUTHORIZATION_ERROR' | 'VALIDATION_ERROR'
  | 'NOT_FOUND' | 'CONFLICT' | 'RATE_LIMITED' | 'TIMEOUT'
  | 'POLICY_DENIED' | 'APPROVAL_REQUIRED' | 'COMPATIBILITY_ERROR'
  | 'EXTENSION_ERROR' | 'TOOL_EXECUTION_ERROR' | 'CONNECTOR_ERROR'
  | 'MCP_ERROR' | 'SANDBOX_ERROR' | 'DEPLOYMENT_ERROR' | 'SERVER_ERROR'
  | 'NETWORK_ERROR';

export class OpenAgentError extends Error {
  code: ErrorCode;
  status: number;
  requestId: string;
  constructor(message: string, opts: { code?: ErrorCode; status?: number; requestId?: string } = {}) {
    super(message);
    this.name = 'OpenAgentError';
    this.code = opts.code ?? 'SERVER_ERROR';
    this.status = opts.status ?? 0;
    this.requestId = opts.requestId ?? '';
  }
}

export class AuthenticationError extends OpenAgentError {
  constructor(m: string, o = {}) { super(m, { ...o, code: 'AUTHENTICATION_ERROR', status: 401 }); }
}
export class AuthorizationError extends OpenAgentError {
  constructor(m: string, o = {}) { super(m, { ...o, code: 'AUTHORIZATION_ERROR', status: 403 }); }
}
export class ValidationError extends OpenAgentError {
  constructor(m: string, o = {}) { super(m, { ...o, code: 'VALIDATION_ERROR', status: 422 }); }
}
export class NotFoundError extends OpenAgentError {
  constructor(m: string, o = {}) { super(m, { ...o, code: 'NOT_FOUND', status: 404 }); }
}
export class ConflictError extends OpenAgentError {
  constructor(m: string, o = {}) { super(m, { ...o, code: 'CONFLICT', status: 409 }); }
}
export class RateLimitError extends OpenAgentError {
  constructor(m: string, o = {}) { super(m, { ...o, code: 'RATE_LIMITED', status: 429 }); }
}
export class TimeoutError extends OpenAgentError {
  constructor(m: string, o = {}) { super(m, { ...o, code: 'TIMEOUT', status: 408 }); }
}
export class PolicyDeniedError extends OpenAgentError {
  constructor(m: string, o = {}) { super(m, { ...o, code: 'POLICY_DENIED', status: 403 }); }
}
export class ApprovalRequiredError extends OpenAgentError {
  constructor(m: string, o = {}) { super(m, { ...o, code: 'APPROVAL_REQUIRED', status: 403 }); }
}
export class CompatibilityError extends OpenAgentError {
  constructor(m: string, o = {}) { super(m, { ...o, code: 'COMPATIBILITY_ERROR', status: 422 }); }
}
export class ExtensionError extends OpenAgentError {
  constructor(m: string, o = {}) { super(m, { ...o, code: 'EXTENSION_ERROR', status: 422 }); }
}
export class ToolExecutionError extends OpenAgentError {
  constructor(m: string, o = {}) { super(m, { ...o, code: 'TOOL_EXECUTION_ERROR', status: 502 }); }
}
export class ConnectorError extends OpenAgentError {
  constructor(m: string, o = {}) { super(m, { ...o, code: 'CONNECTOR_ERROR', status: 502 }); }
}
export class MCPError extends OpenAgentError {
  constructor(m: string, o = {}) { super(m, { ...o, code: 'MCP_ERROR', status: 502 }); }
}
export class SandboxError extends OpenAgentError {
  constructor(m: string, o = {}) { super(m, { ...o, code: 'SANDBOX_ERROR', status: 502 }); }
}
export class DeploymentError extends OpenAgentError {
  constructor(m: string, o = {}) { super(m, { ...o, code: 'DEPLOYMENT_ERROR', status: 502 }); }
}

function toTypedError(status: number, path: string, requestId: string): OpenAgentError {
  const message = `SDK request failed (${status}): ${path}`;
  const opts = { requestId };
  if (status === 401) return new AuthenticationError(message, opts);
  if (status === 403) return new AuthorizationError(message, opts);
  if (status === 404) return new NotFoundError(message, opts);
  if (status === 409) return new ConflictError(message, opts);
  if (status === 429) return new RateLimitError(message, opts);
  if (status === 408) return new TimeoutError(message, opts);
  if (status === 422) return new ValidationError(message, opts);
  return new OpenAgentError(message, { ...opts, status });
}

function baseUrlOf(config: SDKConfig): string {
  const raw = (config.apiUrl ?? config.baseUrl ?? '') as string;
  return raw.replace(/\/+$/, '');
}

function newRequestId(): string {
  const c = (globalThis as { crypto?: { randomUUID?: () => string } }).crypto;
  if (c?.randomUUID) return c.randomUUID();
  return `req_${Date.now().toString(36)}_${Math.floor(Math.random() * 1e9).toString(36)}`;
}

const sleep = (ms: number): Promise<void> => new Promise((r) => setTimeout(r, ms));

async function http<T>(config: SDKConfig, path: string, init?: RequestInit & RequestOptions): Promise<T> {
  const method = (init?.method ?? 'GET').toUpperCase();
  const safe = method === 'GET' || method === 'HEAD' || Boolean(init?.idempotencyKey);
  const maxRetries = safe ? (config.maxRetries ?? 3) : 0;
  const requestId = init?.requestId ?? newRequestId();
  let lastError: unknown = null;
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), init?.timeoutMs ?? config.timeoutMs ?? 30_000);
    try {
      const res = await fetch(`${baseUrlOf(config)}${path}`, {
        ...init,
        signal: init?.signal ?? controller.signal,
        headers: {
          'Content-Type': 'application/json',
          ...(config.apiKey ? { Authorization: `Bearer ${config.apiKey}` } : {}),
          ...(config.organizationId ? { 'X-Organization-ID': config.organizationId } : {}),
          ...(init?.idempotencyKey ? { 'Idempotency-Key': init.idempotencyKey } : {}),
          'X-Request-ID': requestId,
          ...init?.headers,
        },
      });
      if ((res.status === 429 || (res.status >= 500 && res.status < 600)) && attempt < maxRetries) {
        const retryAfter = Number(res.headers.get('Retry-After') ?? 0);
        await sleep(retryAfter > 0 ? retryAfter * 1000 : 250 * 2 ** attempt);
        continue;
      }
      if (!res.ok) {
        throw toTypedError(res.status, path, requestId);
      }
      if (res.status === 204) return undefined as T;
      return (await res.json()) as T;
    } catch (err) {
      lastError = err;
      if (err instanceof OpenAgentError) throw err;
      if (attempt >= maxRetries) {
        throw new OpenAgentError(
          err instanceof Error && err.name === 'AbortError' ? 'Request timed out' : 'Network error',
          { code: err instanceof Error && err.name === 'AbortError' ? 'TIMEOUT' : 'NETWORK_ERROR', requestId },
        );
      }
      await sleep(250 * 2 ** attempt);
    } finally {
      clearTimeout(timeout);
    }
  }
  throw lastError instanceof Error ? lastError : new OpenAgentError('Request failed');
}

function orgPath(config: SDKConfig, suffix: string): string {
  return `/api/v1/organizations/${config.organizationId}${suffix}`;
}

export function createSDK(config: SDKConfig) {
  return {
    agents: {
      async list() {
        return http(config, orgPath(config, '/agents'));
      },
      async create(input: unknown, opts?: RequestOptions) {
        return http(config, orgPath(config, '/agents'), {
          method: 'POST',
          body: JSON.stringify(input),
          ...opts,
        });
      },
    },
    workflows: {
      async list() {
        return http(config, orgPath(config, '/workflows'));
      },
      async create(input: unknown, opts?: RequestOptions) {
        return http(config, orgPath(config, '/workflows'), {
          method: 'POST',
          body: JSON.stringify(input),
          ...opts,
        });
      },
    },
    runs: {
      async list() {
        return http(config, orgPath(config, '/runs'));
      },
      async get(input: unknown) {
        return http(config, orgPath(config, `/runs/${String(input)}`));
      },
    },
    orchestrations: {
      async create(
        input: { objective: string; template?: string; idempotency_key?: string },
        opts?: RequestOptions,
      ) {
        return http(config, orgPath(config, '/orchestrations'), {
          method: 'POST',
          body: JSON.stringify(input),
          idempotencyKey: opts?.idempotencyKey ?? input.idempotency_key,
        });
      },
      async list(params?: { status?: string; page?: number; page_size?: number }) {
        const qs = new URLSearchParams(
          Object.entries(params ?? {}).reduce<Record<string, string>>((acc, [k, v]) => {
            if (v !== undefined) acc[k] = String(v);
            return acc;
          }, {}),
        ).toString();
        return http(config, orgPath(config, `/orchestrations${qs ? `?${qs}` : ''}`));
      },
      async get(id: string) {
        return http(config, orgPath(config, `/orchestrations/${id}`));
      },
      async plan(id: string, plan: unknown) {
        return http(config, orgPath(config, `/orchestrations/${id}/plan`), {
          method: 'POST',
          body: JSON.stringify(plan),
        });
      },
      async start(id: string, opts?: RequestOptions) {
        return http(config, orgPath(config, `/orchestrations/${id}/start`), {
          method: 'POST',
          body: JSON.stringify({}),
          ...opts,
        });
      },
      async pause(id: string) {
        return http(config, orgPath(config, `/orchestrations/${id}/pause`), {
          method: 'POST',
          body: JSON.stringify({}),
        });
      },
      async resume(id: string) {
        return http(config, orgPath(config, `/orchestrations/${id}/resume`), {
          method: 'POST',
          body: JSON.stringify({}),
          ...optsSafe(),
        });
      },
      async cancel(id: string) {
        return http(config, orgPath(config, `/orchestrations/${id}/cancel`), {
          method: 'POST',
          body: JSON.stringify({}),
        });
      },
      async tasks(id: string) {
        return http(config, orgPath(config, `/orchestrations/${id}/tasks`));
      },
      async messages(id: string) {
        return http(config, orgPath(config, `/orchestrations/${id}/messages`));
      },
      async events(id: string) {
        return http(config, orgPath(config, `/orchestrations/${id}/events`));
      },
      async retryTask(id: string, taskId: string) {
        return http(config, orgPath(config, `/orchestrations/${id}/tasks/${taskId}/retry`), {
          method: 'POST',
          body: JSON.stringify({}),
        });
      },
      async reassignTask(id: string, taskId: string, agentId: string) {
        return http(config, orgPath(config, `/orchestrations/${id}/tasks/${taskId}/reassign`), {
          method: 'POST',
          body: JSON.stringify({ agent_id: agentId }),
        });
      },
    },
    browser: {
      async createSession(input?: { headless?: boolean; browser_profile_id?: string }) {
        return http(config, '/api/v1/browser/sessions', {
          method: 'POST',
          body: JSON.stringify(input ?? { headless: true }),
        });
      },
      async listSessions() {
        return http(config, '/api/v1/browser/sessions');
      },
      async closeSession(sessionId: string) {
        return http(config, `/api/v1/browser/sessions/${sessionId}`, { method: 'DELETE' });
      },
      async createTask(input: { browser_session_id: string; objective: string; max_steps?: number }) {
        return http(config, '/api/v1/browser/tasks', {
          method: 'POST',
          body: JSON.stringify(input),
        });
      },
      async runAction(
        taskId: string,
        action: { action_type: string; page_id: string; input: Record<string, unknown>; approved?: boolean },
      ) {
        return http(config, `/api/v1/browser/tasks/${taskId}/actions`, {
          method: 'POST',
          body: JSON.stringify(action),
        });
      },
      async listPolicies() {
        return http(config, '/api/v1/browser/policies');
      },
    },
    code: {
      // Repositories — writes accept `credential_ref` handles only, never raw secrets.
      async createRepository(input: {
        provider: 'local' | 'generic' | 'github' | 'gitlab' | 'bitbucket';
        name: string;
        full_name: string;
        clone_url: string;
        default_branch?: string;
        visibility?: 'private' | 'public' | 'internal';
        credential_ref?: string;
        provider_config?: Record<string, unknown>;
        external_id?: string;
      }) {
        return http(config, '/api/v1/repositories', {
          method: 'POST',
          body: JSON.stringify(input),
        });
      },
      async listRepositories() {
        return http(config, '/api/v1/repositories');
      },
      async getRepository(id: string) {
        return http(config, `/api/v1/repositories/${id}`);
      },
      async connectRepository(id: string) {
        return http(config, `/api/v1/repositories/${id}/connect`, {
          method: 'POST',
          body: JSON.stringify({}),
        });
      },
      async syncRepository(id: string) {
        return http(config, `/api/v1/repositories/${id}/sync`, {
          method: 'POST',
          body: JSON.stringify({}),
        });
      },
      // Workspaces — server-side checkouts; host paths are never returned.
      async createWorkspace(input: { repository_id: string; task_id?: string; branch?: string }) {
        return http(config, '/api/v1/code/workspaces', {
          method: 'POST',
          body: JSON.stringify(input),
        });
      },
      async listWorkspaces(params?: { status?: string }) {
        const qs = params?.status ? `?status=${encodeURIComponent(params.status)}` : '';
        return http(config, `/api/v1/code/workspaces${qs}`);
      },
      async getWorkspace(id: string) {
        return http(config, `/api/v1/code/workspaces/${id}`);
      },
      async deleteWorkspace(id: string, force = false) {
        return http(config, `/api/v1/code/workspaces/${id}${force ? '?force=true' : ''}`, {
          method: 'DELETE',
        });
      },
      async listFiles(workspaceId: string, prefix = '') {
        const qs = prefix ? `?prefix=${encodeURIComponent(prefix)}` : '';
        return http(config, `/api/v1/code/workspaces/${workspaceId}/files${qs}`);
      },
      async readFile(workspaceId: string, path: string, range?: { start?: number; end?: number }) {
        const qs = new URLSearchParams({ path });
        if (range?.start !== undefined) qs.set('start', String(range.start));
        if (range?.end !== undefined) qs.set('end', String(range.end));
        return http(config, `/api/v1/code/workspaces/${workspaceId}/files/read?${qs.toString()}`);
      },
      // Coding tasks — the canonical software-engineering entrypoint.
      tasks: {
        async create(input: {
          repository_id: string;
          objective: string;
          branch?: string;
          max_steps?: number;
          max_duration_seconds?: number;
          risk_level?: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
          budgets?: Record<string, unknown>;
        }) {
          return http(config, '/api/v1/code/tasks', {
            method: 'POST',
            body: JSON.stringify(input),
          });
        },
        async list(params?: { status?: string; repository_id?: string }) {
          const qs = new URLSearchParams(
            Object.entries(params ?? {}).reduce<Record<string, string>>((acc, [k, v]) => {
              if (v !== undefined) acc[k] = String(v);
              return acc;
            }, {}),
          ).toString();
          return http(config, `/api/v1/code/tasks${qs ? `?${qs}` : ''}`);
        },
        async get(id: string) {
          return http(config, `/api/v1/code/tasks/${id}`);
        },
        async cancel(id: string) {
          return http(config, `/api/v1/code/tasks/${id}/cancel`, {
            method: 'POST',
            body: JSON.stringify({}),
          });
        },
        async pause(id: string) {
          return http(config, `/api/v1/code/tasks/${id}/pause`, {
            method: 'POST',
            body: JSON.stringify({}),
          });
        },
        async resume(id: string) {
          return http(config, `/api/v1/code/tasks/${id}/resume`, {
            method: 'POST',
            body: JSON.stringify({}),
          });
        },
        async wait(
          id: string,
          opts?: { timeoutMs?: number; intervalMs?: number },
        ): Promise<{ id: string; status: string; [k: string]: unknown }> {
          const terminal = new Set(['SUCCEEDED', 'FAILED', 'CANCELLED', 'TIMED_OUT', 'READY_FOR_PR']);
          const deadline = Date.now() + (opts?.timeoutMs ?? 30 * 60 * 1000);
          const interval = opts?.intervalMs ?? 5000;
          for (;;) {
            const t = (await http(config, `/api/v1/code/tasks/${id}`)) as {
              id: string;
              status: string;
              [k: string]: unknown;
            };
            if (terminal.has(t.status) || Date.now() > deadline) return t;
            await new Promise((r) => setTimeout(r, interval));
          }
        },
        async result(id: string) {
          const [task, diff, events] = await Promise.all([
            http(config, `/api/v1/code/tasks/${id}`),
            http(config, `/api/v1/code/tasks/${id}/diff`),
            http(config, `/api/v1/code/tasks/${id}/events`),
          ]);
          return { task, diff, events };
        },
        async plan(id: string) {
          return http(config, `/api/v1/code/tasks/${id}/plan`);
        },
        async diff(id: string) {
          return http(config, `/api/v1/code/tasks/${id}/diff`);
        },
        async events(id: string) {
          return http(config, `/api/v1/code/tasks/${id}/events`);
        },
        async artifacts(id: string) {
          return http(config, `/api/v1/code/tasks/${id}/artifacts`);
        },
        async applyPatch(id: string, input: { diff: string; approved?: boolean; approval_id?: string }) {
          return http(config, `/api/v1/code/tasks/${id}/patch`, {
            method: 'POST',
            body: JSON.stringify(input),
          });
        },
        async commit(id: string, message: string) {
          return http(config, `/api/v1/code/tasks/${id}/commit`, {
            method: 'POST',
            body: JSON.stringify({ message }),
          });
        },
        async push(id: string, input?: { approved?: boolean; approval_id?: string; force?: boolean }) {
          return http(config, `/api/v1/code/tasks/${id}/push`, {
            method: 'POST',
            body: JSON.stringify(input ?? {}),
          });
        },
        async planTests(id: string) {
          return http(config, `/api/v1/code/tasks/${id}/tests/plan`, {
            method: 'POST',
            body: JSON.stringify({}),
          });
        },
      },
      async search(input: {
        workspace_id: string;
        query: string;
        mode?: 'text' | 'regex' | 'symbol' | 'references' | 'semantic';
        symbol?: string;
        top_k?: number;
      }) {
        return http(config, '/api/v1/code/search', {
          method: 'POST',
          body: JSON.stringify(input),
        });
      },
      async review(input: { task_id?: string; filename?: string; content?: string }) {
        return http(config, '/api/v1/code/review', {
          method: 'POST',
          body: JSON.stringify(input),
        });
      },
      async execute(input: {
        workspace_id?: string;
        task_id?: string;
        profile?: 'TEST' | 'LINT' | 'TYPECHECK' | 'BUILD' | 'PACKAGE' | 'MIGRATION' | 'CUSTOM';
        command: string;
      }) {
        return http(config, '/api/v1/code/execute', {
          method: 'POST',
          body: JSON.stringify(input),
        });
      },
      async preparePR(input: { task_id: string; title: string; summary?: string; open?: boolean }) {
        return http(config, '/api/v1/code/pr', {
          method: 'POST',
          body: JSON.stringify(input),
        });
      },
    },
    sandbox: {
      async create(input?: {
        profile?: string;
        task_id?: string;
        workspace_host_path?: string;
        workspace_mode?: 'WORKSPACE_RW' | 'WORKSPACE_RO';
        image?: string;
        image_digest?: string;
        ttl_seconds?: number;
      }) {
        return http(config, '/api/v1/sandboxes', {
          method: 'POST',
          body: JSON.stringify(input ?? { profile: 'TEST' }),
        });
      },
      async list(params?: { status?: string }) {
        const qs = params?.status ? `?status=${encodeURIComponent(params.status)}` : '';
        return http(config, `/api/v1/sandboxes${qs}`);
      },
      async get(id: string) {
        return http(config, `/api/v1/sandboxes/${id}`);
      },
      async start(id: string) {
        return http(config, `/api/v1/sandboxes/${id}/start`, {
          method: 'POST',
          body: JSON.stringify({}),
        });
      },
      async stop(id: string) {
        return http(config, `/api/v1/sandboxes/${id}/stop`, {
          method: 'POST',
          body: JSON.stringify({}),
        });
      },
      async destroy(id: string) {
        return http(config, `/api/v1/sandboxes/${id}`, { method: 'DELETE' });
      },
      async execute(
        id: string,
        input: {
          command: string | string[];
          workdir?: string;
          env?: Record<string, string>;
          credential_refs?: Record<string, string>;
          timeout_seconds?: number;
          approved?: boolean;
          artifacts?: Array<{ path: string; name?: string }>;
        },
      ) {
        return http(config, `/api/v1/sandboxes/${id}/execute`, {
          method: 'POST',
          body: JSON.stringify(input),
        });
      },
      async executions(sandboxId: string) {
        return http(config, `/api/v1/sandboxes/${sandboxId}/executions`);
      },
      async execution(sandboxId: string, executionId: string) {
        return http(config, `/api/v1/sandboxes/${sandboxId}/executions/${executionId}`);
      },
      async wait(
        sandboxId: string,
        executionId: string,
        opts?: { timeoutMs?: number; intervalMs?: number },
      ): Promise<{ execution_id: string; status: string; [k: string]: unknown }> {
        const terminal = new Set([
          'SUCCEEDED', 'FAILED', 'TIMED_OUT', 'CANCELLED', 'KILLED',
          'RESOURCE_LIMIT', 'POLICY_DENIED', 'SANDBOX_ERROR', 'WAITING_FOR_APPROVAL',
        ]);
        const deadline = Date.now() + (opts?.timeoutMs ?? 30 * 60 * 1000);
        const interval = opts?.intervalMs ?? 5000;
        for (;;) {
          const e = (await http(
            config,
            `/api/v1/sandboxes/${sandboxId}/executions/${executionId}`,
          )) as { execution_id: string; status: string; [k: string]: unknown };
          if (terminal.has(e.status) || Date.now() > deadline) return e;
          await new Promise((r) => setTimeout(r, interval));
        }
      },
      async cancel(sandboxId: string, executionId: string) {
        return http(config, `/api/v1/sandboxes/${sandboxId}/executions/${executionId}/cancel`, {
          method: 'POST',
          body: JSON.stringify({}),
        });
      },
      async events(sandboxId: string) {
        return http(config, `/api/v1/sandboxes/${sandboxId}/events`);
      },
      async artifacts(sandboxId: string) {
        return http(config, `/api/v1/sandboxes/${sandboxId}/artifacts`);
      },
      async acquireLease(sandboxId: string, input: { owner: string; ttl_seconds?: number }) {
        return http(config, `/api/v1/sandboxes/${sandboxId}/leases`, {
          method: 'POST',
          body: JSON.stringify(input),
        });
      },
      async listProfiles() {
        return http(config, '/api/v1/sandbox-profiles');
      },
      async securityCheck() {
        return http(config, '/api/v1/sandboxes/security/check');
      },
    },
    management: {
      mgmt(path: string) {
        return orgPath(config, `/management${path}`);
      },
      async createManager(input: unknown, opts?: RequestOptions) {
        return http(config, orgPath(config, '/management/managers'), {
          method: 'POST',
          body: JSON.stringify(input),
          ...opts,
        });
      },
      async createContract(input: unknown, opts?: RequestOptions) {
        return http(config, orgPath(config, '/management/contracts'), {
          method: 'POST',
          body: JSON.stringify(input),
          ...opts,
        });
      },
      async delegate(input: unknown, opts?: RequestOptions) {
        return http(config, orgPath(config, '/management/delegations'), {
          method: 'POST',
          body: JSON.stringify(input),
          ...opts,
        });
      },
      async delegationAction(id: string, action: string, body?: unknown) {
        return http(config, orgPath(config, `/management/delegations/${id}/${action}`), {
          method: 'POST',
          body: JSON.stringify(body ?? {}),
        });
      },
      async handoff(input: unknown, opts?: RequestOptions) {
        return http(config, orgPath(config, '/management/handoffs'), {
          method: 'POST',
          body: JSON.stringify(input),
          ...opts,
        });
      },
      async handoffAction(id: string, action: string) {
        return http(config, orgPath(config, `/management/handoffs/${id}/${action}`), {
          method: 'POST',
          body: JSON.stringify({}),
        });
      },
      async review(input: unknown) {
        return http(config, orgPath(config, '/management/reviews'), {
          method: 'POST',
          body: JSON.stringify(input),
        });
      },
      async escalate(input: unknown, opts?: RequestOptions) {
        return http(config, orgPath(config, '/management/escalations'), {
          method: 'POST',
          body: JSON.stringify(input),
          ...opts,
        });
      },
      async escalationAction(id: string, action: string, body?: unknown) {
        return http(config, orgPath(config, `/management/escalations/${id}/${action}`), {
          method: 'POST',
          body: JSON.stringify(body ?? {}),
        });
      },
      async formTeam(input: unknown) {
        return http(config, orgPath(config, '/management/teams/form'), {
          method: 'POST',
          body: JSON.stringify(input),
        });
      },
      async teamAction(id: string, action: string) {
        return http(config, orgPath(config, `/management/teams/${id}/${action}`), {
          method: 'POST',
          body: JSON.stringify({}),
        });
      },
      async console(runId?: string) {
        return http(
          config,
          orgPath(config, `/management/console${runId ? `?run_id=${runId}` : ''}`),
        );
      },
      async orgChart() {
        return http(config, orgPath(config, '/management/organization/chart'));
      },
    },
    approvals: {
      async list(params?: { status?: string; risk_level?: string }) {
        const q = new URLSearchParams({
          ...(params?.status ? { status: params.status } : {}),
          ...(params?.risk_level ? { risk_level: params.risk_level } : {}),
        }).toString();
        return http(config, orgPath(config, `/approvals${q ? `?${q}` : ''}`));
      },
      async get(id: string) {
        return http(config, orgPath(config, `/approvals/${id}`));
      },
      async history(id: string) {
        return http(config, orgPath(config, `/approvals/${id}/history`));
      },
      async request(
        input: {
          action_type: string;
          action_category?: string;
          requested_params?: Record<string, unknown>;
          target_type?: string;
          target_id?: string;
          impact_summary?: string;
          environment?: string;
        },
        opts?: RequestOptions,
      ) {
        return http(config, orgPath(config, '/approvals'), {
          method: 'POST',
          body: JSON.stringify(input),
          ...opts,
        });
      },
      async approve(id: string, reason?: string, opts?: RequestOptions) {
        return http(config, orgPath(config, `/approvals/${id}/approve`), {
          method: 'POST',
          body: JSON.stringify({ reason: reason ?? '' }),
          ...opts,
        });
      },
      async reject(id: string, reason?: string, opts?: RequestOptions) {
        return http(config, orgPath(config, `/approvals/${id}/reject`), {
          method: 'POST',
          body: JSON.stringify({ reason: reason ?? '' }),
          ...opts,
        });
      },
      async cancel(id: string, reason?: string) {
        return http(config, orgPath(config, `/approvals/${id}/cancel`), {
          method: 'POST',
          body: JSON.stringify({ reason: reason ?? '' }),
        });
      },
      async escalate(id: string, input?: { reason?: string; escalate_to?: string }) {
        return http(config, orgPath(config, `/approvals/${id}/escalate`), {
          method: 'POST',
          body: JSON.stringify(input ?? {}),
        });
      },
      async simulate(input: {
        action_type: string;
        action_category: string;
        target_type?: string;
        target_id?: string;
        environment?: string;
        tool_name?: string;
      }) {
        return http(config, orgPath(config, '/approvals/simulate'), {
          method: 'POST',
          body: JSON.stringify(input),
        });
      },
      // Safe helper: run a guarded tool call, returning the approval when gated.
      // There is intentionally no execute-without-approval API.
      async guardedToolCall(tool: { slug: string }, args: { tool_id: string; input?: unknown }) {
        void tool;
        return http(config, orgPath(config, '/tools/execute'), {
          method: 'POST',
          body: JSON.stringify(args),
        });
      },
    },
    // Evaluator, verification & self-correction. Safe interfaces only:
    // evaluate / verify / decide / correct. There is intentionally no
    // force_success / disable_evaluation / bypass_quality_gate API.
    evaluator: {
      async evaluate(
        input: {
          evaluation_type?: string;
          task_id?: string;
          agent_id?: string;
          agent_run_id?: string;
          workflow_id?: string;
          workflow_execution_id?: string;
          criteria?: unknown;
          goal?: string;
          input_ref?: unknown;
          output_ref?: unknown;
          evidence?: unknown[];
          quality_threshold?: number;
        },
        opts?: RequestOptions,
      ) {
        return http(config, orgPath(config, '/evaluations'), {
          method: 'POST',
          body: JSON.stringify(input),
          ...opts,
        });
      },
      async list(params?: { status?: string; decision?: string; evaluation_type?: string }) {
        const q = new URLSearchParams({
          ...(params?.status ? { status: params.status } : {}),
          ...(params?.decision ? { decision: params.decision } : {}),
          ...(params?.evaluation_type ? { evaluation_type: params.evaluation_type } : {}),
        }).toString();
        return http(config, orgPath(config, `/evaluations${q ? `?${q}` : ''}`));
      },
      async get(id: string) {
        return http(config, orgPath(config, `/evaluations/${id}`));
      },
      async verify(id: string, checks: unknown[]) {
        return http(config, orgPath(config, `/evaluations/${id}/verify`), {
          method: 'POST',
          body: JSON.stringify({ checks }),
        });
      },
      async decide(
        id: string,
        input?: { quality_threshold?: number; confidence_threshold?: number; disagreement_policy?: string },
      ) {
        return http(config, orgPath(config, `/evaluations/${id}/finalize`), {
          method: 'POST',
          body: JSON.stringify(input ?? {}),
        });
      },
      async correct(
        id: string,
        input?: { strategy?: string; changes?: unknown; root_cause?: unknown; risk_level?: string },
      ) {
        return http(config, orgPath(config, `/evaluations/${id}/correct`), {
          method: 'POST',
          body: JSON.stringify(input ?? {}),
        });
      },
      async retry(id: string, reason?: string) {
        return http(config, orgPath(config, `/evaluations/${id}/retry`), {
          method: 'POST',
          body: JSON.stringify({ reason: reason ?? '' }),
        });
      },
      async evidence(id: string) {
        return http(config, orgPath(config, `/evaluations/${id}/evidence`));
      },
      async history(id: string) {
        return http(config, orgPath(config, `/evaluations/${id}/history`));
      },
      async feedback(id: string, input: { verdict: string; reason?: string; feedback?: string }) {
        return http(config, orgPath(config, `/evaluations/${id}/feedback`), {
          method: 'POST',
          body: JSON.stringify(input),
        });
      },
      // Workflow authoring helpers (nodes run in the existing engine).
      nodes: {
        verify: (checks: unknown[], target?: unknown) => ({
          type: 'verify',
          config: { checks, ...(target !== undefined ? { target } : {}) },
        }),
        evaluate: (score: unknown, quality_threshold = 0.7) => ({
          type: 'evaluate',
          config: { score, quality_threshold },
        }),
        assert: (conditions: unknown[]) => ({ type: 'assert', config: { conditions } }),
        qualityGate: (gate: string, check_targets?: unknown) => ({
          type: 'quality_gate',
          config: { gate, ...(check_targets !== undefined ? { check_targets } : {}) },
        }),
        retry: (max_attempts = 3) => ({ type: 'retry', config: { max_attempts } }),
        correct: (strategy = 'RETRY_SAME', max_correction_cycles = 3) => ({
          type: 'correct',
          config: { strategy, max_correction_cycles },
        }),
        connectorAction: (action_id: string, connection_id?: string, input?: unknown) => ({
          type: 'connector_action',
          config: { action_id, ...(connection_id ? { connection_id } : {}), input: input ?? {} },
        }),
        connectorTrigger: (trigger_id: string) => ({
          type: 'connector_trigger',
          config: { trigger_id },
        }),
        connectorSearch: (query: string, limit = 10) => ({
          type: 'connector_search',
          config: { query, limit },
        }),
        connectorResource: (kind: string, connector?: string) => ({
          type: 'connector_resource',
          config: { kind, ...(connector ? { connector } : {}) },
        }),
      },
    },
    integrations: {
      async catalog(params?: { category?: string; trust?: string; search?: string }) {
        const q = new URLSearchParams({
          ...(params?.category ? { category: params.category } : {}),
          ...(params?.trust ? { trust: params.trust } : {}),
          ...(params?.search ? { search: params.search } : {}),
        }).toString();
        return http(config, orgPath(config, `/connectors${q ? `?${q}` : ''}`));
      },
      async get(connector: string) {
        return http(config, orgPath(config, `/connectors/${connector}`));
      },
      async actions(connector: string) {
        return http(config, orgPath(config, `/connectors/${connector}/actions`));
      },
      async search(query: string, kind = 'action') {
        return http(
          config,
          orgPath(config, `/connectors/search?q=${encodeURIComponent(query)}&kind=${kind}`),
        );
      },
      async connections(params?: { connector_id?: string; status?: string }) {
        const q = new URLSearchParams({
          ...(params?.connector_id ? { connector_id: params.connector_id } : {}),
          ...(params?.status ? { status: params.status } : {}),
        }).toString();
        return http(config, orgPath(config, `/integration-connections${q ? `?${q}` : ''}`));
      },
      async createConnection(input: unknown, opts?: RequestOptions) {
        return http(config, orgPath(config, '/integration-connections'), {
          method: 'POST',
          body: JSON.stringify(input),
          ...opts,
        });
      },
      async executeAction(connection: string, action: string, input?: unknown, opts?: RequestOptions) {
        return http(config, orgPath(config, `/integration-connections/${connection}/execute`), {
          method: 'POST',
          body: JSON.stringify({ action_id: action, input: input ?? {} }),
          ...opts,
        });
      },
      async testConnection(connection: string) {
        return http(config, orgPath(config, `/integration-connections/${connection}/test`), {
          method: 'POST',
          body: JSON.stringify({}),
        });
      },
      async disconnect(connection: string) {
        return http(config, orgPath(config, `/integration-connections/${connection}/disconnect`), {
          method: 'POST',
          body: JSON.stringify({}),
        });
      },
      async removeConnection(connection: string) {
        return http(config, orgPath(config, `/integration-connections/${connection}`), {
          method: 'DELETE',
        });
      },
      async updateConnection(connection: string, input: unknown) {
        return http(config, orgPath(config, `/integration-connections/${connection}`), {
          method: 'PATCH',
          body: JSON.stringify(input),
        });
      },
      async connect(connection: string, input?: { redirect_uri?: string; scopes?: string[] }) {
        return http(config, orgPath(config, `/integration-connections/${connection}/connect`), {
          method: 'POST',
          body: JSON.stringify(input ?? {}),
        });
      },
      async connectionHealth(connection: string) {
        return http(config, orgPath(config, `/integration-connections/${connection}/health`));
      },
      async connectionEvents(connection: string, params?: { limit?: number }) {
        const qs = params?.limit ? `?limit=${params.limit}` : '';
        return http(config, orgPath(config, `/integration-connections/${connection}/events${qs}`));
      },
      async connectorHealth(connector: string) {
        return http(config, orgPath(config, `/connectors/${connector}/health`));
      },
      async capabilities(connector: string) {
        return http(config, orgPath(config, `/connectors/${connector}/capabilities`));
      },
      async triggers(connector: string) {
        return http(config, orgPath(config, `/connectors/${connector}/triggers`));
      },
      async registerConnector(manifest: unknown, opts?: RequestOptions) {
        return http(config, orgPath(config, '/connectors'), {
          method: 'POST',
          body: JSON.stringify({ manifest }),
          ...opts,
        });
      },
      async syncConnectors(opts?: RequestOptions) {
        return http(config, orgPath(config, '/connectors/sync'), {
          method: 'POST',
          body: JSON.stringify({}),
          ...opts,
        });
      },
      async permissions(connection: string) {
        return http(config, orgPath(config, `/integration-connections/${connection}/permissions`));
      },
      async grantPermission(connection: string, input: { capability: string }) {
        return http(config, orgPath(config, `/integration-connections/${connection}/permissions`), {
          method: 'POST',
          body: JSON.stringify(input),
        });
      },
      credentials: {
        async list() {
          return http(config, orgPath(config, '/credentials'));
        },
        async create(input: unknown, opts?: RequestOptions) {
          return http(config, orgPath(config, '/credentials'), {
            method: 'POST',
            body: JSON.stringify(input),
            ...opts,
          });
        },
        async rotate(id: string, secrets: Record<string, unknown>) {
          return http(config, orgPath(config, `/credentials/${id}/rotate`), {
            method: 'POST',
            body: JSON.stringify({ secrets }),
          });
        },
        async revoke(id: string) {
          return http(config, orgPath(config, `/credentials/${id}/revoke`), {
            method: 'POST',
            body: JSON.stringify({}),
          });
        },
        async remove(id: string) {
          return http(config, orgPath(config, `/credentials/${id}`), { method: 'DELETE' });
        },
      },
      webhooks: {
        async list(params?: { connection_id?: string }) {
          const qs = params?.connection_id ? `?connection_id=${params.connection_id}` : '';
          return http(config, orgPath(config, `/connector-webhooks${qs}`));
        },
        async create(input: { connection_id: string; endpoint: string; event_types?: string[] }) {
          return http(
            config,
            orgPath(config, `/connector-webhooks?connection_id=${input.connection_id}`),
            { method: 'POST', body: JSON.stringify({ endpoint: input.endpoint, event_types: input.event_types ?? [] }) },
          );
        },
        async rotate(id: string) {
          return http(config, orgPath(config, `/connector-webhooks/${id}/rotate`), {
            method: 'POST',
            body: JSON.stringify({}),
          });
        },
        async remove(id: string) {
          return http(config, orgPath(config, `/connector-webhooks/${id}`), { method: 'DELETE' });
        },
      },
    },
    packages: {
      // Reusable packages / templates: full discover -> install -> update -> rollback flow.
      async list(params?: Record<string, string | number | boolean>) {
        const qs = new URLSearchParams(
          Object.entries(params ?? {}).reduce<Record<string, string>>((acc, [k, v]) => {
            if (v !== undefined) acc[k] = String(v);
            return acc;
          }, {}),
        ).toString();
        return http(config, orgPath(config, `/packages${qs ? `?${qs}` : ''}`));
      },
      async get(id: string) {
        return http(config, orgPath(config, `/packages/${id}`));
      },
      async create(input: unknown, opts?: RequestOptions) {
        return http(config, orgPath(config, '/packages'), {
          method: 'POST',
          body: JSON.stringify(input),
          ...opts,
        });
      },
      async createVersion(id: string, input: { version: string; manifest: unknown; changelog?: string }) {
        return http(config, orgPath(config, `/packages/${id}/versions`), {
          method: 'POST',
          body: JSON.stringify(input),
        });
      },
      async validate(id: string, version: string) {
        return http(config, orgPath(config, `/packages/${id}/versions/${version}/validate`), {
          method: 'POST',
          body: JSON.stringify({}),
        });
      },
      async publish(id: string, version: string) {
        return http(config, orgPath(config, `/packages/${id}/versions/${version}/publish`), {
          method: 'POST',
          body: JSON.stringify({}),
        });
      },
      async revoke(id: string, version: string, reason: string) {
        return http(config, orgPath(config, `/packages/${id}/versions/${version}/revoke`), {
          method: 'POST',
          body: JSON.stringify({ reason }),
        });
      },
      async diff(id: string, v1: string, v2: string) {
        return http(config, orgPath(config, `/packages/${id}/versions/${v1}/diff/${v2}`));
      },
      async security(id: string, version: string) {
        return http(config, orgPath(config, `/packages/${id}/versions/${version}/security`));
      },
      async preview(id: string, version: string, values: Record<string, unknown> = {}) {
        return http(config, orgPath(config, `/packages/${id}/versions/${version}/install-preview`), {
          method: 'POST',
          body: JSON.stringify({ values }),
        });
      },
      async install(
        id: string,
        version: string,
        input: { values?: Record<string, unknown>; idempotency_key?: string } = {},
        opts?: RequestOptions,
      ) {
        return http(config, orgPath(config, `/packages/${id}/versions/${version}/install`), {
          method: 'POST',
          body: JSON.stringify({ values: input.values ?? {}, idempotency_key: input.idempotency_key ?? '' }),
          idempotencyKey: opts?.idempotencyKey ?? input.idempotency_key,
        });
      },
      async fork(id: string, input: { slug: string; name: string }) {
        return http(config, orgPath(config, `/packages/${id}/fork`), {
          method: 'POST',
          body: JSON.stringify(input),
        });
      },
      async exportBundle(id: string, version: string) {
        return http(config, orgPath(config, `/packages/${id}/versions/${version}/export`), {
          method: 'POST',
          body: JSON.stringify({}),
        });
      },
      async importBundle(input: { files: Record<string, string>; slug?: string; visibility?: string }) {
        return http(config, orgPath(config, '/packages/import'), {
          method: 'POST',
          body: JSON.stringify(input),
        });
      },
      skills: {
        async list(params?: Record<string, string | number | boolean>) {
          const qs = new URLSearchParams(
            Object.entries(params ?? {}).reduce<Record<string, string>>((acc, [k, v]) => {
              if (v !== undefined) acc[k] = String(v);
              return acc;
            }, {}),
          ).toString();
          return http(config, orgPath(config, `/skills${qs ? `?${qs}` : ''}`));
        },
        async get(id: string) {
          return http(config, orgPath(config, `/skills/${id}`));
        },
        async create(input: unknown, opts?: RequestOptions) {
          return http(config, orgPath(config, '/skills'), {
            method: 'POST',
            body: JSON.stringify(input),
            ...opts,
          });
        },
        async attach(skillId: string, target_type: 'agent' | 'workflow', target_id: string) {
          return http(config, orgPath(config, `/skills/${skillId}/attach`), {
            method: 'POST',
            body: JSON.stringify({ target_type, target_id }),
          });
        },
      },
      presets: {
        async list(params?: Record<string, string>) {
          const qs = new URLSearchParams(params ?? {}).toString();
          return http(config, orgPath(config, `/presets${qs ? `?${qs}` : ''}`));
        },
        async get(id: string) {
          return http(config, orgPath(config, `/presets/${id}`));
        },
        async create(input: unknown, opts?: RequestOptions) {
          return http(config, orgPath(config, '/presets'), {
            method: 'POST',
            body: JSON.stringify(input),
            ...opts,
          });
        },
      },
      catalog: {
        async search(params?: Record<string, string | number | boolean>) {
          const qs = new URLSearchParams(
            Object.entries(params ?? {}).reduce<Record<string, string>>((acc, [k, v]) => {
              if (v !== undefined) acc[k] = String(v);
              return acc;
            }, {}),
          ).toString();
          return http(config, orgPath(config, `/catalog/search${qs ? `?${qs}` : ''}`));
        },
        async categories() {
          return http(config, orgPath(config, '/catalog/categories'));
        },
      },
      installations: {
        async list(params?: Record<string, string | number | boolean>) {
          const qs = new URLSearchParams(
            Object.entries(params ?? {}).reduce<Record<string, string>>((acc, [k, v]) => {
              if (v !== undefined) acc[k] = String(v);
              return acc;
            }, {}),
          ).toString();
          return http(config, orgPath(config, `/installations${qs ? `?${qs}` : ''}`));
        },
        async get(id: string) {
          return http(config, orgPath(config, `/installations/${id}`));
        },
        async planUpdate(id: string, to_version: string) {
          return http(config, orgPath(config, `/installations/${id}/update-plan`), {
            method: 'POST',
            body: JSON.stringify({ to_version }),
          });
        },
        async applyUpdate(id: string) {
          return http(config, orgPath(config, `/installations/${id}/update`), {
            method: 'POST',
            body: JSON.stringify({}),
          });
        },
        async rollback(id: string) {
          return http(config, orgPath(config, `/installations/${id}/rollback`), {
            method: 'POST',
            body: JSON.stringify({}),
          });
        },
        async uninstall(id: string) {
          return http(config, orgPath(config, `/installations/${id}`), { method: 'DELETE' });
        },
      },
    },
    marketplace: {
      async search(params?: Record<string, string | number | boolean>) {
        const qs = new URLSearchParams(
          Object.entries(params ?? {}).reduce<Record<string, string>>((acc, [k, v]) => {
            if (v !== undefined) acc[k] = String(v);
            return acc;
          }, {}),
        ).toString();
        return http(config, `/api/v1/marketplace/search${qs ? `?${qs}` : ''}`);
      },
      async categories(marketplace?: string) {
        const qs = marketplace ? `?marketplace=${encodeURIComponent(marketplace)}` : '';
        return http(config, `/api/v1/marketplace/categories${qs}`);
      },
      async featured() {
        return http(config, `/api/v1/marketplace/featured`);
      },
      async get(slug: string) {
        return http(config, `/api/v1/marketplace/${encodeURIComponent(slug)}`);
      },
      async related(slug: string, limit = 8) {
        return http(config, `/api/v1/marketplace/${encodeURIComponent(slug)}/related?limit=${limit}`);
      },
      async install(
        listingId: string,
        input: { version?: string; values?: Record<string, unknown>; idempotency_key?: string } = {},
        opts?: RequestOptions,
      ) {
        return http(config, orgPath(config, `/listings/${listingId}/install`), {
          method: 'POST',
          body: JSON.stringify({
            version: input.version ?? '',
            values: input.values ?? {},
            idempotency_key: input.idempotency_key ?? '',
          }),
          idempotencyKey: opts?.idempotencyKey ?? input.idempotency_key,
        });
      },
    },
    publishers: {
      async list(params?: { q?: string; verification?: string }) {
        const qs = new URLSearchParams(
          Object.entries(params ?? {}).reduce<Record<string, string>>((acc, [k, v]) => {
            if (v !== undefined) acc[k] = String(v);
            return acc;
          }, {}),
        ).toString();
        return http(config, `/api/v1/publishers${qs ? `?${qs}` : ''}`);
      },
      async get(slug: string) {
        return http(config, `/api/v1/publishers/${encodeURIComponent(slug)}`);
      },
      async create(input: unknown, opts?: RequestOptions) {
        return http(config, `/api/v1/publishers`, {
          method: 'POST',
          body: JSON.stringify(input),
          ...opts,
        });
      },
      async follow(slug: string) {
        return http(config, `/api/v1/publishers/${encodeURIComponent(slug)}/follow`, {
          method: 'POST',
          body: JSON.stringify({}),
        });
      },
      async unfollow(slug: string) {
        return http(config, `/api/v1/publishers/${encodeURIComponent(slug)}/follow`, {
          method: 'DELETE',
        });
      },
      async analytics(slug: string, days = 30) {
        return http(config, `/api/v1/publishers/${encodeURIComponent(slug)}/analytics?days=${days}`);
      },
    },
    listings: {
      async list(params?: Record<string, string | number | boolean>) {
        const qs = new URLSearchParams(
          Object.entries(params ?? {}).reduce<Record<string, string>>((acc, [k, v]) => {
            if (v !== undefined) acc[k] = String(v);
            return acc;
          }, {}),
        ).toString();
        return http(config, orgPath(config, `/listings${qs ? `?${qs}` : ''}`));
      },
      async get(id: string) {
        return http(config, orgPath(config, `/listings/${id}`));
      },
      async create(input: unknown, opts?: RequestOptions) {
        return http(config, orgPath(config, '/listings'), {
          method: 'POST',
          body: JSON.stringify(input),
          ...opts,
        });
      },
      async submit(id: string) {
        return http(config, orgPath(config, `/listings/${id}/submit`), {
          method: 'POST',
          body: JSON.stringify({}),
        });
      },
      async publish(id: string) {
        return http(config, orgPath(config, `/listings/${id}/publish`), {
          method: 'POST',
          body: JSON.stringify({}),
        });
      },
      async health(id: string) {
        return http(config, orgPath(config, `/listings/${id}/health`));
      },
      async security(id: string) {
        return http(config, orgPath(config, `/listings/${id}/security`));
      },
    },
    reviews: {
      async list(listingId: string, params?: { status?: string; page?: number; page_size?: number }) {
        const qs = new URLSearchParams(
          Object.entries({ listing_id: listingId, ...(params ?? {}) }).reduce<Record<string, string>>(
            (acc, [k, v]) => {
              if (v !== undefined) acc[k] = String(v);
              return acc;
            },
            {},
          ),
        ).toString();
        return http(config, `/api/v1/reviews?${qs}`);
      },
      async create(input: unknown, opts?: RequestOptions) {
        return http(config, `/api/v1/reviews`, {
          method: 'POST',
          body: JSON.stringify(input),
          ...opts,
        });
      },
      async report(id: string, input: { reason: string; details?: string }) {
        return http(config, `/api/v1/reviews/${id}/report`, {
          method: 'POST',
          body: JSON.stringify(input),
        });
      },
    },
    distribution: {
      async artifacts(versionId: string) {
        return http(
          config,
          orgPath(config, `/distribution/artifacts?version_id=${encodeURIComponent(versionId)}`),
        );
      },
    },
    advisories: {
      async list(params?: { status?: string; severity?: string }) {
        const qs = new URLSearchParams(
          Object.entries(params ?? {}).reduce<Record<string, string>>((acc, [k, v]) => {
            if (v !== undefined) acc[k] = String(v);
            return acc;
          }, {}),
        ).toString();
        return http(config, `/api/v1/security-advisories${qs ? `?${qs}` : ''}`);
      },
      async get(id: string) {
        return http(config, `/api/v1/security-advisories/${id}`);
      },
    },
    // Commerce: registries, billing, entitlements, usage, revenue, payouts.
    // Provider-specific behavior stays server-side behind these interfaces.
    registries: {
      async list() {
        return http(config, '/api/v1/registries');
      },
      async create(input: {
        slug: string;
        name: string;
        registry_type?: string;
        endpoint?: string;
        visibility?: string;
        trust_level?: string;
        auth_type?: string;
        credential_ref?: string;
        signature_policy?: Record<string, unknown>;
        mirror_of?: string;
      }) {
        return http(config, '/api/v1/registries', {
          method: 'POST',
          body: JSON.stringify(input),
        });
      },
      async test(id: string) {
        return http(config, `/api/v1/registries/${id}/test`, {
          method: 'POST',
          body: JSON.stringify({}),
        });
      },
      async sync(id: string) {
        return http(config, `/api/v1/registries/${id}/sync`, {
          method: 'POST',
          body: JSON.stringify({}),
        });
      },
      async remove(id: string) {
        return http(config, `/api/v1/registries/${id}`, { method: 'DELETE' });
      },
    },
    billing: {
      async status() {
        return http(config, '/api/v1/billing/status');
      },
      async portal() {
        return http(config, '/api/v1/billing/portal', {
          method: 'POST',
          body: JSON.stringify({}),
        });
      },
    },
    products: {
      async list(params?: { product_type?: string; page?: number; page_size?: number }) {
        const qs = new URLSearchParams(
          Object.entries(params ?? {}).reduce<Record<string, string>>((acc, [k, v]) => {
            if (v !== undefined) acc[k] = String(v);
            return acc;
          }, {}),
        ).toString();
        return http(config, `/api/v1/products${qs ? `?${qs}` : ''}`);
      },
      async create(input: unknown, opts?: RequestOptions) {
        return http(config, '/api/v1/products', {
          method: 'POST',
          body: JSON.stringify(input),
          ...opts,
        });
      },
      async activate(id: string) {
        return http(config, `/api/v1/products/${id}/activate`, {
          method: 'POST',
          body: JSON.stringify({}),
        });
      },
    },
    prices: {
      async list(productId?: string) {
        const qs = productId ? `?product_id=${encodeURIComponent(productId)}` : '';
        return http(config, `/api/v1/prices${qs}`);
      },
      async create(
        productId: string,
        input: { amount: string; currency?: string; pricing_model?: string; billing_interval?: string },
      ) {
        return http(config, `/api/v1/products/${productId}/prices`, {
          method: 'POST',
          body: JSON.stringify(input),
        });
      },
    },
    checkout: {
      async create(
        input: { product_id: string; price_id: string; idempotency_key?: string; promo_code?: string },
        opts?: RequestOptions,
      ) {
        return http(config, '/api/v1/checkout', {
          method: 'POST',
          body: JSON.stringify(input),
          idempotencyKey: opts?.idempotencyKey ?? input.idempotency_key,
        });
      },
      async get(id: string) {
        return http(config, `/api/v1/checkout/${id}`);
      },
    },
    subscriptions: {
      async list(params?: { status?: string; page?: number; page_size?: number }) {
        const qs = new URLSearchParams(
          Object.entries(params ?? {}).reduce<Record<string, string>>((acc, [k, v]) => {
            if (v !== undefined) acc[k] = String(v);
            return acc;
          }, {}),
        ).toString();
        return http(config, `/api/v1/subscriptions${qs ? `?${qs}` : ''}`);
      },
      async create(input: { customer_id: string; price_id: string; trial_days?: number }) {
        return http(config, '/api/v1/subscriptions', {
          method: 'POST',
          body: JSON.stringify(input),
        });
      },
      async cancel(id: string, atPeriodEnd = true) {
        return http(config, `/api/v1/subscriptions/${id}/cancel?at_period_end=${atPeriodEnd}`, {
          method: 'POST',
          body: JSON.stringify({}),
        });
      },
    },
    entitlements: {
      async list(productId?: string) {
        const qs = productId ? `?product_id=${encodeURIComponent(productId)}` : '';
        return http(config, `/api/v1/entitlements${qs}`);
      },
      async check(feature = 'package.install') {
        return http(config, `/api/v1/entitlements/check?feature=${encodeURIComponent(feature)}`);
      },
      async revoke(id: string, reason = '') {
        return http(config, `/api/v1/entitlements/${id}/revoke${reason ? `?reason=${encodeURIComponent(reason)}` : ''}`, {
          method: 'POST',
          body: JSON.stringify({}),
        });
      },
    },
    usage: {
      async meters() {
        return http(config, '/api/v1/usage/meters');
      },
      async record(input: { meter: string; quantity?: number; feature?: string; idempotency_key?: string }) {
        return http(config, '/api/v1/usage', {
          method: 'POST',
          body: JSON.stringify(input),
        });
      },
      async summary(meter: string, periodStart: string, periodEnd: string) {
        const qs = new URLSearchParams({ meter, period_start: periodStart, period_end: periodEnd }).toString();
        return http(config, `/api/v1/usage/summary?${qs}`);
      },
    },
    quotas: {
      async list() {
        return http(config, '/api/v1/quotas');
      },
      async check(id: string, quantity = 1) {
        return http(config, `/api/v1/quotas/${id}/check?quantity=${quantity}`);
      },
      async consume(id: string, quantity = 1) {
        return http(config, `/api/v1/quotas/${id}/consume?quantity=${quantity}`, {
          method: 'POST',
          body: JSON.stringify({}),
        });
      },
    },
    invoices: {
      async list(params?: { page?: number; page_size?: number }) {
        const qs = new URLSearchParams(
          Object.entries(params ?? {}).reduce<Record<string, string>>((acc, [k, v]) => {
            if (v !== undefined) acc[k] = String(v);
            return acc;
          }, {}),
        ).toString();
        return http(config, `/api/v1/invoices${qs ? `?${qs}` : ''}`);
      },
      async get(id: string) {
        return http(config, `/api/v1/invoices/${id}`);
      },
      async pay(id: string, paymentReference: string) {
        const qs = new URLSearchParams({ payment_reference: paymentReference }).toString();
        return http(config, `/api/v1/invoices/${id}/pay?${qs}`, {
          method: 'POST',
          body: JSON.stringify({}),
        });
      },
    },
    revenue: {
      async publisher(publisherId: string) {
        return http(config, `/api/v1/revenue?publisher_id=${encodeURIComponent(publisherId)}`);
      },
      async ledger(publisherId: string) {
        return http(config, `/api/v1/revenue/ledger?publisher_id=${encodeURIComponent(publisherId)}`);
      },
    },
    payouts: {
      async list(publisherId?: string) {
        const qs = publisherId ? `?publisher_id=${encodeURIComponent(publisherId)}` : '';
        return http(config, `/api/v1/payouts${qs}`);
      },
      async request(input: {
        publisher_id: string;
        amount: string;
        currency?: string;
        destination_reference: string;
        idempotency_key?: string;
      }) {
        return http(config, '/api/v1/payouts', {
          method: 'POST',
          body: JSON.stringify(input),
        });
      },
      async transition(id: string, target: string, reason = '') {
        const qs = new URLSearchParams({ target, ...(reason ? { reason } : {}) }).toString();
        return http(config, `/api/v1/payouts/${id}/transition?${qs}`, {
          method: 'POST',
          body: JSON.stringify({}),
        });
      },
    },
    // MP25: cloud runtime (hosted execution, artifacts). Backward compatible.
    executions: {
      async create(input: Record<string, unknown>, opts?: RequestOptions) {
        return http(config, '/api/v1/cloud/executions', {
          method: 'POST',
          body: JSON.stringify(input),
          ...opts,
        });
      },
      async get(id: string) {
        return http(config, `/api/v1/cloud/executions/${encodeURIComponent(id)}`);
      },
      async cancel(id: string) {
        return http(config, `/api/v1/cloud/executions/${encodeURIComponent(id)}/cancel`, {
          method: 'POST',
          body: JSON.stringify({}),
        });
      },
      async retry(id: string) {
        return http(config, `/api/v1/cloud/executions/${encodeURIComponent(id)}/retry`, {
          method: 'POST',
          body: JSON.stringify({}),
        });
      },
      async events(id: string, fromSequence = 0) {
        return http(config, `/api/v1/cloud/executions/${encodeURIComponent(id)}/events?from_sequence=${fromSequence}`);
      },
      async stream(id: string, fromSequence = 0): Promise<ReadableStream<Uint8Array> | null> {
        const res = await fetch(
          `${baseUrlOf(config)}/api/v1/cloud/executions/${encodeURIComponent(id)}/stream?from_sequence=${fromSequence}`,
          {
            headers: {
              ...(config.apiKey ? { Authorization: `Bearer ${config.apiKey}` } : {}),
              ...(config.organizationId ? { 'X-Organization-ID': config.organizationId } : {}),
            },
          },
        );
        if (!res.ok || !res.body) throw new Error(`SDK stream failed (${res.status})`);
        return res.body;
      },
    },
    artifacts: {
      async list(params?: { execution_id?: string }) {
        const qs = params?.execution_id ? `?execution_id=${encodeURIComponent(params.execution_id)}` : '';
        return http(config, `/api/v1/cloud/files${qs}`);
      },
      async download(id: string) {
        return http(config, `/api/v1/cloud/files/${encodeURIComponent(id)}`);
      },
      async share(id: string, expiresSeconds = 3600) {
        return http(config, `/api/v1/cloud/files/${encodeURIComponent(id)}/share`, {
          method: 'POST',
          body: JSON.stringify({ expires_seconds: expiresSeconds }),
        });
      },
      async remove(id: string) {
        return http(config, `/api/v1/cloud/files/${encodeURIComponent(id)}`, { method: 'DELETE' });
      },
    },
    cloud: {
      async workers(params?: { region?: string; pool?: string }) {
        const qs = new URLSearchParams(
          Object.entries(params ?? {}).reduce<Record<string, string>>((acc, [k, v]) => {
            if (v !== undefined) acc[k] = String(v);
            return acc;
          }, {}),
        ).toString();
        return http(config, `/api/v1/cloud/workers${qs ? `?${qs}` : ''}`);
      },
      async queues() {
        return http(config, '/api/v1/cloud/queues');
      },
      async regions() {
        return http(config, '/api/v1/cloud/regions');
      },
      async storage() {
        return http(config, '/api/v1/cloud/storage');
      },
      async usage() {
        return http(config, '/api/v1/cloud/usage');
      },
      async health() {
        return http(config, '/api/v1/cloud/health');
      },
    },
    // MP26: operations + platform control (stable, versioned).
    operations: {
      async health() {
        return http(config, '/api/v1/operations/health');
      },
      async metrics() {
        return http(config, '/api/v1/operations/metrics');
      },
      async alerts(params?: { status?: string; severity?: string }) {
        const qs = new URLSearchParams(
          Object.entries(params ?? {}).reduce<Record<string, string>>((acc, [k, v]) => {
            if (v !== undefined) acc[k] = String(v);
            return acc;
          }, {}),
        ).toString();
        return http(config, `/api/v1/operations/alerts${qs ? `?${qs}` : ''}`);
      },
      async incidents(params?: { status?: string }) {
        const qs = params?.status ? `?status=${encodeURIComponent(params.status)}` : '';
        return http(config, `/api/v1/operations/incidents${qs}`);
      },
      async audit(params?: { action?: string; resource?: string }) {
        const qs = new URLSearchParams(
          Object.entries(params ?? {}).reduce<Record<string, string>>((acc, [k, v]) => {
            if (v !== undefined) acc[k] = String(v);
            return acc;
          }, {}),
        ).toString();
        return http(config, `/api/v1/operations/audit${qs ? `?${qs}` : ''}`);
      },
      async deployments() {
        return http(config, '/api/v1/operations/deployments');
      },
      async diagnostics() {
        return http(config, '/api/v1/operations/diagnostics');
      },
      async featureFlags() {
        return http(config, '/api/v1/master/control/flags');
      },
    },
    // MP27: enterprise security (SSO/SCIM/policies/devices/sessions/controls).
    security: {
      async sso() {
        return http(config, '/api/v1/enterprise/sso');
      },
      async scimCredentials() {
        return http(config, '/api/v1/enterprise/scim/credentials');
      },
      async policies() {
        return http(config, '/api/v1/enterprise/policies');
      },
      async simulatePolicy(body: Record<string, unknown>) {
        return http(config, '/api/v1/enterprise/policies/simulate', {
          method: 'POST',
          body: JSON.stringify(body),
        });
      },
      async devices() {
        return http(config, '/api/v1/enterprise/devices');
      },
      async sessions() {
        return http(config, '/api/v1/enterprise/sessions/risk');
      },
      async controls() {
        return http(config, '/api/v1/enterprise/controls');
      },
      async audit(params?: { method?: string }) {
        const qs = params?.method ? `?method=${encodeURIComponent(params.method)}` : '';
        return http(config, `/api/v1/enterprise/audit${qs}`);
      },
      async posture() {
        return http(config, '/api/v1/enterprise/posture');
      },
    },
  };
}

function optsSafe(): Record<string, never> {
  return {};
}

// ---------------------------------------------------------------------------
// MP28: OpenAgent class + full resource surface (§6).
//
//   import { OpenAgent } from "@openagent/sdk";
//   const client = new OpenAgent({ apiKey: process.env.OPENAGENT_API_KEY });
//   const agent = await client.agents.create({ name: "Research Agent", ... });
//
// Idiomatic, strongly typed, and transport-agnostic: no HTTP internals leak.
// `createSDK()` above remains available for backward compatibility.
// ---------------------------------------------------------------------------

export interface PaginationParams {
  page?: number;
  page_size?: number;
  cursor?: string;
  [k: string]: string | number | boolean | undefined;
}

export interface Paginated<T> {
  items: T[];
  page: number;
  page_size: number;
  total: number;
  has_more: boolean;
}

function qs(params?: { [k: string]: string | number | boolean | undefined }): string {
  const out = new URLSearchParams();
  for (const [k, v] of Object.entries(params ?? {})) {
    if (v !== undefined) out.set(k, String(v));
  }
  const s = out.toString();
  return s ? `?${s}` : '';
}

export class OpenAgent {
  readonly config: SDKConfig;

  constructor(config: OpenAgentConfig & { apiUrl?: string }) {
    const apiUrl = config.apiUrl ?? config.baseUrl ?? process.env.OPENAGENT_API_URL ?? 'http://localhost:8000';
    const apiKey = config.apiKey ?? process.env.OPENAGENT_API_KEY;
    // Never store or expose secrets beyond the in-memory config: no logging here.
    this.config = {
      apiUrl,
      apiKey,
      organizationId: config.organizationId ?? process.env.OPENAGENT_ORG_ID,
      timeoutMs: config.timeoutMs,
      maxRetries: config.maxRetries,
    };
    // All namespaces below close over `config` so `this` is never lost.
    const cfg = this.config;
    const org = (suffix: string): string => orgPath(cfg, suffix);

    this.agents = {
      async list(params?: PaginationParams) { return http(cfg, org(`/agents${qs(params)}`)); },
      async create(input: { name: string; description?: string; model?: string; instructions?: string; [k: string]: unknown }, opts?: RequestOptions) {
        return http(cfg, org('/agents'), { method: 'POST', body: JSON.stringify(input), ...opts });
      },
      async get(id: string) { return http(cfg, org(`/agents/${id}`)); },
      async update(id: string, input: unknown) {
        return http(cfg, org(`/agents/${id}`), { method: 'PATCH', body: JSON.stringify(input) });
      },
      async remove(id: string) { return http(cfg, org(`/agents/${id}`), { method: 'DELETE' }); },
      async *iterate(params?: PaginationParams): AsyncGenerator<unknown> {
        yield* paginate<unknown>((p) => http(cfg, org(`/agents${qs({ ...params, ...p })}`)));
      },
    };

    this.agentRuns = {
      async list(params?: PaginationParams) { return http(cfg, org(`/runs${qs(params)}`)); },
      async get(id: string) { return http(cfg, org(`/runs/${id}`)); },
      async start(agentId: string, input?: unknown, opts?: RequestOptions) {
        return http(cfg, org('/runs'), { method: 'POST', body: JSON.stringify({ agent_id: agentId, input }), ...opts });
      },
      async cancel(id: string) {
        return http(cfg, org(`/runs/${id}/cancel`), { method: 'POST', body: JSON.stringify({}) });
      },
      events: (id: string, fromSequence = 0): AsyncGenerator<unknown> =>
        streamEvents(cfg, org(`/runs/${id}/events${qs({ from_sequence: fromSequence })}`)),
    };

    this.workflows = {
      async list(params?: PaginationParams) { return http(cfg, org(`/workflows${qs(params)}`)); },
      async create(input: unknown, opts?: RequestOptions) {
        return http(cfg, org('/workflows'), { method: 'POST', body: JSON.stringify(input), ...opts });
      },
      async get(id: string) { return http(cfg, org(`/workflows/${id}`)); },
      async validate(id: string, definition?: unknown) {
        return http(cfg, org(`/workflows/${id}/validate`), { method: 'POST', body: JSON.stringify(definition ?? {}) });
      },
      async deploy(id: string, opts?: RequestOptions) {
        return http(cfg, org(`/workflows/${id}/deploy`), { method: 'POST', body: JSON.stringify({}), ...opts });
      },
    };

    this.executions = {
      async list(params?: PaginationParams) { return http(cfg, org(`/executions${qs(params)}`)); },
      async get(id: string) { return http(cfg, org(`/executions/${id}`)); },
      async start(workflowId: string, input?: unknown, opts?: RequestOptions) {
        return http(cfg, org('/executions'), { method: 'POST', body: JSON.stringify({ workflow_id: workflowId, input }), ...opts });
      },
      async cancel(id: string) {
        return http(cfg, org(`/executions/${id}/cancel`), { method: 'POST', body: JSON.stringify({}) });
      },
      events: (id: string): AsyncGenerator<unknown> =>
        streamEvents(cfg, org(`/executions/${id}/events`)),
    };

    this.tools = {
      async list(params?: { search?: string; category?: string } & PaginationParams) {
        return http(cfg, org(`/tools${qs(params)}`));
      },
      async get(id: string) { return http(cfg, org(`/tools/${id}`)); },
      async execute(toolId: string, input?: unknown, opts?: RequestOptions & { approved?: boolean }) {
        return http(cfg, org('/tools/execute'), {
          method: 'POST',
          body: JSON.stringify({ tool_id: toolId, input, approved: opts?.approved }),
          ...opts,
        });
      },
    };

    const integrations = {
      async catalog(params?: { category?: string; trust?: string; search?: string }) {
        return http(cfg, org(`/connectors${qs(params)}`));
      },
      async connections(params?: { connector_id?: string; status?: string }) {
        return http(cfg, org(`/integration-connections${qs(params)}`));
      },
      async executeAction(connection: string, action: string, input?: unknown, opts?: RequestOptions) {
        return http(cfg, org(`/integration-connections/${connection}/execute`), {
          method: 'POST', body: JSON.stringify({ action_id: action, input: input ?? {} }), ...opts,
        });
      },
    };
    this.integrations = integrations;
    // Alias: connectors === integrations (§7: same surface, both languages).
    this.connectors = integrations;

    this.mcp = {
      async servers() { return http(cfg, org('/mcp/servers')); },
      async server(id: string) { return http(cfg, org(`/mcp/servers/${id}`)); },
      async tools(serverId: string) { return http(cfg, org(`/mcp/servers/${serverId}/tools`)); },
      async callTool(serverId: string, tool: string, args?: unknown, opts?: RequestOptions) {
        return http(cfg, org(`/mcp/servers/${serverId}/tools/call`), {
          method: 'POST', body: JSON.stringify({ tool, arguments: args ?? {} }), ...opts,
        });
      },
      async resources(serverId: string) { return http(cfg, org(`/mcp/servers/${serverId}/resources`)); },
      async prompts(serverId: string) { return http(cfg, org(`/mcp/servers/${serverId}/prompts`)); },
    };

    this.memory = {
      async list(params?: PaginationParams) { return http(cfg, org(`/memory${qs(params)}`)); },
      async create(input: { key?: string; value?: unknown; scope?: string }, opts?: RequestOptions) {
        return http(cfg, org('/memory'), { method: 'POST', body: JSON.stringify(input), ...opts });
      },
      async search(query: string, topK = 10) {
        return http(cfg, org('/memory/search'), { method: 'POST', body: JSON.stringify({ query, top_k: topK }) });
      },
      async remove(id: string) { return http(cfg, org(`/memory/${id}`), { method: 'DELETE' }); },
    };

    this.models = {
      async list() { return http(cfg, '/api/v1/models'); },
      async providers() { return http(cfg, '/api/v1/model-providers'); },
      async route(input: { task?: string; preferences?: unknown }) {
        return http(cfg, org('/models/route'), { method: 'POST', body: JSON.stringify(input) });
      },
    };

    this.evaluations = {
      async evaluate(input: Record<string, unknown>, opts?: RequestOptions) {
        return http(cfg, org('/evaluations'), { method: 'POST', body: JSON.stringify(input), ...opts });
      },
      async list(params?: PaginationParams) { return http(cfg, org(`/evaluations${qs(params)}`)); },
      async get(id: string) { return http(cfg, org(`/evaluations/${id}`)); },
      async decide(id: string, input?: unknown) {
        return http(cfg, org(`/evaluations/${id}/finalize`), { method: 'POST', body: JSON.stringify(input ?? {}) });
      },
    };

    this.sandboxes = {
      async create(input?: Record<string, unknown>) {
        return http(cfg, '/api/v1/sandboxes', { method: 'POST', body: JSON.stringify(input ?? { profile: 'TEST' }) });
      },
      async list() { return http(cfg, '/api/v1/sandboxes'); },
      async get(id: string) { return http(cfg, `/api/v1/sandboxes/${id}`); },
      async execute(id: string, input: Record<string, unknown>) {
        return http(cfg, `/api/v1/sandboxes/${id}/execute`, { method: 'POST', body: JSON.stringify(input) });
      },
      async destroy(id: string) { return http(cfg, `/api/v1/sandboxes/${id}`, { method: 'DELETE' }); },
    };

    this.approvals = {
      async list(params?: { status?: string }) { return http(cfg, org(`/approvals${qs(params)}`)); },
      async get(id: string) { return http(cfg, org(`/approvals/${id}`)); },
      async approve(id: string, reason?: string, opts?: RequestOptions) {
        return http(cfg, org(`/approvals/${id}/approve`), {
          method: 'POST', body: JSON.stringify({ reason: reason ?? '' }), ...opts,
        });
      },
      async reject(id: string, reason?: string, opts?: RequestOptions) {
        return http(cfg, org(`/approvals/${id}/reject`), {
          method: 'POST', body: JSON.stringify({ reason: reason ?? '' }), ...opts,
        });
      },
    };

    this.marketplace = {
      async search(params?: Record<string, string | number | boolean>) {
        return http(cfg, `/api/v1/marketplace/search${qs(params)}`);
      },
      async get(slug: string) { return http(cfg, `/api/v1/marketplace/${encodeURIComponent(slug)}`); },
      async publish(input: unknown, opts?: RequestOptions) {
        return http(cfg, org('/listings'), { method: 'POST', body: JSON.stringify(input), ...opts });
      },
    };

    this.registry = {
      async list() { return http(cfg, '/api/v1/registries'); },
      async search(query: string) { return http(cfg, org(`/catalog/search${qs({ q: query })}`)); },
      async install(packageId: string, version: string, values?: Record<string, unknown>, opts?: RequestOptions) {
        return http(cfg, org(`/packages/${packageId}/versions/${version}/install`), {
          method: 'POST', body: JSON.stringify({ values: values ?? {} }), ...opts,
        });
      },
      async publish(packageId: string, version: string) {
        return http(cfg, org(`/packages/${packageId}/versions/${version}/publish`), {
          method: 'POST', body: JSON.stringify({}) });
      },
      async local() { return http(cfg, '/api/v1/registry/local/packages'); },
    };

    this.projects = {
      async list() { return http(cfg, org('/developer/projects')); },
      async create(input: { slug: string; name: string; description?: string }, opts?: RequestOptions) {
        return http(cfg, org('/developer/projects'), { method: 'POST', body: JSON.stringify(input), ...opts });
      },
      async get(id: string) { return http(cfg, org(`/developer/projects/${id}`)); },
      async updateEnvironment(projectId: string, env: string, input: { api_endpoint?: string; config?: Record<string, unknown> }) {
        return http(cfg, org(`/developer/projects/${projectId}/environments/${env}`), {
          method: 'PUT', body: JSON.stringify(input),
        });
      },
    };

    this.deployments = {
      async list() { return http(cfg, org('/developer/deployments')); },
      async deploy(extensionId: string, input: { version: string; environment?: string }) {
        return http(cfg, org(`/extensions/${extensionId}/deploy`), {
          method: 'POST', body: JSON.stringify({ environment: 'staging', ...input }),
        });
      },
      async rollback(extensionId: string, installationId: string) {
        return http(cfg, org(`/extensions/${extensionId}/rollback?installation_id=${installationId}`), {
          method: 'POST', body: JSON.stringify({}) });
      },
    };

    this.events = {
      async schemas() { return http(cfg, org('/developer/events')); },
      subscribe: (runOrExecution: { kind: 'run' | 'execution'; id: string }): AsyncGenerator<unknown> =>
        streamEvents(cfg, org(
          runOrExecution.kind === 'run'
            ? `/runs/${runOrExecution.id}/events`
            : `/executions/${runOrExecution.id}/events`,
        )),
    };

    this.webhooks = {
      async list() { return http(cfg, org('/developer/webhooks')); },
      async create(input: { url: string; events?: string[]; project_id?: string }) {
        return http(cfg, org('/developer/webhooks'), { method: 'POST', body: JSON.stringify(input) });
      },
    };

    this.extensions = {
      async list(params?: { extension_type?: string; lifecycle?: string }) {
        return http(cfg, org(`/extensions${qs(params)}`));
      },
      async create(input: Record<string, unknown>, opts?: RequestOptions) {
        return http(cfg, org('/extensions'), { method: 'POST', body: JSON.stringify(input), ...opts });
      },
      async get(id: string) { return http(cfg, org(`/extensions/${id}`)); },
      async createVersion(id: string, input: { version: string; manifest: unknown; changelog?: string }) {
        return http(cfg, org(`/extensions/${id}/versions`), { method: 'POST', body: JSON.stringify(input) });
      },
      async validate(id: string, files?: Record<string, string>) {
        return http(cfg, org(`/extensions/${id}/validate`), {
          method: 'POST', body: JSON.stringify({ files: files ?? {} }) });
      },
      async test(id: string, files?: Record<string, string>) {
        return http(cfg, org(`/extensions/${id}/test`), {
          method: 'POST', body: JSON.stringify({ files: files ?? {} }) });
      },
      async package(id: string, files?: Record<string, string>) {
        return http(cfg, org(`/extensions/${id}/package`), {
          method: 'POST', body: JSON.stringify({ files: files ?? {} }) });
      },
      async publish(id: string, files?: Record<string, string>) {
        return http(cfg, org(`/extensions/${id}/publish`), {
          method: 'POST', body: JSON.stringify({ files: files ?? {} }) });
      },
      async install(id: string, input: { version: string; environment?: string; granted_permissions?: string[]; config_values?: Record<string, unknown> }) {
        return http(cfg, org(`/extensions/${id}/install`), { method: 'POST', body: JSON.stringify(input) });
      },
      async quarantine(id: string, reason: string) {
        return http(cfg, org(`/extensions/${id}/quarantine`), { method: 'POST', body: JSON.stringify({ reason }) });
      },
      async disable(id: string) {
        return http(cfg, org(`/extensions/${id}/disable`), { method: 'POST', body: JSON.stringify({}) });
      },
    };
  }

  agents: {
    list(params?: PaginationParams): Promise<unknown>;
    create(input: Record<string, unknown>, opts?: RequestOptions): Promise<unknown>;
    get(id: string): Promise<unknown>;
    update(id: string, input: unknown): Promise<unknown>;
    remove(id: string): Promise<unknown>;
    iterate(params?: PaginationParams): AsyncGenerator<unknown>;
  };
  agentRuns: {
    list(params?: PaginationParams): Promise<unknown>;
    get(id: string): Promise<unknown>;
    start(agentId: string, input?: unknown, opts?: RequestOptions): Promise<unknown>;
    cancel(id: string): Promise<unknown>;
    events(id: string, fromSequence?: number): AsyncGenerator<unknown>;
  };
  workflows: {
    list(params?: PaginationParams): Promise<unknown>;
    create(input: unknown, opts?: RequestOptions): Promise<unknown>;
    get(id: string): Promise<unknown>;
    validate(id: string, definition?: unknown): Promise<unknown>;
    deploy(id: string, opts?: RequestOptions): Promise<unknown>;
  };
  executions: {
    list(params?: PaginationParams): Promise<unknown>;
    get(id: string): Promise<unknown>;
    start(workflowId: string, input?: unknown, opts?: RequestOptions): Promise<unknown>;
    cancel(id: string): Promise<unknown>;
    events(id: string): AsyncGenerator<unknown>;
  };
  tools: {
    list(params?: Record<string, string | number | boolean | undefined>): Promise<unknown>;
    get(id: string): Promise<unknown>;
    execute(toolId: string, input?: unknown, opts?: RequestOptions & { approved?: boolean }): Promise<unknown>;
  };
  integrations: {
    catalog(params?: Record<string, string | undefined>): Promise<unknown>;
    connections(params?: Record<string, string | undefined>): Promise<unknown>;
    executeAction(connection: string, action: string, input?: unknown, opts?: RequestOptions): Promise<unknown>;
  };
  connectors: OpenAgent['integrations'];
  mcp: {
    servers(): Promise<unknown>;
    server(id: string): Promise<unknown>;
    tools(serverId: string): Promise<unknown>;
    callTool(serverId: string, tool: string, args?: unknown, opts?: RequestOptions): Promise<unknown>;
    resources(serverId: string): Promise<unknown>;
    prompts(serverId: string): Promise<unknown>;
  };
  memory: {
    list(params?: PaginationParams): Promise<unknown>;
    create(input: Record<string, unknown>, opts?: RequestOptions): Promise<unknown>;
    search(query: string, topK?: number): Promise<unknown>;
    remove(id: string): Promise<unknown>;
  };
  models: {
    list(): Promise<unknown>;
    providers(): Promise<unknown>;
    route(input: Record<string, unknown>): Promise<unknown>;
  };
  evaluations: {
    evaluate(input: Record<string, unknown>, opts?: RequestOptions): Promise<unknown>;
    list(params?: PaginationParams): Promise<unknown>;
    get(id: string): Promise<unknown>;
    decide(id: string, input?: unknown): Promise<unknown>;
  };
  sandboxes: {
    create(input?: Record<string, unknown>): Promise<unknown>;
    list(): Promise<unknown>;
    get(id: string): Promise<unknown>;
    execute(id: string, input: Record<string, unknown>): Promise<unknown>;
    destroy(id: string): Promise<unknown>;
  };
  approvals: {
    list(params?: { status?: string }): Promise<unknown>;
    get(id: string): Promise<unknown>;
    approve(id: string, reason?: string, opts?: RequestOptions): Promise<unknown>;
    reject(id: string, reason?: string, opts?: RequestOptions): Promise<unknown>;
  };
  marketplace: {
    search(params?: Record<string, string | number | boolean>): Promise<unknown>;
    get(slug: string): Promise<unknown>;
    publish(input: unknown, opts?: RequestOptions): Promise<unknown>;
  };
  registry: {
    list(): Promise<unknown>;
    search(query: string): Promise<unknown>;
    install(packageId: string, version: string, values?: Record<string, unknown>, opts?: RequestOptions): Promise<unknown>;
    publish(packageId: string, version: string): Promise<unknown>;
    local(): Promise<unknown>;
  };
  projects: {
    list(): Promise<unknown>;
    create(input: Record<string, unknown>, opts?: RequestOptions): Promise<unknown>;
    get(id: string): Promise<unknown>;
    updateEnvironment(projectId: string, env: string, input: Record<string, unknown>): Promise<unknown>;
  };
  deployments: {
    list(): Promise<unknown>;
    deploy(extensionId: string, input: Record<string, unknown>): Promise<unknown>;
    rollback(extensionId: string, installationId: string): Promise<unknown>;
  };
  events: {
    schemas(): Promise<unknown>;
    subscribe(target: { kind: 'run' | 'execution'; id: string }): AsyncGenerator<unknown>;
  };
  webhooks: {
    list(): Promise<unknown>;
    create(input: Record<string, unknown>): Promise<unknown>;
  };
  extensions: {
    list(params?: Record<string, string | undefined>): Promise<unknown>;
    create(input: Record<string, unknown>, opts?: RequestOptions): Promise<unknown>;
    get(id: string): Promise<unknown>;
    createVersion(id: string, input: Record<string, unknown>): Promise<unknown>;
    validate(id: string, files?: Record<string, string>): Promise<unknown>;
    test(id: string, files?: Record<string, string>): Promise<unknown>;
    package(id: string, files?: Record<string, string>): Promise<unknown>;
    publish(id: string, files?: Record<string, string>): Promise<unknown>;
    install(id: string, input: Record<string, unknown>): Promise<unknown>;
    quarantine(id: string, reason: string): Promise<unknown>;
    disable(id: string): Promise<unknown>;
  };
}

async function* paginate<T>(fetchPage: (p: { page: number; page_size: number }) => Promise<unknown>): AsyncGenerator<T> {
  let page = 1;
  for (;;) {
    const res = (await fetchPage({ page, page_size: 100 })) as
      | { items?: T[]; has_more?: boolean } | T[];
    const items = Array.isArray(res) ? res : (res.items ?? []);
    for (const item of items) yield item;
    if (Array.isArray(res) || !res.has_more || items.length === 0) return;
    page += 1;
  }
}

async function* streamEvents(config: SDKConfig, path: string): AsyncGenerator<unknown> {
  const res = await fetch(`${baseUrlOf(config)}${path}`, {
    headers: {
      Accept: 'text/event-stream',
      ...(config.apiKey ? { Authorization: `Bearer ${config.apiKey}` } : {}),
      ...(config.organizationId ? { 'X-Organization-ID': config.organizationId } : {}),
    },
  });
  if (!res.ok || !res.body) {
    throw toTypedError(res.status, path, '');
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
      try {
        yield JSON.parse(dataLine.slice(5).trim()) as unknown;
      } catch {
        // keep-alive comment — ignore
      }
    }
  }
}
