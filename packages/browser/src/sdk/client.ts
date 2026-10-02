/**
 * Policy-aware Browser SDK. All calls go through the canonical API/services —
 * the SDK never bypasses Tool Runtime, RBAC, or domain policy.
 */

export interface SdkClientOptions {
  baseUrl: string;
  apiKey?: string;
  organizationId: string;
  fetchImpl?: typeof fetch;
}

export interface ElementTarget {
  role?: string;
  name?: string;
  selector?: string;
  xpath?: string;
  testId?: string;
  text?: string;
}

function headers(opts: SdkClientOptions): Record<string, string> {
  return {
    'Content-Type': 'application/json',
    ...(opts.apiKey ? { Authorization: `Bearer ${opts.apiKey}` } : {}),
    'X-Organization-ID': opts.organizationId,
  };
}

async function request(opts: SdkClientOptions, path: string, init?: RequestInit) {
  const res = await (opts.fetchImpl ?? fetch)(`${opts.baseUrl}${path}`, {
    ...init,
    headers: { ...headers(opts), ...(init?.headers ?? {}) },
  });
  if (!res.ok) throw new Error(`Browser API ${res.status}: ${await res.text()}`);
  return res.json();
}

export class BrowserSessionClient {
  constructor(private opts: SdkClientOptions, readonly sessionId: string, readonly pageId?: string) {}

  async navigate(url: string): Promise<unknown> {
    return request(this.opts, `/api/v1/browser/tasks/actions-proxy`, {
      method: 'POST',
      body: JSON.stringify({ sessionId: this.sessionId, action: 'NAVIGATE', url }),
    });
  }

  async click(target: ElementTarget): Promise<unknown> {
    return request(this.opts, `/api/v1/browser/tasks/actions-proxy`, {
      method: 'POST',
      body: JSON.stringify({ sessionId: this.sessionId, action: 'CLICK', ...target }),
    });
  }

  async type(selector: string, text: string): Promise<unknown> {
    return request(this.opts, `/api/v1/browser/tasks/actions-proxy`, {
      method: 'POST',
      body: JSON.stringify({ sessionId: this.sessionId, action: 'TYPE', selector, text }),
    });
  }

  async extract(selector = 'body'): Promise<unknown> {
    return request(this.opts, `/api/v1/browser/tasks/actions-proxy`, {
      method: 'POST',
      body: JSON.stringify({ sessionId: this.sessionId, action: 'EXTRACT', selector }),
    });
  }

  async close(): Promise<unknown> {
    return request(this.opts, `/api/v1/browser/sessions/${this.sessionId}`, { method: 'DELETE' });
  }
}

export async function createBrowserSession(opts: SdkClientOptions, params?: { headless?: boolean }): Promise<BrowserSessionClient> {
  const data = await request(opts, '/api/v1/browser/sessions', {
    method: 'POST',
    body: JSON.stringify({ headless: params?.headless ?? true }),
  });
  return new BrowserSessionClient(opts, data.session_id ?? data.id);
}

export const openagentBrowser = { createBrowserSession, BrowserSessionClient };
