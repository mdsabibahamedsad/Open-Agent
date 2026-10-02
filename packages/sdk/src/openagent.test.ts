// Tests for @openagent/sdk OpenAgent class: headers, errors, resources.
import { describe, expect, it, vi } from 'vitest';
import { AuthenticationError, NotFoundError, OpenAgent } from './index';

function mockJson(payload: unknown, status = 200) {
  const fn = vi.fn(async () => new Response(JSON.stringify(payload), { status }));
  return fn as unknown as typeof fetch;
}

describe('OpenAgent', () => {
  it('creates agents with typed input + idempotency', async () => {
    const fetchMock = mockJson({ id: 'a1', name: 'Research Agent' });
    (globalThis as Record<string, unknown>).fetch = fetchMock;
    const client = new OpenAgent({ apiKey: 'k', baseUrl: 'https://api.example.com', organizationId: 'o' });
    const agent = (await client.agents.create({
      name: 'Research Agent', model: 'smart', instructions: 'Research.',
    }, { idempotencyKey: 'idem-1' })) as { id: string };
    expect(agent.id).toBe('a1');
    const calls = (fetchMock as unknown as { mock: { calls: Array<[string, RequestInit]> } }).mock.calls;
    const [, init] = calls[0];
    const headers = init.headers as Record<string, string>;
    expect(headers['Idempotency-Key']).toBe('idem-1');
    expect(headers['X-Request-ID']).toBeTruthy();
  });

  it('maps 401 to AuthenticationError', async () => {
    (globalThis as Record<string, unknown>).fetch = mockJson({}, 401);
    const client = new OpenAgent({ baseUrl: 'https://x', organizationId: 'o' });
    await expect(client.agents.list()).rejects.toBeInstanceOf(AuthenticationError);
  });

  it('maps 404 to NotFoundError', async () => {
    (globalThis as Record<string, unknown>).fetch = mockJson({}, 404);
    const client = new OpenAgent({ baseUrl: 'https://x', organizationId: 'o' });
    await expect(client.tools.get('missing')).rejects.toBeInstanceOf(NotFoundError);
  });

  it('exposes the full resource surface', () => {
    const client = new OpenAgent({ baseUrl: 'https://x' });
    for (const ns of ['agents', 'agentRuns', 'workflows', 'executions', 'tools',
      'connectors', 'integrations', 'mcp', 'memory', 'models', 'evaluations',
      'sandboxes', 'approvals', 'marketplace', 'registry', 'projects',
      'deployments', 'events', 'webhooks', 'extensions']) {
      expect((client as unknown as Record<string, unknown>)[ns], ns).toBeTruthy();
    }
    expect(client.connectors).toBe(client.integrations);
  });

  it('connectors alias integrations', async () => {
    (globalThis as Record<string, unknown>).fetch = mockJson({ items: [] });
    const client = new OpenAgent({ baseUrl: 'https://x', organizationId: 'o' });
    await client.connectors.catalog();
    await client.integrations.catalog();
  });
});
