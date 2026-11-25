import * as React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import type {
  AssistantConversation,
  AssistantConversationDetail,
  KoroChatResult,
} from '@/features/koro/koro-api';
import type { ChatStreamHandlers, ChatStreamInput } from '@/features/koro/chat-stream';
import { ApiError } from '@/lib/api';
import { MISSING_CONVERSATION_NOTICE } from '@/features/assistant/url-state';
import { AssistantWorkspace } from './AssistantWorkspace';

const ORG_1 = '11111111-1111-1111-1111-111111111111';
const ORG_2 = '22222222-2222-2222-2222-222222222222';
const CONV_A = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa';
const CONV_B = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb';
const CONV_HIDDEN = 'cccccccc-cccc-cccc-cccc-cccccccccccc';
const CONV_NEW = 'dddddddd-dddd-dddd-dddd-dddddddddddd';

type GetHandler = (
  endpoint: string,
  params?: Record<string, string | number | boolean | undefined | null>,
  opts?: { signal?: AbortSignal },
) => Promise<unknown>;

type DeleteHandler = (endpoint: string) => Promise<unknown>;

type StreamHandler = (
  organizationId: string,
  input: ChatStreamInput,
  handlers?: ChatStreamHandlers,
) => Promise<KoroChatResult>;

const mockState = vi.hoisted(() => ({
  orgId: '11111111-1111-1111-1111-111111111111' as string | null,
  searchParams: '',
  getImpl: null as GetHandler | null,
  deleteImpl: null as DeleteHandler | null,
  streamImpl: null as StreamHandler | null,
}));

vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    prefetch: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    go: vi.fn(),
    pathname: '/assistant',
    query: {},
    asPath: '/assistant',
  }),
  useSearchParams: () => new URLSearchParams(mockState.searchParams),
  usePathname: () => '/assistant',
}));

vi.mock('next/dynamic', () => ({
  default: () =>
    function MockDynamicCanvas() {
      return null;
    },
}));

vi.mock('@/context/OrganizationContext', () => ({
  useOrganization: () => ({
    organizations: [],
    currentOrg: null,
    currentOrgId: mockState.orgId,
    isLoading: false,
    error: null,
    switchOrg: vi.fn(),
    refresh: vi.fn(),
    permissions: [],
  }),
}));

vi.mock('@/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api')>('@/lib/api');
  return {
    ...actual,
    api: {
      get: vi.fn((endpoint: string, params?: Record<string, string | number | boolean | undefined | null>, opts?: { signal?: AbortSignal }) => {
        if (mockState.getImpl) {
          return mockState.getImpl(endpoint, params, opts);
        }
        return Promise.resolve({});
      }),
      post: vi.fn(() => Promise.resolve({})),
      put: vi.fn(() => Promise.resolve({})),
      patch: vi.fn(() => Promise.resolve({})),
      delete: vi.fn((endpoint: string) => {
        if (mockState.deleteImpl) {
          return mockState.deleteImpl(endpoint);
        }
        return Promise.resolve({});
      }),
    },
  };
});

vi.mock('@/features/koro/chat-stream', () => ({
  streamKoroChat: vi.fn((orgId: string, input: ChatStreamInput, handlers?: ChatStreamHandlers) => {
    if (mockState.streamImpl) {
      return mockState.streamImpl(orgId, input, handlers);
    }
    return Promise.resolve({
      reply: 'Done.',
      source: 'commands',
      actions: [],
      conversation_id: input.conversation_id ?? CONV_NEW,
    } satisfies KoroChatResult);
  }),
}));

function makeConversationSummary(
  id: string,
  title: string,
  updatedAt = '2026-11-25T10:00:00Z',
): AssistantConversation {
  return {
    id,
    title,
    message_count: 2,
    created_at: updatedAt,
    updated_at: updatedAt,
  };
}

function makeConversationDetail(
  id: string,
  title: string,
  userText: string,
  assistantText: string,
): AssistantConversationDetail {
  return {
    ...makeConversationSummary(id, title),
    messages: [
      {
        id: `${id}-m1`,
        role: 'user',
        content: userText,
        created_at: '2026-11-25T10:00:00Z',
      },
      {
        id: `${id}-m2`,
        role: 'assistant',
        content: assistantText,
        created_at: '2026-11-25T10:00:01Z',
        source: 'commands',
        actions: [],
      },
    ],
  };
}

function createDeferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function renderWorkspace(options: { strict?: boolean; client?: QueryClient } = {}) {
  const client =
    options.client ??
    new QueryClient({
      defaultOptions: {
        queries: { retry: false },
      },
    });
  const node = (
    <QueryClientProvider client={client}>
      <AssistantWorkspace />
    </QueryClientProvider>
  );
  const view = render(options.strict ? <React.StrictMode>{node}</React.StrictMode> : node);
  return { client, ...view };
}

function installNextHistoryPatch(onRouterSync: (nextUrl: string) => void) {
  const originalPushState = window.history.pushState.bind(window.history);
  const originalReplaceState = window.history.replaceState.bind(window.history);

  const copyNextJsInternalHistoryState = (data: unknown) => {
    const nextData: Record<string, unknown> =
      data && typeof data === 'object' ? { ...(data as Record<string, unknown>) } : {};
    const currentState = window.history.state as Record<string, unknown> | null;
    if (currentState?.__NA) {
      nextData.__NA = currentState.__NA;
    }
    if (currentState?.__PRIVATE_NEXTJS_INTERNALS_TREE) {
      nextData.__PRIVATE_NEXTJS_INTERNALS_TREE = currentState.__PRIVATE_NEXTJS_INTERNALS_TREE;
    }
    return nextData;
  };

  window.history.pushState = (data: unknown, unused: string, url?: string | URL | null) => {
    const state = data as Record<string, unknown> | null;
    if (state?.__NA || state?._N) {
      return originalPushState(data, unused, url);
    }
    const nextData = copyNextJsInternalHistoryState(data);
    if (url != null) {
      onRouterSync(String(url));
    }
    return originalPushState(nextData, unused, url);
  };

  window.history.replaceState = (data: unknown, unused: string, url?: string | URL | null) => {
    const state = data as Record<string, unknown> | null;
    if (state?.__NA || state?._N) {
      return originalReplaceState(data, unused, url);
    }
    const nextData = copyNextJsInternalHistoryState(data);
    if (url != null) {
      onRouterSync(String(url));
    }
    return originalReplaceState(nextData, unused, url);
  };

  return () => {
    window.history.pushState = originalPushState;
    window.history.replaceState = originalReplaceState;
  };
}

function navigateNextClient(
  nextUrl: string,
  rerender: (ui: React.ReactElement) => void,
  client: QueryClient,
) {
  const parsed = new URL(nextUrl, 'http://localhost');
  act(() => {
    window.history.pushState(
      { __NA: true, __PRIVATE_NEXTJS_INTERNALS_TREE: ['nav'] },
      '',
      nextUrl,
    );
    mockState.searchParams = parsed.searchParams.toString();
    rerender(
      <QueryClientProvider client={client}>
        <AssistantWorkspace />
      </QueryClientProvider>,
    );
  });
}

