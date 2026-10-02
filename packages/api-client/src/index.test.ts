// Tests for @openagent/api-client: errors, retry safety, webhooks.
import { describe, expect, it, vi } from 'vitest';
import {
  ApiClient,
  OpenAgentApiError,
  parseWebhook,
  signWebhook,
  verifyWebhook,
} from './index';

function mockFetchOnce(status: number, body: unknown, headers: Record<string, string> = {}) {
  return vi.fn(async () => new Response(
    body === undefined ? null : JSON.stringify(body),
    { status, headers: { 'Content-Type': 'application/json', ...headers } },
  )) as unknown as typeof fetch;
}

describe('ApiClient', () => {
  it('sends auth + org + request-id headers', async () => {
    const fetchImpl = mockFetchOnce(200, { ok: true });
    const client = new ApiClient({
      baseUrl: 'https://api.example.com', apiKey: 'k', organizationId: 'o', fetchImpl,
    });
    await client.get('/developer/sdk');
    const [, init] = fetchImpl.mock.calls[0] as [string, RequestInit];
    const headers = init.headers as Record<string, string>;
    expect(headers.Authorization).toBe('Bearer k');
    expect(headers['X-Organization-ID']).toBe('o');
    expect(headers['X-Request-ID']).toBeTruthy();
  });

  it('maps 404/429 to typed errors with rate-limit metadata', async () => {
    const c404 = new ApiClient({
      baseUrl: 'https://x', fetchImpl: mockFetchOnce(404, { error: { code: 'NOT_FOUND', message: 'nope' } }),
    });
    await expect(c404.get('/x')).rejects.toMatchObject({ code: 'NOT_FOUND', status: 404 });
    const c429 = new ApiClient({
      baseUrl: 'https://x', maxRetries: 0,
      fetchImpl: mockFetchOnce(429, { error: { code: 'RATE_LIMITED', message: 'slow' } }, { 'Retry-After': '2' }),
    });
    try {
      await c429.get('/x');
      expect.unreachable();
    } catch (err) {
      expect(err).toBeInstanceOf(OpenAgentApiError);
      expect((err as OpenAgentApiError).code).toBe('RATE_LIMITED');
      expect((err as OpenAgentApiError).retryAfterSeconds).toBe(2);
    }
  });

  it('never retries unsafe non-idempotent writes', async () => {
    const fetchImpl = mockFetchOnce(500, { error: { code: 'SERVER_ERROR', message: 'boom' } });
    const client = new ApiClient({ baseUrl: 'https://x', maxRetries: 3, fetchImpl });
    await expect(client.post('/x', { a: 1 })).rejects.toBeInstanceOf(OpenAgentApiError);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it('retries idempotent writes with Idempotency-Key', async () => {
    let calls = 0;
    const fetchImpl = (async () => {
      calls += 1;
      if (calls === 1) return new Response('err', { status: 500 });
      return new Response('{"ok":true}', { status: 200 });
    }) as unknown as typeof fetch;
    const client = new ApiClient({ baseUrl: 'https://x', fetchImpl });
    const res = await client.post('/x', { a: 1 }, { idempotencyKey: 'k1' });
    expect(res).toEqual({ ok: true });
    expect(calls).toBe(2);
  });

  it('iterates paginated results', async () => {
    const pages = [
      { items: [1, 2], has_more: true },
      { items: [3], has_more: false },
    ];
    let i = 0;
    const fetchImpl = (async () =>
      new Response(JSON.stringify(pages[i++]), { status: 200 })) as unknown as typeof fetch;
    const client = new ApiClient({ baseUrl: 'https://x', fetchImpl });
    const out: unknown[] = [];
    for await (const item of client.iterate('/x')) out.push(item);
    expect(out).toEqual([1, 2, 3]);
  });
});

describe('webhooks', () => {
  it('sign/verify roundtrip; tamper + replay rejected', async () => {
    const body = '{"event":"tool.completed.v1"}';
    const header = await signWebhook('s', body, { deliveryId: 'd1', timestamp: 1_700_000_000 });
    expect((await verifyWebhook('s', body, header, { now: 1_700_000_100 })).ok).toBe(true);
    expect((await verifyWebhook('s', '{"event":"other"}', header, { now: 1_700_000_100 })).ok).toBe(false);
    expect((await verifyWebhook('s', body, header, { now: 1_700_000_100 + 3600 })).ok).toBe(false);
    expect((await verifyWebhook('s', body, 'garbage', { now: 1_700_000_100 })).ok).toBe(false);
  });

  it('parseWebhook requires event field', () => {
    expect(parseWebhook('{"event":"x"}')).toEqual({ event: 'x' });
    expect(() => parseWebhook('{"a":1}')).toThrow();
    expect(() => parseWebhook('nope')).toThrow();
  });
});