describe('AssistantWorkspace deep links and race safety', () => {
  let listByOrg: Record<string, AssistantConversation[]>;
  let detailsByOrg: Record<string, Record<string, AssistantConversationDetail>>;
  let requestedDetailUrls: string[];
  let detailSignals: AbortSignal[];

  beforeAll(() => {
    if (!HTMLElement.prototype.scrollTo) {
      Object.defineProperty(HTMLElement.prototype, 'scrollTo', {
        value: vi.fn(),
        configurable: true,
        writable: true,
      });
    }
  });

  beforeEach(() => {
    mockState.orgId = ORG_1;
    mockState.searchParams = '';
    requestedDetailUrls = [];
    detailSignals = [];
    listByOrg = {
      [ORG_1]: [
        makeConversationSummary(CONV_A, 'Chat Alpha', '2026-11-25T10:05:00Z'),
        makeConversationSummary(CONV_B, 'Chat Beta', '2026-11-25T10:04:00Z'),
      ],
      [ORG_2]: [],
    };
    detailsByOrg = {
      [ORG_1]: {
        [CONV_A]: makeConversationDetail(CONV_A, 'Chat Alpha', 'User Alpha', 'Reply Alpha'),
        [CONV_B]: makeConversationDetail(CONV_B, 'Chat Beta', 'User Beta', 'Reply Beta'),
        [CONV_HIDDEN]: makeConversationDetail(
          CONV_HIDDEN,
          'Older Chat',
          'Older question',
          'Older answer beyond limit 50',
        ),
      },
      [ORG_2]: {},
    };

    mockState.getImpl = async (endpoint, _params, opts) => {
      if (endpoint.endsWith('/copilot/status')) {
        return {
          ready: false,
          provider: 'ollama',
          model: 'qwen2.5:0.5b-instruct',
          model_size: '400MB',
          base_url: 'http://127.0.0.1:11434/v1',
          models: [],
          install_hint: 'Install Ollama',
          api_key_set: false,
          local: true,
          customized: false,
        };
      }
      if (endpoint.endsWith('/copilot/conversations')) {
        const orgMatch = endpoint.match(/\/organizations\/([^/]+)\/copilot\/conversations$/);
        const org = orgMatch ? decodeURIComponent(orgMatch[1]) : ORG_1;
        return listByOrg[org] ?? [];
      }
      const detailMatch = endpoint.match(
        /\/organizations\/([^/]+)\/copilot\/conversations\/([^/]+)$/,
      );
      if (detailMatch) {
        requestedDetailUrls.push(endpoint);
        if (opts?.signal) detailSignals.push(opts.signal);
        const org = decodeURIComponent(detailMatch[1]);
        const id = decodeURIComponent(detailMatch[2]);
        const record = detailsByOrg[org]?.[id];
        if (!record) {
          throw new ApiError('Conversation not found', { status: 404, code: 'NOT_FOUND' });
        }
        return record;
      }
      if (endpoint.includes('/workflows')) {
        return { items: [], total: 0 };
      }
      if (endpoint.includes('/credentials')) {
        return { credentials: [] };
      }
      return {};
    };

    mockState.deleteImpl = async (endpoint) => {
      const match = endpoint.match(/\/organizations\/([^/]+)\/copilot\/conversations\/([^/]+)$/);
      if (!match) return { deleted: false, conversation_id: '' };
      const org = decodeURIComponent(match[1]);
      const id = decodeURIComponent(match[2]);
      listByOrg[org] = (listByOrg[org] ?? []).filter((item) => item.id !== id);
      if (detailsByOrg[org]) {
        delete detailsByOrg[org][id];
      }
      return { deleted: true, conversation_id: id };
    };

    mockState.streamImpl = null;
    window.history.replaceState({ tree: 'next-root' }, '', '/assistant');
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('opens in empty state when no conversation param is provided', async () => {
    renderWorkspace();
    expect(await screen.findByText('What do you want to automate?')).toBeInTheDocument();
    expect(window.location.pathname + window.location.search).toBe('/assistant');
    expect(requestedDetailUrls).toHaveLength(0);
  });

  it('loads transcript from ?conversation=<id> without modifying the URL', async () => {
    const replaceSpy = vi.spyOn(window.history, 'replaceState');
    window.history.replaceState(null, '', `/assistant?conversation=${CONV_A}`);
    replaceSpy.mockClear();

    renderWorkspace();

    expect(await screen.findByText('Reply Alpha')).toBeInTheDocument();
    expect(screen.getByText('User Alpha')).toBeInTheDocument();
    expect(window.location.pathname + window.location.search).toBe(`/assistant?conversation=${CONV_A}`);
    expect(replaceSpy).not.toHaveBeenCalled();
  });

  it('normalizes uppercase UUID deep links and matches lowercase backend data', async () => {
    window.history.replaceState(null, '', `/assistant?conversation=${CONV_A.toUpperCase()}`);

    renderWorkspace();

    expect(await screen.findByText('Reply Alpha')).toBeInTheDocument();
    expect(requestedDetailUrls).toContain(`/organizations/${ORG_1}/copilot/conversations/${CONV_A}`);
  });

  it('loads deep-linked conversation outside the recent 50 sidebar items', async () => {
    window.history.replaceState(null, '', `/assistant?conversation=${CONV_HIDDEN}`);

    renderWorkspace();

    expect(await screen.findByText('Older answer beyond limit 50')).toBeInTheDocument();
    expect(screen.getByText('Older question')).toBeInTheDocument();
  });

  it('preserves ?conversation=, unrelated query params, and hash when consuming ?prompt=', async () => {
    window.history.replaceState(
      null,
      '',
      `/assistant?conversation=${CONV_A}&prompt=Draft%20my%20flow&utm_source=docs#panel`,
    );

    renderWorkspace();

    expect(await screen.findByText('Reply Alpha')).toBeInTheDocument();
    const box = screen.getByLabelText('Message the assistant') as HTMLTextAreaElement;
    expect(box.value).toBe('Draft my flow');
    expect(window.location.pathname + window.location.search + window.location.hash).toBe(
      `/assistant?conversation=${CONV_A}&utm_source=docs#panel`,
    );
  });

  it('updates URL via pushState on conversation switch and New chat, passing null state to preserve Next.js router sync', async () => {
    window.history.replaceState(
      { __NA: true, __PRIVATE_NEXTJS_INTERNALS_TREE: ['tree'], custom: 'keep' },
      '',
      `/assistant?foo=bar#sec`,
    );
    const pushSpy = vi.spyOn(window.history, 'pushState');

    renderWorkspace();

    const alphaButtons = await screen.findAllByRole('button', { name: /Chat Alpha/ });
    fireEvent.click(alphaButtons[0]);

    expect(await screen.findByText('Reply Alpha')).toBeInTheDocument();
    expect(window.location.pathname + window.location.search + window.location.hash).toBe(
      `/assistant?foo=bar&conversation=${CONV_A}#sec`,
    );
    expect(pushSpy).toHaveBeenLastCalledWith(
      null,
      '',
      `/assistant?foo=bar&conversation=${CONV_A}#sec`,
    );

    const betaButtons = screen.getAllByRole('button', { name: /Chat Beta/ });
    fireEvent.click(betaButtons[0]);

    expect(await screen.findByText('Reply Beta')).toBeInTheDocument();
    expect(window.location.pathname + window.location.search + window.location.hash).toBe(
      `/assistant?foo=bar&conversation=${CONV_B}#sec`,
    );

    fireEvent.click(screen.getAllByRole('button', { name: 'New chat' })[0]);
    expect(await screen.findByText('What do you want to automate?')).toBeInTheDocument();
    expect(window.location.pathname + window.location.search + window.location.hash).toBe(
      '/assistant?foo=bar#sec',
    );
  });

  it('syncs server conversation_id via replaceState after sending first message in a new chat', async () => {
    const replaceSpy = vi.spyOn(window.history, 'replaceState');
    mockState.streamImpl = async (_org, input) => {
      const createdId = input.conversation_id ?? CONV_NEW;
      detailsByOrg[ORG_1][createdId] = makeConversationDetail(
        createdId,
        'First message',
        'First message',
        'Created on server',
      );
      listByOrg[ORG_1] = [
        makeConversationSummary(createdId, 'First message'),
        ...listByOrg[ORG_1],
      ];
      return {
        reply: 'Created on server',
        source: 'commands',
        actions: [],
        conversation_id: createdId,
      };
    };

    renderWorkspace();
    const box = await screen.findByLabelText('Message the assistant');
    fireEvent.change(box, { target: { value: 'First message' } });
    fireEvent.keyDown(box, { key: 'Enter' });

    expect(await screen.findByText('Created on server')).toBeInTheDocument();
    await waitFor(() => {
      expect(window.location.search).toBe(`?conversation=${CONV_NEW}`);
    });
    expect(replaceSpy).toHaveBeenCalled();
  });

  it('clears URL on deleting active conversation and shows notice if browser navigates back to deleted id', async () => {
    window.history.replaceState(null, '', `/assistant?conversation=${CONV_A}`);
    const replaceSpy = vi.spyOn(window.history, 'replaceState');

    renderWorkspace();
    expect(await screen.findByText('Reply Alpha')).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText('Delete chat “Chat Alpha”'));

    await waitFor(() => {
      expect(window.location.pathname + window.location.search).toBe('/assistant');
    });
    expect(await screen.findByText('What do you want to automate?')).toBeInTheDocument();
    expect(replaceSpy).toHaveBeenCalled();

    // Simulate browser Back returning to the deleted conversation URL.
    act(() => {
      window.history.replaceState(null, '', `/assistant?conversation=${CONV_A}`);
      window.dispatchEvent(new PopStateEvent('popstate'));
    });

    expect(await screen.findByText(MISSING_CONVERSATION_NOTICE)).toBeInTheDocument();
    expect(screen.queryByText('Reply Alpha')).toBeNull();
    expect(window.location.pathname + window.location.search).toBe('/assistant');
  });

  it('handles invalid UUID, empty conversation param, 404, and conversation_id 422 gracefully', async () => {
    for (const badUrl of [
      '/assistant?conversation=not-a-uuid',
      '/assistant?conversation=',
      '/assistant?conversation=00000000-0000-0000-0000-000000000000',
    ]) {
      window.history.replaceState(null, '', badUrl);
      const { unmount } = renderWorkspace();

      expect(await screen.findByText(MISSING_CONVERSATION_NOTICE)).toBeInTheDocument();
      expect(screen.getByText('What do you want to automate?')).toBeInTheDocument();
      expect(window.location.pathname + window.location.search).toBe('/assistant');
      unmount();
    }

    // Explicit 422 on path.conversation_id from backend
    const baseGet = mockState.getImpl!;
    mockState.getImpl = async (endpoint, params, opts) => {
      if (endpoint.includes(`/conversations/${CONV_A}`)) {
        throw new ApiError('Invalid request', {
          status: 422,
          code: 'VALIDATION_ERROR',
          details: [{ field: 'path.conversation_id', code: 'VALIDATION_ERROR', message: 'Invalid UUID' }],
        });
      }
      return baseGet(endpoint, params, opts);
    };
    window.history.replaceState(null, '', `/assistant?conversation=${CONV_A}`);
    renderWorkspace();
    expect(await screen.findByText(MISSING_CONVERSATION_NOTICE)).toBeInTheDocument();
    expect(window.location.pathname + window.location.search).toBe('/assistant');
  });

  it('preserves URL and allows Retry on 500 or network error without misreporting missing conversation', async () => {
    let failCount = 0;
    const baseGet = mockState.getImpl!;
    mockState.getImpl = async (endpoint, params, opts) => {
      if (endpoint.includes(`/conversations/${CONV_A}`)) {
        failCount += 1;
        if (failCount === 1) {
          throw new ApiError('Network error', { status: 0, code: 'NETWORK_ERROR' });
        }
        if (failCount === 2) {
          throw new ApiError('Internal error', { status: 500, code: 'SERVER_ERROR' });
        }
      }
      return baseGet(endpoint, params, opts);
    };

    window.history.replaceState(null, '', `/assistant?conversation=${CONV_A}`);
    renderWorkspace();

    expect(
      await screen.findByText('Network error. Check your connection and retry.'),
    ).toBeInTheDocument();
    expect(window.location.search).toBe(`?conversation=${CONV_A}`);
    expect(screen.queryByText(MISSING_CONVERSATION_NOTICE)).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(
      await screen.findByText('Something went wrong on our side. Please retry.'),
    ).toBeInTheDocument();
    expect(window.location.search).toBe(`?conversation=${CONV_A}`);

    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByText('Reply Alpha')).toBeInTheDocument();
  });

  it('syncs state on browser popstate without calling pushState, and cleans invalid popstate URLs', async () => {
    window.history.replaceState(null, '', `/assistant?conversation=${CONV_A}`);
    renderWorkspace();
    expect(await screen.findByText('Reply Alpha')).toBeInTheDocument();

    const pushSpy = vi.spyOn(window.history, 'pushState');
    const replaceSpy = vi.spyOn(window.history, 'replaceState');

    act(() => {
      window.history.replaceState(null, '', `/assistant?conversation=${CONV_B}`);
      replaceSpy.mockClear();
      window.dispatchEvent(new PopStateEvent('popstate'));
    });

    expect(await screen.findByText('Reply Beta')).toBeInTheDocument();
    expect(pushSpy).not.toHaveBeenCalled();

    act(() => {
      window.history.replaceState(null, '', '/assistant?conversation=bad-id');
      replaceSpy.mockClear();
      window.dispatchEvent(new PopStateEvent('popstate'));
    });

    expect(await screen.findByText(MISSING_CONVERSATION_NOTICE)).toBeInTheDocument();
    expect(window.location.pathname + window.location.search).toBe('/assistant');
    expect(pushSpy).not.toHaveBeenCalled();
    expect(replaceSpy).toHaveBeenCalled();
  });

  it('cancels stale detail request and prevents slow response A from overwriting fast response B', async () => {
    const deferredA = createDeferred<AssistantConversationDetail>();
    const baseGet = mockState.getImpl!;
    mockState.getImpl = async (endpoint, params, opts) => {
      if (endpoint.includes(`/conversations/${CONV_A}`)) {
        if (opts?.signal) detailSignals.push(opts.signal);
        return deferredA.promise;
      }
      return baseGet(endpoint, params, opts);
    };

    renderWorkspace();
    const alphaBtn = (await screen.findAllByRole('button', { name: /Chat Alpha/ }))[0];
    const betaBtn = screen.getAllByRole('button', { name: /Chat Beta/ })[0];

    fireEvent.click(alphaBtn);
    // While detail A is loading, composer send is disabled.
    const box = screen.getByLabelText('Message the assistant') as HTMLTextAreaElement;
    expect(box.disabled).toBe(true);

    fireEvent.click(betaBtn);
    expect(await screen.findByText('Reply Beta')).toBeInTheDocument();
    expect(detailSignals.some((s) => s.aborted)).toBe(true);

    // Late resolution of A must not overwrite B's transcript or URL.
    await act(async () => {
      deferredA.resolve(detailsByOrg[ORG_1][CONV_A]);
    });

    expect(screen.getByText('Reply Beta')).toBeInTheDocument();
    expect(screen.queryByText('Reply Alpha')).toBeNull();
    expect(window.location.search).toBe(`?conversation=${CONV_B}`);
  });

  it('protects B stream, URL, busy state, and abort controller when late A stream resolves or fails', async () => {
    const streamA = createDeferred<KoroChatResult>();
    const streamB = createDeferred<KoroChatResult>();
    let handlersA: ChatStreamHandlers | undefined;
    let handlersB: ChatStreamHandlers | undefined;
    let callCount = 0;

    mockState.streamImpl = (_orgId, _input, handlers) => {
      callCount += 1;
      if (callCount === 1) {
        handlersA = handlers;
        return streamA.promise;
      }
      handlersB = handlers;
      return streamB.promise;
    };

    renderWorkspace();
    await screen.findByText('What do you want to automate?');

    // Start streaming turn A from a blank chat (no conversation_id yet).
    const box = screen.getByLabelText('Message the assistant');
    fireEvent.change(box, { target: { value: 'Prompt for A' } });
    fireEvent.keyDown(box, { key: 'Enter' });

    await waitFor(() => expect(callCount).toBe(1));
    expect(screen.getByLabelText('Stop the assistant')).toBeInTheDocument();

    // User switches to existing conversation B while A is in flight.
    fireEvent.click(screen.getAllByRole('button', { name: /Chat Beta/ })[0]);
    expect(handlersA?.signal?.aborted).toBe(true);
    expect(await screen.findByText('Reply Beta')).toBeInTheDocument();
    expect(window.location.search).toBe(`?conversation=${CONV_B}`);

    // Start streaming turn B in conversation B.
    const boxB = screen.getByLabelText('Message the assistant');
    fireEvent.change(boxB, { target: { value: 'Prompt for B' } });
    fireEvent.keyDown(boxB, { key: 'Enter' });
    await waitFor(() => expect(callCount).toBe(2));
    expect(screen.getByLabelText('Stop the assistant')).toBeInTheDocument();

    // Late delta + late resolve + finally from A must NOT touch B's UI, URL, busy, or abort signal!
    await act(async () => {
      handlersA?.onDelta?.('STALE_DELTA_A');
      streamA.resolve({
        reply: 'STALE_REPLY_A',
        source: 'commands',
        actions: [],
        conversation_id: CONV_NEW,
      });
    });

    expect(screen.queryByText(/STALE_DELTA_A/)).toBeNull();
    expect(screen.queryByText(/STALE_REPLY_A/)).toBeNull();
    expect(window.location.search).toBe(`?conversation=${CONV_B}`);
    // B must STILL be busy with Stop button working against B's signal!
    const stopBtn = screen.getByLabelText('Stop the assistant');
    expect(stopBtn).toBeInTheDocument();
    expect(handlersB?.signal?.aborted).toBe(false);

    // Clicking Stop now aborts B (proving A's finally did not clear abortRef).
    fireEvent.click(stopBtn);
    expect(handlersB?.signal?.aborted).toBe(true);

    await act(async () => {
      streamB.reject(new DOMException('Aborted', 'AbortError'));
    });
    await waitFor(() => {
      expect(screen.queryByLabelText('Stop the assistant')).toBeNull();
    });
  });

  it('isolates state and cancels stream when switching organizations', async () => {
    const streamOrg1 = createDeferred<KoroChatResult>();
    let handlersOrg1: ChatStreamHandlers | undefined;
    mockState.streamImpl = (_orgId, _input, handlers) => {
      handlersOrg1 = handlers;
      return streamOrg1.promise;
    };

    window.history.replaceState(null, '', `/assistant?conversation=${CONV_A}`);
    const { rerender, client } = renderWorkspace();
    expect(await screen.findByText('Reply Alpha')).toBeInTheDocument();

    const box = screen.getByLabelText('Message the assistant');
    fireEvent.change(box, { target: { value: 'Org1 message' } });
    fireEvent.keyDown(box, { key: 'Enter' });
    await waitFor(() => expect(handlersOrg1).toBeDefined());

    // Switch to ORG_2
    mockState.orgId = ORG_2;
    rerender(
      <QueryClientProvider client={client}>
        <AssistantWorkspace />
      </QueryClientProvider>,
    );

    expect(handlersOrg1?.signal?.aborted).toBe(true);
    expect(await screen.findByText('What do you want to automate?')).toBeInTheDocument();
    expect(screen.queryByText('Reply Alpha')).toBeNull();
    expect(window.location.pathname + window.location.search).toBe('/assistant');

    // Late rejection/resolution from Org1 must not show error or update Org2 state.
    await act(async () => {
      streamOrg1.reject(new ApiError('Org1 failed', { status: 500, code: 'SERVER_ERROR' }));
    });
    expect(screen.queryByText('Org1 failed')).toBeNull();
  });

  it('initializes reliably under React StrictMode without losing prompt/notice or duplicating popstate listeners', async () => {
    const addListenerSpy = vi.spyOn(window, 'addEventListener');
    const removeListenerSpy = vi.spyOn(window, 'removeEventListener');

    window.history.replaceState(null, '', `/assistant?conversation=bad-uuid&prompt=Keep%20me`);
    const { unmount } = renderWorkspace({ strict: true });

    expect(await screen.findByText(MISSING_CONVERSATION_NOTICE)).toBeInTheDocument();
    const box = screen.getByLabelText('Message the assistant') as HTMLTextAreaElement;
    expect(box.value).toBe('Keep me');
    expect(window.location.pathname + window.location.search).toBe('/assistant');

    // Verify StrictMode remount registered and cleaned up symmetrically (net 1 active listener).
    const addedPop = addListenerSpy.mock.calls.filter(([type]) => type === 'popstate').length;
    const removedPop = removeListenerSpy.mock.calls.filter(([type]) => type === 'popstate').length;
    expect(addedPop - removedPop).toBe(1);

    unmount();
    const removedAfterUnmount = removeListenerSpy.mock.calls.filter(
      ([type]) => type === 'popstate',
    ).length;
    expect(addedPop - removedAfterUnmount).toBe(0);
  });

  // --- S3 Regression Tests: DEF-01 ---
  it('syncs Next.js router state when history.state carries __NA marker', async () => {
    window.history.replaceState(
      { __NA: true, __PRIVATE_NEXTJS_INTERNALS_TREE: ['root'] },
      '',
      '/assistant',
    );
    const routerSyncedUrls: string[] = [];
    let rerenderView: ((ui: React.ReactElement) => void) | null = null;
    let queryClient!: QueryClient;
    const uninstall = installNextHistoryPatch((nextUrl) => {
      routerSyncedUrls.push(nextUrl);
      const parsed = new URL(nextUrl, 'http://localhost');
      mockState.searchParams = parsed.searchParams.toString();
      if (rerenderView) {
        rerenderView(
          <QueryClientProvider client={queryClient}>
            <AssistantWorkspace />
          </QueryClientProvider>,
        );
      }
    });

    try {
      const rendered = renderWorkspace();
      rerenderView = rendered.rerender;
      queryClient = rendered.client;

      const alphaBtn = (await screen.findAllByRole('button', { name: /Chat Alpha/ }))[0];
      fireEvent.click(alphaBtn);
      expect(await screen.findByText('Reply Alpha')).toBeInTheDocument();

      expect(routerSyncedUrls).toContain(`/assistant?conversation=${CONV_A}`);
      expect(mockState.searchParams).toBe(`conversation=${CONV_A}`);
      expect((window.history.state as { __NA?: boolean }).__NA).toBe(true);

      fireEvent.click(screen.getAllByRole('button', { name: 'New chat' })[0]);
      expect(await screen.findByText('What do you want to automate?')).toBeInTheDocument();
      expect(routerSyncedUrls).toContain('/assistant');
      expect(mockState.searchParams).toBe('');
      expect((window.history.state as { __NA?: boolean }).__NA).toBe(true);
    } finally {
      uninstall();
    }
  });

  it('resets thread to fresh state on Next.js client navigation to /assistant (main nav Chat click)', async () => {
    window.history.replaceState(
      { __NA: true, __PRIVATE_NEXTJS_INTERNALS_TREE: ['init'] },
      '',
      `/assistant?conversation=${CONV_A}`,
    );
    mockState.searchParams = `conversation=${CONV_A}`;
    const { rerender, client } = renderWorkspace();

    expect(await screen.findByText('Reply Alpha')).toBeInTheDocument();

    // Simulate clicking main sidebar Link href="/assistant" without unmounting AssistantWorkspace.
    navigateNextClient('/assistant', rerender, client);

    expect(await screen.findByText('What do you want to automate?')).toBeInTheDocument();
    expect(screen.queryByText('Reply Alpha')).toBeNull();
    expect(window.location.pathname + window.location.search).toBe('/assistant');
  });

  it('switches conversation and prefills prompt on Next.js client Link navigation', async () => {
    window.history.replaceState({ __NA: true }, '', `/assistant?conversation=${CONV_A}`);
    mockState.searchParams = `conversation=${CONV_A}`;
    const { rerender, client } = renderWorkspace();
    expect(await screen.findByText('Reply Alpha')).toBeInTheDocument();

    // Client-side Link navigation to another conversation
    navigateNextClient(`/assistant?conversation=${CONV_B}&tag=nav#section`, rerender, client);
    expect(await screen.findByText('Reply Beta')).toBeInTheDocument();
    expect(screen.queryByText('Reply Alpha')).toBeNull();

    // Client-side Link navigation carrying ?prompt= back to fresh chat
    navigateNextClient('/assistant?prompt=Run%20audit&tag=nav#section', rerender, client);
    expect(await screen.findByText('What do you want to automate?')).toBeInTheDocument();
    const box = screen.getByLabelText('Message the assistant') as HTMLTextAreaElement;
    expect(box.value).toBe('Run audit');
    expect(window.location.pathname + window.location.search + window.location.hash).toBe(
      '/assistant?tag=nav#section',
    );
  });

  // --- S3 Regression Tests: DEF-02 ---
  it('treats 401, 403, 429, 500, and network failures on empty chat as recoverable errors rather than missing conversation', async () => {
    const cases: Array<{ err: ApiError; text: string }> = [
      { err: new ApiError('Unauthorized', { status: 401, code: 'UNAUTHORIZED' }), text: 'You are signed out. Please sign in again.' },
      { err: new ApiError('Forbidden', { status: 403, code: 'FORBIDDEN' }), text: 'You do not have permission to perform this action.' },
      { err: new ApiError('Too many', { status: 429, code: 'RATE_LIMITED' }), text: 'Too many requests. Please wait a moment and retry.' },
      { err: new ApiError('Server error', { status: 500, code: 'SERVER_ERROR' }), text: 'Something went wrong on our side. Please retry.' },
      { err: new ApiError('Network down', { status: 0, code: 'NETWORK_ERROR' }), text: 'Network error. Check your connection and retry.' },
    ];

    const baseGet = mockState.getImpl!;
    for (const testCase of cases) {
      mockState.getImpl = async (endpoint, params, opts) => {
        if (endpoint.includes(`/conversations/${CONV_A}`)) {
          throw testCase.err;
        }
        return baseGet(endpoint, params, opts);
      };
      window.history.replaceState(null, '', `/assistant?conversation=${CONV_A}`);
      mockState.searchParams = `conversation=${CONV_A}`;
      const { unmount } = renderWorkspace();

      expect(await screen.findByText(testCase.text)).toBeInTheDocument();
      expect(screen.queryByText(MISSING_CONVERSATION_NOTICE)).toBeNull();
      expect(window.location.search).toBe(`?conversation=${CONV_A}`);
      expect((screen.getByLabelText('Message the assistant') as HTMLTextAreaElement).disabled).toBe(true);
      expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Start new chat' })).toBeInTheDocument();
      unmount();
    }
  });

  it('shows Retry and Start new chat when background detail refetch fails on non-empty thread and unlocks after Retry', async () => {
    let shouldFail = false;
    const baseGet = mockState.getImpl!;
    mockState.getImpl = async (endpoint, params, opts) => {
      if (endpoint.includes(`/conversations/${CONV_A}`) && shouldFail) {
        throw new ApiError('Internal error', { status: 500, code: 'SERVER_ERROR' });
      }
      return baseGet(endpoint, params, opts);
    };

    window.history.replaceState(null, '', `/assistant?conversation=${CONV_A}`);
    mockState.searchParams = `conversation=${CONV_A}`;
    const { client } = renderWorkspace();
    expect(await screen.findByText('Reply Alpha')).toBeInTheDocument();

    shouldFail = true;
    await act(async () => {
      await client.invalidateQueries({ queryKey: ['koro', 'conversation', ORG_1, CONV_A] });
    });

    expect(await screen.findByText('Something went wrong on our side. Please retry.')).toBeInTheDocument();
    expect((screen.getByLabelText('Message the assistant') as HTMLTextAreaElement).disabled).toBe(true);
    const retryBtn = screen.getByRole('button', { name: 'Retry' });
    expect(screen.getByRole('button', { name: 'Start new chat' })).toBeInTheDocument();

    shouldFail = false;
    fireEvent.click(retryBtn);

    await waitFor(() => {
      expect(screen.queryByText('Something went wrong on our side. Please retry.')).toBeNull();
      expect((screen.getByLabelText('Message the assistant') as HTMLTextAreaElement).disabled).toBe(false);
    });
    expect(screen.getByText('Reply Alpha')).toBeInTheDocument();
  });

  it('shows error recovery controls when detail GET returns 500 immediately after creating a new conversation', async () => {
    let failCreatedDetail = true;
    const baseGet = mockState.getImpl!;
    mockState.getImpl = async (endpoint, params, opts) => {
      if (endpoint.includes(`/conversations/${CONV_NEW}`) && failCreatedDetail) {
        throw new ApiError('Server error', { status: 500, code: 'SERVER_ERROR' });
      }
      return baseGet(endpoint, params, opts);
    };
    mockState.streamImpl = async (_org, input) => {
      const createdId = input.conversation_id ?? CONV_NEW;
      detailsByOrg[ORG_1][createdId] = makeConversationDetail(
        createdId,
        'First message',
        'First message',
        'Created on server',
      );
      return {
        reply: 'Created on server',
        source: 'commands',
        actions: [],
        conversation_id: createdId,
      };
    };

    renderWorkspace();
    const box = await screen.findByLabelText('Message the assistant');
    fireEvent.change(box, { target: { value: 'First message' } });
    fireEvent.keyDown(box, { key: 'Enter' });

    expect(await screen.findByText('Created on server')).toBeInTheDocument();
    expect(await screen.findByText('Something went wrong on our side. Please retry.')).toBeInTheDocument();
    expect((screen.getByLabelText('Message the assistant') as HTMLTextAreaElement).disabled).toBe(true);

    failCreatedDetail = false;
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    await waitFor(() => {
      expect(screen.queryByText('Something went wrong on our side. Please retry.')).toBeNull();
      expect((screen.getByLabelText('Message the assistant') as HTMLTextAreaElement).disabled).toBe(false);
    });
  });

  it('aborts in-flight Retry and prevents pollution when switching to another conversation, and handles 404 on non-empty thread', async () => {
    let phase: 'ok' | 'fail_once' | 'retry_pending' | 'deleted' = 'ok';
    const deferredRetry = createDeferred<AssistantConversationDetail>();
    const baseGet = mockState.getImpl!;
    mockState.getImpl = async (endpoint, params, opts) => {
      if (endpoint.includes(`/conversations/${CONV_A}`)) {
        if (opts?.signal) detailSignals.push(opts.signal);
        if (phase === 'fail_once') {
          throw new ApiError('Network error', { status: 0, code: 'NETWORK_ERROR' });
        }
        if (phase === 'retry_pending') {
          return deferredRetry.promise;
        }
        if (phase === 'deleted') {
          throw new ApiError('Not found', { status: 404, code: 'NOT_FOUND' });
        }
      }
      return baseGet(endpoint, params, opts);
    };

    window.history.replaceState(null, '', `/assistant?conversation=${CONV_A}`);
    mockState.searchParams = `conversation=${CONV_A}`;
    const { client } = renderWorkspace();
    expect(await screen.findByText('Reply Alpha')).toBeInTheDocument();

    // Non-empty 500/network error -> click Retry -> switch to B while Retry is pending
    phase = 'fail_once';
    await act(async () => {
      await client.invalidateQueries({ queryKey: ['koro', 'conversation', ORG_1, CONV_A] });
    });
    expect(await screen.findByText('Network error. Check your connection and retry.')).toBeInTheDocument();

    phase = 'retry_pending';
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    fireEvent.click(screen.getAllByRole('button', { name: /Chat Beta/ })[0]);

    expect(await screen.findByText('Reply Beta')).toBeInTheDocument();
    expect(detailSignals.some((s) => s.aborted)).toBe(true);
    expect(screen.queryByText('Network error. Check your connection and retry.')).toBeNull();

    await act(async () => {
      deferredRetry.resolve(detailsByOrg[ORG_1][CONV_A]);
    });
    expect(screen.getByText('Reply Beta')).toBeInTheDocument();
    expect(screen.queryByText('Reply Alpha')).toBeNull();

    // Switch back to A -> simulate 404 on non-empty thread
    phase = 'ok';
    fireEvent.click(screen.getAllByRole('button', { name: /Chat Alpha/ })[0]);
    expect(await screen.findByText('Reply Alpha')).toBeInTheDocument();

    phase = 'deleted';
    await act(async () => {
      await client.invalidateQueries({ queryKey: ['koro', 'conversation', ORG_1, CONV_A] });
    });
    expect(await screen.findByText(MISSING_CONVERSATION_NOTICE)).toBeInTheDocument();
    expect(window.location.pathname + window.location.search).toBe('/assistant');
  });

  // --- S3 Regression Tests: DEF-03 ---
  it('protects streaming and completed turn messages from stale background refetch snapshots', async () => {
    const staleRefetchDuringStream = createDeferred<AssistantConversationDetail>();
    const staleRefetchAfterStream = createDeferred<AssistantConversationDetail>();
    let fetchStep = 0;
    const baseGet = mockState.getImpl!;

    mockState.getImpl = async (endpoint, params, opts) => {
      if (endpoint.includes(`/conversations/${CONV_A}`)) {
        fetchStep += 1;
        if (fetchStep === 1) {
          return baseGet(endpoint, params, opts);
        }
        if (fetchStep === 2) {
          return staleRefetchDuringStream.promise;
        }
        if (fetchStep === 3) {
          return staleRefetchAfterStream.promise;
        }
        return detailsByOrg[ORG_1][CONV_A];
      }
      return baseGet(endpoint, params, opts);
    };

    const streamTurn2 = createDeferred<KoroChatResult>();
    let streamHandlers: ChatStreamHandlers | undefined;
    mockState.streamImpl = (_org, _input, handlers) => {
      streamHandlers = handlers;
      return streamTurn2.promise;
    };

    window.history.replaceState(null, '', `/assistant?conversation=${CONV_A}`);
    mockState.searchParams = `conversation=${CONV_A}`;
    const { client } = renderWorkspace();
    expect(await screen.findByText('Reply Alpha')).toBeInTheDocument();

    // Start turn 2
    const box = screen.getByLabelText('Message the assistant');
    fireEvent.change(box, { target: { value: 'Second user prompt' } });
    fireEvent.keyDown(box, { key: 'Enter' });
    await waitFor(() => expect(streamHandlers).toBeDefined());

    act(() => {
      streamHandlers?.onDelta?.('Streaming partial');
    });
    expect(screen.getByText('Second user prompt')).toBeInTheDocument();
    expect(screen.getByText('Streaming partial')).toBeInTheDocument();

    // Trigger background refetch during streaming and resolve with stale 2-message snapshot
    void client.refetchQueries({ queryKey: ['koro', 'conversation', ORG_1, CONV_A] });
    await waitFor(() => expect(fetchStep).toBe(2));
    await act(async () => {
      staleRefetchDuringStream.resolve({
        ...detailsByOrg[ORG_1][CONV_A],
        updated_at: '2026-11-25T10:02:00Z',
      });
    });

    expect(screen.getByText('Second user prompt')).toBeInTheDocument();
    expect(screen.getByText('Streaming partial')).toBeInTheDocument();

    // Finish stream -> post-stream invalidation fires fetchStep 3; simulate server stale 2-msg snapshot arriving
    await act(async () => {
      streamTurn2.resolve({
        reply: 'Final turn 2 reply',
        source: 'commands',
        actions: [],
        conversation_id: CONV_A,
      });
    });
    expect(await screen.findByText('Final turn 2 reply')).toBeInTheDocument();
    expect(screen.getByText('Second user prompt')).toBeInTheDocument();

    await waitFor(() => expect(fetchStep).toBe(3));
    await act(async () => {
      staleRefetchAfterStream.resolve({
        ...detailsByOrg[ORG_1][CONV_A],
        updated_at: '2026-11-25T10:02:30Z',
      });
    });

    // Stale 2-msg snapshot must NOT overwrite final 4-message thread!
    expect(screen.getByText('Second user prompt')).toBeInTheDocument();
    expect(screen.getByText('Final turn 2 reply')).toBeInTheDocument();

    // Now return complete 4-message server snapshot (with server-canonical content/actions)
    detailsByOrg[ORG_1][CONV_A] = {
      ...detailsByOrg[ORG_1][CONV_A],
      message_count: 4,
      messages: [
        ...detailsByOrg[ORG_1][CONV_A].messages,
        {
          id: `${CONV_A}-m3`,
          role: 'user',
          content: 'Second user prompt',
          created_at: '2026-11-25T10:03:00Z',
        },
        {
          id: `${CONV_A}-m4`,
          role: 'assistant',
          content: 'Canonical server turn 2 reply',
          created_at: '2026-11-25T10:03:01Z',
          source: 'commands',
          actions: [],
        },
      ],
    };
    await act(async () => {
      await client.invalidateQueries({ queryKey: ['koro', 'conversation', ORG_1, CONV_A] });
    });
    expect(await screen.findByText('Canonical server turn 2 reply')).toBeInTheDocument();
    expect(screen.getByText('Second user prompt')).toBeInTheDocument();
  });

  it('preserves local messages on failed/aborted stream, multi-turn history, and A->B->A quick switch', async () => {
    const baseGet = mockState.getImpl!;
    let injectStaleNextGet = false;
    mockState.getImpl = async (endpoint, params, opts) => {
      if (endpoint.includes(`/conversations/${CONV_A}`) && injectStaleNextGet) {
        injectStaleNextGet = false;
        return {
          ...detailsByOrg[ORG_1][CONV_A],
          updated_at: '2026-11-25T10:01:00Z',
        };
      }
      return baseGet(endpoint, params, opts);
    };

    const abortedTurn = createDeferred<KoroChatResult>();
    let attempt = 0;
    mockState.streamImpl = (_org, input, handlers) => {
      attempt += 1;
      if (attempt === 1) {
        return Promise.reject(new ApiError('LLM failed', { status: 500, code: 'SERVER_ERROR' }));
      }
      if (attempt === 2) {
        handlers?.onDelta?.('Partial before stop');
        return abortedTurn.promise;
      }
      const prev = detailsByOrg[ORG_1][CONV_A];
      detailsByOrg[ORG_1][CONV_A] = {
        ...prev,
        message_count: prev.messages.length + 2,
        messages: [
          ...prev.messages,
          { id: `u-${attempt}`, role: 'user', content: input.message, created_at: '2026-11-25T10:04:00Z' },
          { id: `a-${attempt}`, role: 'assistant', content: `Reply ${attempt}`, created_at: '2026-11-25T10:04:01Z', source: 'commands', actions: [] },
        ],
      };
      return Promise.resolve({
        reply: `Reply ${attempt}`,
        source: 'commands',
        actions: [],
        conversation_id: CONV_A,
      });
    };

    window.history.replaceState(null, '', `/assistant?conversation=${CONV_A}`);
    mockState.searchParams = `conversation=${CONV_A}`;
    const { client } = renderWorkspace();
    expect(await screen.findByText('Reply Alpha')).toBeInTheDocument();

    // Failed turn must not be wiped by stale background refetch
    const box = screen.getByLabelText('Message the assistant');
    fireEvent.change(box, { target: { value: 'Failed prompt' } });
    fireEvent.keyDown(box, { key: 'Enter' });
    expect((await screen.findAllByText('Something went wrong on our side. Please retry.')).length).toBeGreaterThan(0);

    injectStaleNextGet = true;
    await act(async () => {
      await client.invalidateQueries({ queryKey: ['koro', 'conversation', ORG_1, CONV_A] });
    });
    expect(screen.getByText('Failed prompt')).toBeInTheDocument();

    // User-aborted turn keeps partial delta against stale refetch
    fireEvent.change(box, { target: { value: 'Aborted prompt' } });
    fireEvent.keyDown(box, { key: 'Enter' });
    expect(await screen.findByText('Partial before stop')).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText('Stop the assistant'));
    await act(async () => {
      abortedTurn.reject(new DOMException('Aborted', 'AbortError'));
    });

    injectStaleNextGet = true;
    await act(async () => {
      await client.invalidateQueries({ queryKey: ['koro', 'conversation', ORG_1, CONV_A] });
    });
    expect(screen.getByText('Aborted prompt')).toBeInTheDocument();
    expect(screen.getByText('Partial before stop')).toBeInTheDocument();

    // Next successful multi-turn send recovers cleanly
    fireEvent.change(box, { target: { value: 'Turn 3 ok' } });
    fireEvent.keyDown(box, { key: 'Enter' });
    await waitFor(() => {
      expect(screen.getByText('Reply 3')).toBeInTheDocument();
    });

    // A -> B -> A quick switch reloads canonical A transcript cleanly
    fireEvent.click(screen.getAllByRole('button', { name: /Chat Beta/ })[0]);
    expect(await screen.findByText('Reply Beta')).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole('button', { name: /Chat Alpha/ })[0]);
    expect(await screen.findByText('Reply 3')).toBeInTheDocument();
    expect(screen.queryByText('Failed prompt')).toBeNull();
  });

  // --- S3 Regression Tests: DEF-04 ---
  it('never issues a cross-org detail request during org switch, handles initial null org, intermediate null, and rapid switching', async () => {
    // 1. Start with orgId === null on deep link
    mockState.orgId = null;
    window.history.replaceState(null, '', `/assistant?conversation=${CONV_A}`);
    mockState.searchParams = `conversation=${CONV_A}`;
    const { rerender, client } = renderWorkspace();

    expect(requestedDetailUrls).toHaveLength(0);

    // 2. Org loads as ORG_1 -> loads CONV_A
    mockState.orgId = ORG_1;
    rerender(
      <QueryClientProvider client={client}>
        <AssistantWorkspace />
      </QueryClientProvider>,
    );
    expect(await screen.findByText('Reply Alpha')).toBeInTheDocument();
    expect(requestedDetailUrls).toEqual([`/organizations/${ORG_1}/copilot/conversations/${CONV_A}`]);

    // 3. Switch ORG_1 -> ORG_2: zero requests to ORG_2 for CONV_A!
    requestedDetailUrls = [];
    mockState.orgId = ORG_2;
    rerender(
      <QueryClientProvider client={client}>
        <AssistantWorkspace />
      </QueryClientProvider>,
    );

    expect(screen.queryByText('Reply Alpha')).toBeNull();
    expect(await screen.findByText('What do you want to automate?')).toBeInTheDocument();
    expect(requestedDetailUrls).not.toContain(`/organizations/${ORG_2}/copilot/conversations/${CONV_A}`);
    expect(requestedDetailUrls).toHaveLength(0);

    // 4. Open CONV_A in ORG_1, then switch ORG_1 -> null -> ORG_2 rapidly -> zero cross-org requests
    mockState.orgId = ORG_1;
    rerender(
      <QueryClientProvider client={client}>
        <AssistantWorkspace />
      </QueryClientProvider>,
    );
    fireEvent.click((await screen.findAllByRole('button', { name: /Chat Alpha/ }))[0]);
    expect(await screen.findByText('Reply Alpha')).toBeInTheDocument();
    requestedDetailUrls = [];

    mockState.orgId = null;
    rerender(
      <QueryClientProvider client={client}>
        <AssistantWorkspace />
      </QueryClientProvider>,
    );
    expect(screen.queryByText('Reply Alpha')).toBeNull();

    mockState.orgId = ORG_2;
    rerender(
      <QueryClientProvider client={client}>
        <AssistantWorkspace />
      </QueryClientProvider>,
    );
    expect(requestedDetailUrls).toHaveLength(0);
    expect(window.location.pathname + window.location.search).toBe('/assistant');
  });

  // --- S3 Regression Tests: DEF-05 ---
  it('isolates async delete errors, success resets, and QueryClient cache by request-time org and conversation', async () => {
    detailsByOrg[ORG_2][CONV_A] = makeConversationDetail(
      CONV_A,
      'Org2 Same ID Chat',
      'Org2 question',
      'Org2 answer intact',
    );
    listByOrg[ORG_2] = [makeConversationSummary(CONV_A, 'Org2 Same ID Chat')];

    let deleteDeferred = createDeferred<{ deleted: boolean; conversation_id: string }>();
    mockState.deleteImpl = () => deleteDeferred.promise;

    window.history.replaceState(null, '', `/assistant?conversation=${CONV_A}`);
    mockState.searchParams = `conversation=${CONV_A}`;
    const { rerender, client } = renderWorkspace();
    expect(await screen.findByText('Reply Alpha')).toBeInTheDocument();

    // Seed detail cache for both ORG_1 and ORG_2 under the same CONV_A id
    client.setQueryData(['koro', 'conversation', ORG_1, CONV_A], detailsByOrg[ORG_1][CONV_A]);
    client.setQueryData(['koro', 'conversation', ORG_2, CONV_A], detailsByOrg[ORG_2][CONV_A]);

    // Case A: Org1 delete fails 500 after switching to Org2 -> Org2 must NOT show Org1 error
    fireEvent.click(screen.getByLabelText('Delete chat “Chat Alpha”'));
    mockState.orgId = ORG_2;
    rerender(
      <QueryClientProvider client={client}>
        <AssistantWorkspace />
      </QueryClientProvider>,
    );
    await act(async () => {
      deleteDeferred.reject(new ApiError('Org1 delete boom', { status: 500, code: 'SERVER_ERROR' }));
    });
    expect(screen.queryByText('Something went wrong on our side. Please retry.')).toBeNull();

    // Case B: Org1 delete succeeds after switching to Org2 (which opens Org2 CONV_A) -> only ORG_1 cache removed, Org2 active CONV_A untouched!
    mockState.orgId = ORG_1;
    rerender(
      <QueryClientProvider client={client}>
        <AssistantWorkspace />
      </QueryClientProvider>,
    );
    fireEvent.click((await screen.findAllByRole('button', { name: /Chat Alpha/ }))[0]);
    expect(await screen.findByText('Reply Alpha')).toBeInTheDocument();

    deleteDeferred = createDeferred<{ deleted: boolean; conversation_id: string }>();
    fireEvent.click(screen.getByLabelText('Delete chat “Chat Alpha”'));

    mockState.orgId = ORG_2;
    rerender(
      <QueryClientProvider client={client}>
        <AssistantWorkspace />
      </QueryClientProvider>,
    );
    fireEvent.click((await screen.findAllByRole('button', { name: /Org2 Same ID Chat/ }))[0]);
    expect(await screen.findByText('Org2 answer intact')).toBeInTheDocument();

    await act(async () => {
      deleteDeferred.resolve({ deleted: true, conversation_id: CONV_A });
    });

    expect(screen.getByText('Org2 answer intact')).toBeInTheDocument();
    expect(window.location.search).toBe(`?conversation=${CONV_A}`);
    expect(client.getQueryData(['koro', 'conversation', ORG_1, CONV_A])).toBeUndefined();
    expect(client.getQueryData(['koro', 'conversation', ORG_2, CONV_A])).toBeDefined();

    // Case C: X -> Y -> X async delete boundary (error from first ORG_1 epoch must not appear after ORG_1 -> ORG_2 -> ORG_1)
    mockState.orgId = ORG_1;
    rerender(
      <QueryClientProvider client={client}>
        <AssistantWorkspace />
      </QueryClientProvider>,
    );
    fireEvent.click((await screen.findAllByRole('button', { name: /Chat Alpha/ }))[0]);
    expect(await screen.findByText('Reply Alpha')).toBeInTheDocument();

    deleteDeferred = createDeferred<{ deleted: boolean; conversation_id: string }>();
    fireEvent.click(screen.getByLabelText('Delete chat “Chat Alpha”'));
    mockState.orgId = ORG_2;
    rerender(
      <QueryClientProvider client={client}>
        <AssistantWorkspace />
      </QueryClientProvider>,
    );
    mockState.orgId = ORG_1;
    rerender(
      <QueryClientProvider client={client}>
        <AssistantWorkspace />
      </QueryClientProvider>,
    );
    await act(async () => {
      deleteDeferred.reject(new ApiError('Stale epoch delete failed', { status: 500, code: 'SERVER_ERROR' }));
    });
    expect(screen.queryByText('Something went wrong on our side. Please retry.')).toBeNull();
  });

  it('handles intra-org async delete switching A -> B (keeps B) and A -> B -> A (clears deleted A)', async () => {
    let deleteDeferred = createDeferred<{ deleted: boolean; conversation_id: string }>();
    mockState.deleteImpl = () => deleteDeferred.promise;

    window.history.replaceState(null, '', `/assistant?conversation=${CONV_A}`);
    mockState.searchParams = `conversation=${CONV_A}`;
    renderWorkspace();
    expect(await screen.findByText('Reply Alpha')).toBeInTheDocument();

    // Delete A, immediately switch to B -> resolve delete A -> B remains active
    fireEvent.click(screen.getByLabelText('Delete chat “Chat Alpha”'));
    fireEvent.click(screen.getAllByRole('button', { name: /Chat Beta/ })[0]);
    expect(await screen.findByText('Reply Beta')).toBeInTheDocument();

    await act(async () => {
      deleteDeferred.resolve({ deleted: true, conversation_id: CONV_A });
    });
    expect(screen.getByText('Reply Beta')).toBeInTheDocument();
    expect(window.location.search).toBe(`?conversation=${CONV_B}`);

    // Delete B, switch to A, switch back to B -> resolve delete B -> clears B cleanly
    deleteDeferred = createDeferred<{ deleted: boolean; conversation_id: string }>();
    fireEvent.click(screen.getByLabelText('Delete chat “Chat Beta”'));
    fireEvent.click(screen.getAllByRole('button', { name: /Chat Alpha/ })[0]);
    expect(await screen.findByText('Reply Alpha')).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole('button', { name: /Chat Beta/ })[0]);

    await act(async () => {
      deleteDeferred.resolve({ deleted: true, conversation_id: CONV_B });
    });
    expect(await screen.findByText('What do you want to automate?')).toBeInTheDocument();
    expect(window.location.pathname + window.location.search).toBe('/assistant');
  });

  // --- S3 Regression Test: DEF-06 ---
  it('avoids transient Loading transcript lock after first message creation while still failing safely on 500', async () => {
    const detailDeferred = createDeferred<AssistantConversationDetail>();
    const baseGet = mockState.getImpl!;
    mockState.getImpl = async (endpoint, params, opts) => {
      if (endpoint.includes(`/conversations/${CONV_NEW}`)) {
        return detailDeferred.promise;
      }
      return baseGet(endpoint, params, opts);
    };
    mockState.streamImpl = async (_org, input) => ({
      reply: 'First reply',
      source: 'commands',
      actions: [],
      conversation_id: input.conversation_id ?? CONV_NEW,
    });

    renderWorkspace();
    const box = (await screen.findByLabelText('Message the assistant')) as HTMLTextAreaElement;
    fireEvent.change(box, { target: { value: 'Hello' } });
    fireEvent.keyDown(box, { key: 'Enter' });

    expect(await screen.findByText('First reply')).toBeInTheDocument();
    // Composer stays usable and no Loading transcript banner flickers while detail GET settles
    expect(screen.queryByText('Loading transcript…')).toBeNull();
    expect((screen.getByLabelText('Message the assistant') as HTMLTextAreaElement).disabled).toBe(false);

    // If background detail GET subsequently fails 500, composer still locks safely with Retry UI
    await act(async () => {
      detailDeferred.reject(new ApiError('Server error', { status: 500, code: 'SERVER_ERROR' }));
    });
    expect(await screen.findByText('Something went wrong on our side. Please retry.')).toBeInTheDocument();
    expect((screen.getByLabelText('Message the assistant') as HTMLTextAreaElement).disabled).toBe(true);
  });

  it('aborts in-flight blank-chat stream when navigating via Next.js Link or popstate to an existing conversation', async () => {
    const blankStream = createDeferred<KoroChatResult>();
    let blankHandlers: ChatStreamHandlers | undefined;
    mockState.streamImpl = (_org, _input, handlers) => {
      blankHandlers = handlers;
      return blankStream.promise;
    };

    const { rerender, client } = renderWorkspace();
    const box = await screen.findByLabelText('Message the assistant');
    fireEvent.change(box, { target: { value: 'Blank thread message' } });
    fireEvent.keyDown(box, { key: 'Enter' });
    await waitFor(() => expect(blankHandlers).toBeDefined());

    navigateNextClient(`/assistant?conversation=${CONV_B}`, rerender, client);

    expect(blankHandlers?.signal?.aborted).toBe(true);
    expect(await screen.findByText('Reply Beta')).toBeInTheDocument();
    expect(screen.queryByText('Blank thread message')).toBeNull();

    await act(async () => {
      blankHandlers?.onDelta?.('STALE_BLANK_DELTA');
      blankStream.resolve({
        reply: 'STALE_BLANK_REPLY',
        source: 'commands',
        actions: [],
        conversation_id: CONV_NEW,
      });
    });

    expect(screen.queryByText(/STALE_BLANK_DELTA/)).toBeNull();
    expect(screen.queryByText(/STALE_BLANK_REPLY/)).toBeNull();
    expect(window.location.search).toBe(`?conversation=${CONV_B}`);
  });

  // --- S3-F Regression Tests: S3R-01 & S3R-02 ---
  it('S3R-01: prevents cached pre-persisted Stop snapshot from overwriting subsequent Turn 3 before Turn 3 GET settles', async () => {
    const turn2Deferred = createDeferred<KoroChatResult>();
    const turn3GetDeferred = createDeferred<AssistantConversationDetail>();
    let convAGetCount = 0;
    const baseGet = mockState.getImpl!;

    mockState.getImpl = async (endpoint, params, opts) => {
      if (endpoint.includes(`/conversations/${CONV_A}`)) {
        convAGetCount += 1;
        if (convAGetCount === 1) return baseGet(endpoint, params, opts);
        if (convAGetCount === 2) {
          return {
            ...detailsByOrg[ORG_1][CONV_A],
            message_count: 4,
            messages: [
              ...detailsByOrg[ORG_1][CONV_A].messages,
              { id: `${CONV_A}-m3`, role: 'user', content: 'PromptBeforeStop', created_at: '2026-11-25T10:02:00Z' },
              { id: `${CONV_A}-m4`, role: 'assistant', content: 'ServerReplyTurn2', created_at: '2026-11-25T10:02:01Z', source: 'commands', actions: [] },
            ],
          };
        }
        return turn3GetDeferred.promise;
      }
      return baseGet(endpoint, params, opts);
    };

    let streamAttempt = 0;
    mockState.streamImpl = (_org, _input, handlers) => {
      streamAttempt += 1;
      if (streamAttempt === 1) {
        handlers?.onDelta?.('PartialTurn2');
        return turn2Deferred.promise;
      }
      return Promise.resolve({
        reply: 'Turn3LocalReply',
        source: 'commands',
        actions: [],
        conversation_id: CONV_A,
      });
    };

    window.history.replaceState(null, '', `/assistant?conversation=${CONV_A}`);
    mockState.searchParams = `conversation=${CONV_A}`;
    const { client } = renderWorkspace();
    expect(await screen.findByText('Reply Alpha')).toBeInTheDocument();

    // Turn 2: server persists before Stop; external cache refresh brings 4-msg snapshot into detail.data
    const box = screen.getByLabelText('Message the assistant');
    fireEvent.change(box, { target: { value: 'PromptBeforeStop' } });
    fireEvent.keyDown(box, { key: 'Enter' });
    expect(await screen.findByText('PartialTurn2')).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText('Stop the assistant'));
    await act(async () => {
      turn2Deferred.reject(new DOMException('Aborted', 'AbortError'));
    });

    await act(async () => {
      await client.invalidateQueries({ queryKey: ['koro', 'conversation', ORG_1, CONV_A] });
    });
    expect(convAGetCount).toBe(2);

    // Turn 3: completes locally while Turn 3 GET is still pending; cached 4-msg snapshot must NOT overwrite it
    fireEvent.change(box, { target: { value: 'Turn3Question' } });
    fireEvent.keyDown(box, { key: 'Enter' });
    await waitFor(() => expect(convAGetCount).toBe(3));
    await act(async () => {});

    expect(screen.getByText('Turn3Question')).toBeInTheDocument();
    expect(screen.getByText('Turn3LocalReply')).toBeInTheDocument();
    expect(screen.queryByText('ServerReplyTurn2')).toBeNull();

    // When complete 6-msg Turn 3 snapshot arrives, canonical transcript replays normally
    await act(async () => {
      turn3GetDeferred.resolve({
        ...detailsByOrg[ORG_1][CONV_A],
        message_count: 6,
        messages: [
          ...detailsByOrg[ORG_1][CONV_A].messages,
          { id: `${CONV_A}-m3`, role: 'user', content: 'PromptBeforeStop', created_at: '2026-11-25T10:02:00Z' },
          { id: `${CONV_A}-m4`, role: 'assistant', content: 'ServerReplyTurn2', created_at: '2026-11-25T10:02:01Z', source: 'commands', actions: [] },
          { id: `${CONV_A}-m5`, role: 'user', content: 'Turn3Question', created_at: '2026-11-25T10:03:00Z' },
          { id: `${CONV_A}-m6`, role: 'assistant', content: 'Turn3CanonicalReply', created_at: '2026-11-25T10:03:01Z', source: 'commands', actions: [] },
        ],
      });
    });

    expect(await screen.findByText('Turn3CanonicalReply')).toBeInTheDocument();
    expect(screen.getByText('Turn3Question')).toBeInTheDocument();
  });

  it('S3R-01: rejects same-count snapshot missing current turn, supports repeated identical prompt and rapid consecutive sends', async () => {
    const turn1Get = createDeferred<AssistantConversationDetail>();
    const turn2Get = createDeferred<AssistantConversationDetail>();
    const turn3Get = createDeferred<AssistantConversationDetail>();
    const turn4Get = createDeferred<AssistantConversationDetail>();
    let getIdx = 0;
    const baseGet = mockState.getImpl!;

    mockState.getImpl = async (endpoint, params, opts) => {
      if (endpoint.includes(`/conversations/${CONV_A}`)) {
        getIdx += 1;
        if (getIdx === 1) return baseGet(endpoint, params, opts);
        if (getIdx === 2) return turn1Get.promise;
        if (getIdx === 3) return turn2Get.promise;
        if (getIdx === 4) return turn3Get.promise;
        return turn4Get.promise;
      }
      return baseGet(endpoint, params, opts);
    };

    let sendIdx = 0;
    mockState.streamImpl = async () => {
      sendIdx += 1;
      return {
        reply: `LocalReply${sendIdx}`,
        source: 'commands',
        actions: [],
        conversation_id: CONV_A,
      };
    };

    window.history.replaceState(null, '', `/assistant?conversation=${CONV_A}`);
    mockState.searchParams = `conversation=${CONV_A}`;
    renderWorkspace();
    expect(await screen.findByText('Reply Alpha')).toBeInTheDocument();

    // Send MainTabPrompt; stale 4-msg cross-tab snapshot without MainTabPrompt must be ignored
    const box = screen.getByLabelText('Message the assistant');
    fireEvent.change(box, { target: { value: 'MainTabPrompt' } });
    fireEvent.keyDown(box, { key: 'Enter' });
    await waitFor(() => expect(getIdx).toBe(2));
    expect(await screen.findByText('LocalReply1')).toBeInTheDocument();

    const baseMessages = detailsByOrg[ORG_1][CONV_A].messages;
    await act(async () => {
      turn1Get.resolve({
        ...detailsByOrg[ORG_1][CONV_A],
        message_count: 4,
        messages: [
          ...baseMessages,
          { id: 'other-u', role: 'user', content: 'OtherTabPrompt', created_at: '2026-11-25T10:01:00Z' },
          { id: 'other-a', role: 'assistant', content: 'OtherTabReply', created_at: '2026-11-25T10:01:01Z', source: 'commands', actions: [] },
        ],
      });
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(screen.getByText('MainTabPrompt')).toBeInTheDocument();
    expect(screen.getByText('LocalReply1')).toBeInTheDocument();
    expect(screen.queryByText('OtherTabReply')).toBeNull();

    // Now simulate complete 6-msg snapshot via manual refetch/invalidation or next turn:
    // Actually trigger next invalidation/wait for turn2Get after a failure or immediate next send.
    // First test rapid back-to-back send with repeated identical text 'MainTabPrompt' + 'FollowUpPrompt'.
    fireEvent.change(box, { target: { value: 'MainTabPrompt' } });
    fireEvent.keyDown(box, { key: 'Enter' });
    await waitFor(() => expect(getIdx).toBe(3));
    expect(await screen.findByText('LocalReply2')).toBeInTheDocument();

    // Before turn2Get settles, send FollowUpPrompt
    fireEvent.change(box, { target: { value: 'FollowUpPrompt' } });
    fireEvent.keyDown(box, { key: 'Enter' });
    await waitFor(() => expect(getIdx).toBe(4));
    expect(await screen.findByText('LocalReply3')).toBeInTheDocument();

    // Intermediate 8-msg snapshot arriving (without FollowUpPrompt) must not revert FollowUpPrompt
    await act(async () => {
      turn2Get.resolve({
        ...detailsByOrg[ORG_1][CONV_A],
        message_count: 8,
        messages: [
          ...baseMessages,
          { id: 'other-u', role: 'user', content: 'OtherTabPrompt', created_at: '2026-11-25T10:01:00Z' },
          { id: 'other-a', role: 'assistant', content: 'OtherTabReply', created_at: '2026-11-25T10:01:01Z', source: 'commands', actions: [] },
          { id: 'main-1u', role: 'user', content: 'MainTabPrompt', created_at: '2026-11-25T10:02:00Z' },
          { id: 'main-1a', role: 'assistant', content: 'Canonical1', created_at: '2026-11-25T10:02:01Z', source: 'commands', actions: [] },
          { id: 'main-2u', role: 'user', content: 'MainTabPrompt', created_at: '2026-11-25T10:03:00Z' },
          { id: 'main-2a', role: 'assistant', content: 'Canonical2', created_at: '2026-11-25T10:03:01Z', source: 'commands', actions: [] },
        ],
      });
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(screen.getByText('FollowUpPrompt')).toBeInTheDocument();
    expect(screen.getByText('LocalReply3')).toBeInTheDocument();

    // Complete 10-msg snapshot settles cleanly
    await act(async () => {
      turn3Get.resolve({
        ...detailsByOrg[ORG_1][CONV_A],
        message_count: 10,
        messages: [
          ...baseMessages,
          { id: 'other-u', role: 'user', content: 'OtherTabPrompt', created_at: '2026-11-25T10:01:00Z' },
          { id: 'other-a', role: 'assistant', content: 'OtherTabReply', created_at: '2026-11-25T10:01:01Z', source: 'commands', actions: [] },
          { id: 'main-1u', role: 'user', content: 'MainTabPrompt', created_at: '2026-11-25T10:02:00Z' },
          { id: 'main-1a', role: 'assistant', content: 'Canonical1', created_at: '2026-11-25T10:02:01Z', source: 'commands', actions: [] },
          { id: 'main-2u', role: 'user', content: 'MainTabPrompt', created_at: '2026-11-25T10:03:00Z' },
          { id: 'main-2a', role: 'assistant', content: 'Canonical2', created_at: '2026-11-25T10:03:01Z', source: 'commands', actions: [] },
          { id: 'main-3u', role: 'user', content: 'FollowUpPrompt', created_at: '2026-11-25T10:04:00Z' },
          { id: 'main-3a', role: 'assistant', content: 'CanonicalFollowUp', created_at: '2026-11-25T10:04:01Z', source: 'commands', actions: [] },
        ],
      });
    });
    expect(await screen.findByText('CanonicalFollowUp')).toBeInTheDocument();
    expect(screen.getByText('OtherTabReply')).toBeInTheDocument();
  });

  it('S3R-02: guards against backend order_by(created_at.asc()).limit(200) truncated snapshots omitting the new turn', async () => {
    const msgs200 = Array.from({ length: 200 }, (_, i) => ({
      id: `hist-${i}`,
      role: (i % 2 === 0 ? 'user' : 'assistant') as 'user' | 'assistant',
      content: `HistLine${i}`,
      created_at: '2026-11-25T10:00:00Z',
      ...(i % 2 === 1 ? { source: 'commands', actions: [] } : {}),
    }));
    detailsByOrg[ORG_1][CONV_A] = {
      ...makeConversationSummary(CONV_A, 'Long Chat'),
      message_count: 200,
      messages: msgs200,
    };

    let getIdx = 0;
    const baseGet = mockState.getImpl!;
    mockState.getImpl = async (endpoint, params, opts) => {
      if (endpoint.includes(`/conversations/${CONV_A}`)) {
        getIdx += 1;
        if (getIdx === 1) return baseGet(endpoint, params, opts);
        // Backend GET returns earliest 200 messages while message_count is 202.
        return {
          ...makeConversationSummary(CONV_A, 'Long Chat'),
          message_count: 202,
          messages: msgs200,
        };
      }
      return baseGet(endpoint, params, opts);
    };
    mockState.streamImpl = async () => ({
      reply: 'Turn101Reply',
      source: 'commands',
      actions: [],
      conversation_id: CONV_A,
    });

    window.history.replaceState(null, '', `/assistant?conversation=${CONV_A}`);
    mockState.searchParams = `conversation=${CONV_A}`;
    const { client } = renderWorkspace();
    expect(await screen.findByText('HistLine199')).toBeInTheDocument();

    const box = screen.getByLabelText('Message the assistant');
    fireEvent.change(box, { target: { value: 'Turn101Prompt' } });
    fireEvent.keyDown(box, { key: 'Enter' });
    await waitFor(() => expect(getIdx).toBeGreaterThanOrEqual(2));

    await act(async () => {
      await client.invalidateQueries({ queryKey: ['koro', 'conversation', ORG_1, CONV_A] });
    });

    // Newly appended Turn 101 must remain visible and not be wiped by earliest-200 truncation
    expect(screen.getByText('Turn101Prompt')).toBeInTheDocument();
    expect(screen.getByText('Turn101Reply')).toBeInTheDocument();
  });
});
