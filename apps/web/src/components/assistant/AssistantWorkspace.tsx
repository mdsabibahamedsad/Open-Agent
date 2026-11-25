'use client';

import * as React from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { useQueryClient } from '@tanstack/react-query';
import {
  Bot,
  Check,
  Cpu,
  Download,
  KeyRound,
  Loader2,
  MessagesSquare,
  PanelLeft,
  Pencil,
  Pin,
  PinOff,
  Plus,
  Radio,
  Search,
  Settings,
  Sparkles,
  Trash2,
  Workflow,
  X,
} from 'lucide-react';
import {
  AssistantStepsCard,
  type DisplayAction,
} from '@/components/assistant/AssistantActionCard';
import {
  AssistantComposer,
  type ComposerMode,
} from '@/components/assistant/AssistantComposer';
import { Markdown } from '@/components/chat/Markdown';
import { Button } from '@/components/ui/button';
import { toUserMessage } from '@/lib/api';
import { cn } from '@/lib/utils';
import { useLocalStorage } from '@/hooks/hooks';
import { useOrganization } from '@/context/OrganizationContext';
import { streamKoroChat } from '@/features/koro/chat-stream';
import {
  useAssistantConversation,
  useAssistantConversations,
  useDeleteAssistantConversation,
  useKoroStatus,
  useRenameAssistantConversation,
  type AssistantConversationDetail,
} from '@/features/koro/koro-api';
import { useChatModelOverride } from '@/features/koro/use-chat-model';
import { buildKoroContext } from '@/features/koro/context';
import { useWorkflows } from '@/features/workflows/workflows-api';
import { withAttachments } from '@/features/assistant/attachments';
import { useCredentials } from '@/features/integrations/integrations-api';
import { RobotCompanion } from '@/components/robot/RobotCompanion';
import { useRobotCompanion } from '@/features/robot/use-robot-companion';
import {
  buildMentionResources,
  loadSavedPrompts,
} from '@/features/assistant/resources';
import {
  downloadTextFile,
  exportFilename,
  filterChats,
  groupChats,
  sortChats,
  togglePin,
  transcriptMarkdown,
} from '@/features/assistant/chat-list';
import type { MentionResource } from '@/features/assistant/mentions';
import {
  MISSING_CONVERSATION_NOTICE,
  buildAssistantUrl,
  currentRelativeUrl,
  isMissingConversationError,
  normalizeConversationId,
  parseAssistantUrlState,
  type AssistantUrlUpdates,
} from '@/features/assistant/url-state';

function syncAssistantUrl(updates: AssistantUrlUpdates, mode: 'push' | 'replace') {
  if (typeof window === 'undefined') return;
  const current = currentRelativeUrl(window.location);
  const next = buildAssistantUrl(window.location, updates);
  if (next === current) return;
  // Pass null so Next.js App Router's patched History API preserves internal
  // state (__NA/__PRIVATE_NEXTJS_INTERNALS_TREE) and syncs useSearchParams().
  if (mode === 'push') {
    window.history.pushState(null, '', next);
  } else {
    window.history.replaceState(null, '', next);
  }
}

interface ActiveConversation {
  id: string;
  orgId: string | null;
}

interface PendingTurnExpectation {
  /** Snapshot already cached when the turn completed (never replay as fresh). */
  staleSnapshot: AssistantConversationDetail | null;
  /** Monotonic minimum server message_count expected after this turn. */
  minMessageCount: number;
  /** User message content persisted by this turn (matches API 4000-char cap). */
  userContent: string;
  /** Earliest index at which this turn's user+assistant pair must appear. */
  minTurnStartIndex: number;
}

interface TranscriptSyncState {
  verifiedId: string | null;
  serverMessageCount: number;
  pendingTurn: PendingTurnExpectation | null;
  preserveLocalEntries: boolean;
}

function isSnapshotFreshForPendingTurn(
  snapshot: AssistantConversationDetail,
  pending: PendingTurnExpectation,
): boolean {
  if (pending.staleSnapshot && snapshot === pending.staleSnapshot) {
    return false;
  }
  const totalCount = Math.max(snapshot.message_count, snapshot.messages.length);
  if (totalCount < pending.minMessageCount) {
    return false;
  }
  // GET /conversations/{id} uses order_by(created_at.asc()).limit(200), so
  // truncated snapshots omit newly appended turns and must not overwrite them.
  if (snapshot.message_count > snapshot.messages.length) {
    return false;
  }
  const start = Math.min(pending.minTurnStartIndex, snapshot.messages.length);
  for (let i = start; i < snapshot.messages.length - 1; i += 1) {
    if (
      snapshot.messages[i].role === 'user' &&
      snapshot.messages[i].content === pending.userContent &&
      snapshot.messages[i + 1].role === 'assistant'
    ) {
      return true;
    }
  }
  return false;
}

/** One rendered line of the conversation (live or replayed from history). */
type Entry = {
  role: 'user' | 'assistant';
  content: string;
  source?: string;
  actions?: DisplayAction[];
};

const QUICK_PROMPTS = [
  'Build a workflow that triages support emails',
  'Show the versions of my main workflow',
  'What is running right now?',
  'List my credentials',
];

const STARTERS = [
  'Build a webhook to AI + Slack workflow',
  'Duplicate my main workflow and publish it',
  'Debug my last failed run',
  'Review my open workflow and suggest fixes',
];

const NAV_LINKS = [
  { href: '/workflows', label: 'Workflows', icon: Workflow },
  { href: '/runs', label: 'Executions', icon: Radio },
  { href: '/settings?tab=credentials', label: 'Credentials', icon: KeyRound },
  { href: '/settings/models', label: 'Models & keys', icon: Cpu },
  { href: '/settings', label: 'Settings', icon: Settings },
];

function relativeTime(iso: string): string {
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60_000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days < 7) return `${days}d ago`;
  return new Date(iso).toLocaleDateString();
}

export function AssistantWorkspace() {
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  const searchParamsKey = searchParams.toString();
  const { currentOrgId } = useOrganization();
  const conversations = useAssistantConversations();
  const [activeSession, setActiveSession] = React.useState<ActiveConversation | null>(null);
  // Bumped only when the user switches chats, so sending the first message
  // (which creates a transcript id) does not drop the chosen model.
  const [chatEpoch, setChatEpoch] = React.useState(0);
  const { override, setOverride } = useChatModelOverride(String(chatEpoch));
  const [busy, setBusy] = React.useState(false);
  const status = useKoroStatus(true);
  const rename = useRenameAssistantConversation();
  const remove = useDeleteAssistantConversation();
  const workflows = useWorkflows({ pageSize: 50 });
  const credentials = useCredentials();
  const robot = useRobotCompanion();

  const [entries, setEntries] = React.useState<Entry[]>([]);
  const [draft, setDraft] = React.useState('');
  const [mode, setMode] = React.useState<ComposerMode>('build');
  const [error, setError] = React.useState<string | null>(null);
  const [notice, setNotice] = React.useState<string | null>(null);
  const [historyOpen, setHistoryOpen] = React.useState(true);
  const [robotOpen, setRobotOpen] = useLocalStorage<boolean>('oa:assistant-robot-open', true);
  const [mobileRobotOpen, setMobileRobotOpen] = React.useState(false);
  const [mobileHistoryOpen, setMobileHistoryOpen] = React.useState(false);
  const [renaming, setRenaming] = React.useState<{ id: string; title: string } | null>(null);
  const [search, setSearch] = React.useState('');
  const [pinned, setPinned] = useLocalStorage<string[]>('oa:assistant-pinned', []);
  const scrollRef = React.useRef<HTMLDivElement>(null);

  const orgRef = React.useRef({
    current: currentOrgId,
    committed: currentOrgId,
    epoch: 0,
  });
  orgRef.current.current = currentOrgId;

  const turnRef = React.useRef<{
    sessionToken: number;
    requestId: number;
    abort: AbortController | null;
  }>({
    sessionToken: 0,
    requestId: 0,
    abort: null,
  });

  const urlSyncRef = React.useRef({
    initialized: false,
    searchKey: searchParamsKey,
  });

  const transcriptSyncRef = React.useRef<TranscriptSyncState>({
    verifiedId: null,
    serverMessageCount: 0,
    pendingTurn: null,
    preserveLocalEntries: false,
  });

  // Bind conversation visibility to the committed organization during render so
  // switching organizations immediately suppresses stale detail queries and UI.
  const isOrgTransitioning =
    orgRef.current.committed !== null && currentOrgId !== orgRef.current.committed;
  const isSessionValidForOrg =
    activeSession !== null &&
    !isOrgTransitioning &&
    (activeSession.orgId === null || activeSession.orgId === currentOrgId);
  const activeId = isSessionValidForOrg ? activeSession.id : null;
  const visibleEntries = React.useMemo(
    () => (isOrgTransitioning ? [] : entries),
    [isOrgTransitioning, entries],
  );

  const activeIdRef = React.useRef<string | null>(activeId);
  activeIdRef.current = activeId;
  const robotRef = React.useRef(robot);
  robotRef.current = robot;

  const detail = useAssistantConversation(activeId);

  const resetTranscriptSync = React.useCallback(() => {
    transcriptSyncRef.current = {
      verifiedId: null,
      serverMessageCount: 0,
      pendingTurn: null,
      preserveLocalEntries: false,
    };
  }, []);

  const cancelInFlightTurn = React.useCallback(() => {
    turnRef.current.sessionToken += 1;
    const controller = turnRef.current.abort;
    turnRef.current.abort = null;
    controller?.abort();
    setBusy(false);
    robotRef.current.stopSpeaking();
    robotRef.current.clearReply();
    robotRef.current.reset();
  }, []);

  const clearThreadState = React.useCallback(
    (nextNotice: string | null) => {
      cancelInFlightTurn();
      resetTranscriptSync();
      activeIdRef.current = null;
      setActiveSession(null);
      setEntries([]);
      setError(null);
      setNotice(nextNotice);
      setRenaming(null);
      setChatEpoch((epoch) => epoch + 1);
      setMobileHistoryOpen(false);
    },
    [cancelInFlightTurn, resetTranscriptSync],
  );

  const applyUrlSearch = React.useCallback(
    (rawSearch: string) => {
      const parsed = parseAssistantUrlState(rawSearch);
      const hasPrompt = parsed.prompt !== null;
      if (parsed.prompt !== null) {
        setDraft(parsed.prompt);
      }

      if (parsed.conversation.status === 'valid') {
        if (parsed.conversation.id !== activeIdRef.current) {
          if (activeIdRef.current !== null || turnRef.current.abort !== null) {
            cancelInFlightTurn();
            setChatEpoch((epoch) => epoch + 1);
          }
          resetTranscriptSync();
          activeIdRef.current = parsed.conversation.id;
          setActiveSession({
            id: parsed.conversation.id,
            orgId: orgRef.current.current,
          });
          setEntries([]);
          setError(null);
          setNotice(null);
          setRenaming(null);
          setMobileHistoryOpen(false);
        }
        if (hasPrompt) {
          syncAssistantUrl({ clearPrompt: true }, 'replace');
        }
        return;
      }

      if (parsed.conversation.status === 'invalid') {
        clearThreadState(MISSING_CONVERSATION_NOTICE);
        syncAssistantUrl({ conversationId: null, clearPrompt: hasPrompt }, 'replace');
        return;
      }

      if (activeIdRef.current !== null) {
        clearThreadState(null);
      }
      if (hasPrompt) {
        syncAssistantUrl({ clearPrompt: true }, 'replace');
      }
    },
    [cancelInFlightTurn, clearThreadState, resetTranscriptSync],
  );

  // Sync on initial mount and whenever Next.js client navigation updates searchParams.
  React.useEffect(() => {
    if (!urlSyncRef.current.initialized) {
      urlSyncRef.current = { initialized: true, searchKey: searchParamsKey };
      const initialSearch =
        window.location.search || (searchParamsKey ? `?${searchParamsKey}` : '');
      applyUrlSearch(initialSearch);
      return;
    }
    if (urlSyncRef.current.searchKey === searchParamsKey) return;
    urlSyncRef.current.searchKey = searchParamsKey;
    applyUrlSearch(window.location.search);
  }, [searchParamsKey, applyUrlSearch]);

  // Synchronize browser back/forward navigation and clean up on unmount.
  React.useEffect(() => {
    const turnState = turnRef.current;
    const handlePopState = () => {
      applyUrlSearch(window.location.search);
    };
    window.addEventListener('popstate', handlePopState);
    return () => {
      window.removeEventListener('popstate', handlePopState);
      turnState.sessionToken += 1;
      const controller = turnState.abort;
      turnState.abort = null;
      controller?.abort();
    };
  }, [applyUrlSearch]);

  // Finalize organization transitions or bind initial org to a pre-loaded deep link.
  React.useEffect(() => {
    const committedOrgId = orgRef.current.committed;
    if (committedOrgId === null && currentOrgId !== null) {
      orgRef.current.committed = currentOrgId;
      setActiveSession((prev) =>
        prev && prev.orgId === null ? { id: prev.id, orgId: currentOrgId } : prev,
      );
      return;
    }
    if (committedOrgId !== null && committedOrgId !== currentOrgId) {
      orgRef.current.committed = currentOrgId;
      orgRef.current.epoch += 1;
      clearThreadState(null);
      syncAssistantUrl({ conversationId: null }, 'replace');
    }
  }, [currentOrgId, clearThreadState]);

  // Replay a saved transcript into the thread without overwriting active streams
  // or local uncommitted/failed turns with stale snapshots.
  React.useEffect(() => {
    if (!activeId || busy || detail.isError) return;
    if (!detail.data || detail.data.id !== activeId) return;
    const sync = transcriptSyncRef.current;
    if (sync.preserveLocalEntries) return;
    if (sync.pendingTurn && !isSnapshotFreshForPendingTurn(detail.data, sync.pendingTurn)) {
      return;
    }

    transcriptSyncRef.current = {
      verifiedId: activeId,
      serverMessageCount: Math.max(detail.data.message_count, detail.data.messages.length),
      pendingTurn: null,
      preserveLocalEntries: false,
    };
    setEntries(
      detail.data.messages.map((message) => ({
        role: message.role === 'user' ? 'user' : 'assistant',
        content: message.content,
        source: message.source ?? undefined,
        actions: message.actions,
      })),
    );
  }, [activeId, busy, detail.data, detail.dataUpdatedAt, detail.isError]);

  // Gracefully fall back to a fresh chat when a deep-linked or deleted
  // conversation returns 404 or a conversation_id 422 validation error.
  React.useEffect(() => {
    if (!activeId || !detail.isError) return;
    if (!isMissingConversationError(detail.error)) return;
    const failedId = activeId;
    clearThreadState(MISSING_CONVERSATION_NOTICE);
    queryClient.removeQueries({
      queryKey: ['koro', 'conversation', currentOrgId, failedId],
    });
    void queryClient.invalidateQueries({ queryKey: ['koro', 'conversations', currentOrgId] });
    syncAssistantUrl({ conversationId: null }, 'replace');
  }, [activeId, currentOrgId, detail.isError, detail.error, queryClient, clearThreadState]);

  React.useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [visibleEntries, busy]);

  const startNewChat = (options?: { historyMode?: 'push' | 'replace' }) => {
    clearThreadState(null);
    setDraft('');
    syncAssistantUrl({ conversationId: null }, options?.historyMode ?? 'push');
  };

  const openConversation = (id: string) => {
    const normalizedId = normalizeConversationId(id) ?? id;
    if (normalizedId === activeIdRef.current) {
      setMobileHistoryOpen(false);
      return;
    }
    clearThreadState(null);
    activeIdRef.current = normalizedId;
    setActiveSession({ id: normalizedId, orgId: orgRef.current.current });
    syncAssistantUrl({ conversationId: normalizedId }, 'push');
  };

  const isVerifiedActiveConversation =
    activeId !== null && transcriptSyncRef.current.verifiedId === activeId;
  const isLoadingActiveConversation = Boolean(
    activeId &&
      !isVerifiedActiveConversation &&
      (!currentOrgId || detail.isPending || (detail.isFetching && detail.data?.id !== activeId)),
  );
  const hasDetailLoadError = Boolean(
    activeId && detail.isError && !isMissingConversationError(detail.error),
  );
  const composerDisabled = isLoadingActiveConversation || hasDetailLoadError;

  const send = async (payload: { text: string; attachments: Parameters<typeof withAttachments>[1] }) => {
    const message = payload.text.trim();
    if (!message || busy || !currentOrgId || isOrgTransitioning || composerDisabled) return;
    const outgoing = withAttachments(message, payload.attachments);
    const history = visibleEntries
      .slice(-6)
      .map((entry) => ({ role: entry.role, content: entry.content }));
    const requestSessionToken = turnRef.current.sessionToken;
    const requestId = ++turnRef.current.requestId;
    const requestOrgId = currentOrgId;
    const requestConversationId = activeId;
    const isCurrentRequest = () =>
      turnRef.current.sessionToken === requestSessionToken &&
      turnRef.current.requestId === requestId &&
      orgRef.current.current === requestOrgId;

    if (requestConversationId) {
      void queryClient.cancelQueries({
        queryKey: ['koro', 'conversation', requestOrgId, requestConversationId],
      });
    }
    transcriptSyncRef.current.preserveLocalEntries = false;

    setEntries((prev) => [
      ...prev,
      { role: 'user', content: message },
      { role: 'assistant', content: '' },
    ]);
    setDraft('');
    setError(null);
    setNotice(null);
    setBusy(true);
    robotRef.current.requestStarted();
    let streamed = false;
    const controller = new AbortController();
    turnRef.current.abort = controller;
    try {
      const result = await streamKoroChat(
        requestOrgId,
        {
          message: outgoing,
          history,
          persist: true,
          conversation_id: requestConversationId ?? undefined,
          model: override?.model,
          base_url: override?.base_url,
          context: {
            ...buildKoroContext(
              null,
              typeof window !== 'undefined' ? window.location.pathname : undefined,
            ),
            mode,
          },
        },
        {
          signal: controller.signal,
          onDelta: (text) => {
            if (!isCurrentRequest()) return;
            if (!streamed) {
              streamed = true;
              robotRef.current.responseStreaming();
            }
            setEntries((prev) => {
              const next = [...prev];
              const last = next.length - 1;
              if (last < 0 || next[last].role !== 'assistant') return prev;
              next[last] = { ...next[last], content: next[last].content + text };
              return next;
            });
          },
        },
      );

      void queryClient.invalidateQueries({ queryKey: ['koro', 'conversations', requestOrgId] });
      // Copilot actions can create, run or publish workflows and agents.
      void queryClient.invalidateQueries({ queryKey: ['workflows'] });
      void queryClient.invalidateQueries({ queryKey: ['agents'] });
      void queryClient.invalidateQueries({ queryKey: ['runs'] });

      if (!isCurrentRequest()) return;

      setEntries((prev) => {
        const next = [...prev];
        const last = next.length - 1;
        if (last >= 0) {
          next[last] = {
            role: 'assistant',
            content: result.reply,
            source: result.source,
            actions: result.actions,
          };
        }
        return next;
      });
      robotRef.current.completed(result.reply, true);

      const targetId =
        requestConversationId ??
        (result.conversation_id
          ? (normalizeConversationId(result.conversation_id) ?? result.conversation_id)
          : null);
      if (targetId) {
        const cachedDetail =
          queryClient.getQueryData<AssistantConversationDetail>([
            'koro',
            'conversation',
            requestOrgId,
            targetId,
          ]) ?? null;
        const cachedCount = cachedDetail
          ? Math.max(cachedDetail.message_count, cachedDetail.messages.length)
          : 0;
        const prevSync = transcriptSyncRef.current;
        const baseCount = Math.max(
          prevSync.serverMessageCount,
          prevSync.pendingTurn?.minMessageCount ?? 0,
          cachedCount,
        );
        transcriptSyncRef.current = {
          verifiedId: targetId,
          serverMessageCount: prevSync.serverMessageCount,
          pendingTurn: {
            staleSnapshot: cachedDetail,
            minMessageCount: baseCount + 2,
            userContent: outgoing.slice(0, 4000),
            minTurnStartIndex: baseCount,
          },
          preserveLocalEntries: false,
        };
        if (!requestConversationId) {
          activeIdRef.current = targetId;
          setActiveSession({ id: targetId, orgId: requestOrgId });
          syncAssistantUrl({ conversationId: targetId }, 'replace');
        }
        await queryClient.cancelQueries({
          queryKey: ['koro', 'conversation', requestOrgId, targetId],
        });
        void queryClient.invalidateQueries({
          queryKey: ['koro', 'conversation', requestOrgId, targetId],
        });
      }
    } catch (e) {
      if (!isCurrentRequest()) return;
      transcriptSyncRef.current.preserveLocalEntries = true;
      if ((e as Error)?.name === 'AbortError') {
        robotRef.current.reset();
        return;
      }
      const text = toUserMessage(e);
      setError(text);
      robotRef.current.failed();
      setEntries((prev) => {
        const next = [...prev];
        if (next.length > 0 && next[next.length - 1].role === 'assistant') {
          next[next.length - 1] = { role: 'assistant', content: text };
          return next;
        }
        return [...prev, { role: 'assistant', content: text }];
      });
    } finally {
      if (turnRef.current.abort === controller) {
        turnRef.current.abort = null;
      }
      if (isCurrentRequest()) {
        setBusy(false);
      }
    }
  };

  const submitRename = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!renaming || !renaming.title.trim()) return;
    try {
      await rename.mutateAsync({ id: renaming.id, title: renaming.title.trim() });
      setRenaming(null);
    } catch (e) {
      setError(toUserMessage(e));
    }
  };

  const deleteConversation = async (id: string) => {
    if (!currentOrgId) return;
    const requestOrgId = currentOrgId;
    const requestOrgEpoch = orgRef.current.epoch;
    const normalizedDeletedId = normalizeConversationId(id) ?? id;
    try {
      await remove.mutateAsync({ id, orgId: requestOrgId });
      if (
        orgRef.current.current === requestOrgId &&
        normalizedDeletedId === activeIdRef.current
      ) {
        startNewChat({ historyMode: 'replace' });
      }
    } catch (e) {
      if (
        orgRef.current.current !== requestOrgId ||
        orgRef.current.epoch !== requestOrgEpoch
      ) {
        return;
      }
      setError(toUserMessage(e));
    }
  };

  const exportConversation = () => {
    const title = activeTitle ?? 'Assistant chat';
    const messages =
      detail.data?.id === activeId && detail.data.messages.length > 0
        ? detail.data.messages
        : visibleEntries;
    downloadTextFile(exportFilename(title), transcriptMarkdown(title, messages));
  };

  const items = conversations.data ?? [];
  const visible = sortChats(filterChats(items, search), pinned);
  const grouped = groupChats(visible);
  const activeTitle =
    detail.data?.id === activeId
      ? detail.data?.title
      : items.find((item) => item.id === activeId)?.title;

  const ready = status.data?.ready;
  const local = status.data?.local ?? true;

  const resources = React.useMemo<MentionResource[]>(() => {
    return buildMentionResources({
      workflows: (workflows.items ?? []).map((workflow) => ({
        id: workflow.id,
        name: workflow.name,
        status: workflow.status,
      })),
      credentials: credentials.credentials.map((credential) => ({
        id: credential.id,
        name: credential.name,
        provider: credential.provider,
      })),
      prompts: STARTERS,
      savedPrompts: loadSavedPrompts(),
    });
  }, [workflows.items, credentials.credentials]);

  const historyList = (
    <div className="oa-scroll flex-1 overflow-y-auto p-2">
      {conversations.isLoading ? (
        <p className="flex items-center gap-2 px-2 py-3 text-xs text-muted-foreground">
          <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> Loading chats…
        </p>
      ) : conversations.isError ? (
        <div className="px-2 py-3">
          <p className="text-xs text-destructive">{toUserMessage(conversations.error)}</p>
          <Button
            size="sm"
            variant="outline"
            className="mt-2 h-7 text-[11px]"
            onClick={() => void conversations.refetch()}
          >
            Retry
          </Button>
        </div>
      ) : grouped.length === 0 ? (
        <p className="px-2 py-3 text-xs text-muted-foreground">
          {search.trim() ? 'No chats match that search.' : 'No chats yet. Your conversations are saved here.'}
        </p>
      ) : (
        <div className="space-y-3">
          {grouped.map((group) => (
            <div key={group.label}>
              <p className="px-2 pb-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground/70">
                {group.label}
              </p>
              <div className="space-y-0.5">
                {group.items.map((item) =>
                  renaming?.id === item.id ? (
                    <form
                      key={item.id}
                      onSubmit={submitRename}
                      className="flex items-center gap-1 rounded-lg border bg-background px-1.5 py-1"
                    >
                      <input
                        value={renaming.title}
                        onChange={(event) =>
                          setRenaming({ id: item.id, title: event.target.value })
                        }
                        onKeyDown={(event) => {
                          if (event.key === 'Escape') setRenaming(null);
                        }}
                        autoFocus
                        maxLength={200}
                        aria-label="Chat title"
                        className="min-w-0 flex-1 bg-transparent px-1 text-xs outline-none"
                      />
                      <button
                        type="submit"
                        aria-label="Save title"
                        className="rounded p-1 text-emerald-600 hover:bg-accent"
                      >
                        <Check className="h-3.5 w-3.5" />
                      </button>
                      <button
                        type="button"
                        aria-label="Cancel rename"
                        onClick={() => setRenaming(null)}
                        className="rounded p-1 text-muted-foreground hover:bg-accent"
                      >
                        <X className="h-3.5 w-3.5" />
                      </button>
                    </form>
                  ) : (
                    <div
                      key={item.id}
                      className={cn(
                        'group flex items-center gap-0.5 rounded-lg pr-1 transition-colors',
                        item.id === activeId ? 'bg-primary/10' : 'hover:bg-accent/70',
                      )}
                    >
                      <button
                        onClick={() => openConversation(item.id)}
                        aria-current={item.id === activeId ? 'true' : undefined}
                        className="min-w-0 flex-1 px-2 py-1.5 text-left"
                      >
                        <span
                          className={cn(
                            'flex items-center gap-1 truncate text-[13px]',
                            item.id === activeId ? 'font-medium text-primary' : 'text-foreground',
                          )}
                        >
                          {pinned.includes(item.id) && (
                            <Pin className="h-3 w-3 shrink-0 text-primary" aria-hidden />
                          )}
                          <span className="truncate">{item.title}</span>
                        </span>
                        <span className="oa-caption block truncate">
                          {relativeTime(item.updated_at)} · {item.message_count} message
                          {item.message_count === 1 ? '' : 's'}
                        </span>
                      </button>
                      <button
                        onClick={() => setPinned((current) => togglePin(current, item.id))}
                        aria-label={
                          pinned.includes(item.id)
                            ? `Unpin chat “${item.title}”`
                            : `Pin chat “${item.title}”`
                        }
                        className={cn(
                          'rounded p-1 text-muted-foreground transition-opacity hover:bg-accent hover:text-foreground focus-visible:opacity-100 group-hover:opacity-100',
                          pinned.includes(item.id) ? 'opacity-100' : 'opacity-0',
                        )}
                      >
                        {pinned.includes(item.id) ? (
                          <PinOff className="h-3.5 w-3.5" />
                        ) : (
                          <Pin className="h-3.5 w-3.5" />
                        )}
                      </button>
                      <button
                        onClick={() => setRenaming({ id: item.id, title: item.title })}
                        aria-label={`Rename chat “${item.title}”`}
                        className="rounded p-1 text-muted-foreground opacity-0 transition-opacity hover:bg-accent hover:text-foreground focus-visible:opacity-100 group-hover:opacity-100"
                      >
                        <Pencil className="h-3.5 w-3.5" />
                      </button>
                      <button
                        onClick={() => void deleteConversation(item.id)}
                        aria-label={`Delete chat “${item.title}”`}
                        disabled={
                          remove.isPending &&
                          (remove.variables === item.id ||
                            (typeof remove.variables === 'object' &&
                              remove.variables !== null &&
                              remove.variables.id === item.id))
                        }
                        className="rounded p-1 text-muted-foreground opacity-0 transition-opacity hover:bg-destructive/10 hover:text-destructive focus-visible:opacity-100 group-hover:opacity-100"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  ),
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );

  const sidebar = (
    <>
      <div className="flex h-14 shrink-0 items-center gap-2 border-b border-border/70 px-3">
        <span className="oa-brand flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-white shadow-sm">
          <Sparkles className="h-3.5 w-3.5" aria-hidden />
        </span>
        <h2 className="min-w-0 flex-1 truncate text-[13px] font-semibold">Assistant</h2>
        <button
          onClick={() => startNewChat()}
          aria-label="New chat"
          title="New chat"
          className="rounded-lg p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground"
        >
          <Plus className="h-4 w-4" />
        </button>
      </div>

      <div className="shrink-0 space-y-0.5 p-2">
        <button
          onClick={() => startNewChat()}
          className="flex w-full items-center gap-2 rounded-lg border border-border/70 bg-background px-2.5 py-1.5 text-left text-[13px] font-medium transition-colors hover:border-primary/40 hover:bg-accent"
        >
          <MessagesSquare className="h-4 w-4 text-muted-foreground" aria-hidden /> New chat
        </button>
        <nav className="pt-1" aria-label="Assistant navigation">
          {NAV_LINKS.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className="flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-[12.5px] text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
            >
              <link.icon className="h-3.5 w-3.5" aria-hidden /> {link.label}
            </Link>
          ))}
        </nav>
      </div>

      <div className="shrink-0 px-2 pb-1">
        <label className="relative block">
          <Search
            className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground"
            aria-hidden
          />
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search chats"
            aria-label="Search chats"
            className="w-full rounded-lg border border-border/70 bg-background py-1.5 pl-7 pr-2 text-xs outline-none focus:border-primary/60"
          />
        </label>
      </div>

      {historyList}
    </>
  );

  const isFresh = visibleEntries.length === 0;

  const composer = (
    <>
      {notice && (
        <div
          className="mb-2 flex items-center justify-between gap-2 rounded-lg border border-amber-500/30 bg-amber-500/[0.06] px-3 py-1.5 text-xs text-muted-foreground"
          role="status"
        >
          <span>{notice}</span>
          <button
            type="button"
            onClick={() => setNotice(null)}
            aria-label="Dismiss notice"
            className="rounded p-0.5 text-muted-foreground hover:bg-accent hover:text-foreground"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      )}
      {hasDetailLoadError && (
        <div
          role="alert"
          className="mb-2 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-destructive/30 bg-destructive/[0.06] px-3 py-2 text-xs text-destructive"
        >
          <span>{toUserMessage(detail.error)}</span>
          <div className="flex items-center gap-2">
            <Button
              type="button"
              size="sm"
              variant="outline"
              className="h-7 text-[11px]"
              onClick={() => void detail.refetch()}
            >
              Retry
            </Button>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              className="h-7 text-[11px]"
              onClick={() => startNewChat()}
            >
              Start new chat
            </Button>
          </div>
        </div>
      )}
      {error && (
        <p
          className="mb-2 rounded-lg border border-destructive/30 bg-destructive/[0.06] px-3 py-1.5 text-xs text-destructive"
          role="alert"
        >
          {error}
        </p>
      )}
      <AssistantComposer
        value={draft}
        onChange={setDraft}
        onSend={(payload) => void send(payload)}
        onStop={() => turnRef.current.abort?.abort()}
        busy={busy}
        disabled={composerDisabled}
        large={isFresh}
        modelOverride={override}
        onModelOverride={setOverride}
        onVoiceActivity={robot.voiceActivity}
        autoFocus
        resources={resources}
        starters={STARTERS}
        mode={mode}
        onModeChange={setMode}
        footer={
          <p className="oa-caption mt-1.5 flex items-center gap-1.5 px-1">
            <span
              className={cn('h-1.5 w-1.5 rounded-full', ready ? 'bg-emerald-500' : 'bg-amber-500')}
              aria-hidden
            />
            {local
              ? 'Runs on this machine · actions are permission-checked'
              : 'Uses your configured endpoint · actions are permission-checked'}
          </p>
        }
      />
    </>
  );

  return (
    <div className="flex h-[calc(100dvh-4rem)] w-full overflow-hidden">
      {historyOpen && (
        <aside className="hidden w-64 shrink-0 flex-col border-r border-border/70 bg-sidebar/40 lg:flex xl:w-72">
          {sidebar}
        </aside>
      )}

      <section className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center gap-2.5 border-b border-border/70 bg-card/70 px-3 backdrop-blur sm:px-4">
          <button
            onClick={() => setMobileHistoryOpen(true)}
            aria-label="Open chat history"
            className="rounded-lg p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground lg:hidden"
          >
            <MessagesSquare className="h-4 w-4" />
          </button>
          <div className="min-w-0 flex-1">
            <h1 className="truncate text-[13px] font-semibold leading-tight">
              {activeId ? activeTitle || 'Assistant' : 'AI assistant'}
            </h1>
            <p className="oa-caption flex items-center gap-1.5 truncate">
              <span
                className={cn(
                  'h-1.5 w-1.5 shrink-0 rounded-full',
                  ready ? 'bg-emerald-500' : 'bg-amber-500',
                )}
                aria-hidden
              />
              {status.isLoading
                ? 'Checking the model…'
                : ready
                  ? `${status.data?.model} · ${status.data?.provider}`
                  : 'Command mode — no model needed'}
            </p>
          </div>
          {!isFresh && (
            <button
              onClick={exportConversation}
              aria-label="Export this chat"
              title="Export this chat as Markdown"
              className="rounded-lg p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground"
            >
              <Download className="h-4 w-4" />
            </button>
          )}
          <button
            onClick={() => setRobotOpen(!robotOpen)}
            aria-label={robotOpen ? 'Hide the 3D companion' : 'Show the 3D companion'}
            aria-pressed={robotOpen}
            title={robotOpen ? 'Hide the 3D companion' : 'Show the 3D companion'}
            className="hidden rounded-lg p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground xl:inline-flex"
          >
            <Bot className="h-4 w-4" />
          </button>
          <button
            onClick={() => setMobileRobotOpen(true)}
            aria-label="Open the 3D companion"
            title="Open the 3D companion"
            className="rounded-lg p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground xl:hidden"
          >
            <Bot className="h-4 w-4" />
          </button>
          <button
            onClick={() => setHistoryOpen((open) => !open)}
            aria-label={historyOpen ? 'Hide chat history' : 'Show chat history'}
            aria-expanded={historyOpen}
            title={historyOpen ? 'Hide chat history' : 'Show chat history'}
            className="hidden rounded-lg p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground lg:inline-flex"
          >
            <PanelLeft className="h-4 w-4" />
          </button>
        </header>

        <div
          ref={scrollRef}
          className="oa-dot-grid oa-scroll min-h-0 flex-1 overflow-y-auto"
        >
          {visibleEntries.length === 0 ? (
            <div className="flex min-h-full items-center justify-center px-4 py-8">
              <div className="w-full max-w-2xl space-y-5">
                <div className="text-center">
                  <h2 className="flex items-center justify-center gap-2 text-xl font-semibold tracking-tight sm:text-2xl">
                    <Sparkles className="h-5 w-5 text-primary" aria-hidden />
                    What do you want to automate?
                  </h2>
                  <p className="mx-auto mt-1.5 max-w-lg text-sm text-muted-foreground">
                    Describe the outcome in plain language. I can build a workflow, create an
                    agent, run or publish automations, and explain what happened.
                  </p>
                </div>

                {status.data && !status.data.ready && (
                  <div className="rounded-xl border border-amber-500/30 bg-amber-500/[0.06] px-3 py-2.5">
                    <p className="text-xs text-muted-foreground">{status.data.install_hint}</p>
                    <Link
                      href="/settings/models"
                      className="mt-1.5 inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
                    >
                      <Radio className="h-3 w-3" aria-hidden /> Connect a model
                    </Link>
                  </div>
                )}

                <div className="flex flex-wrap justify-center gap-1.5">
                  {QUICK_PROMPTS.map((prompt) => (
                    <button
                      key={prompt}
                      onClick={() => setDraft(prompt)}
                      disabled={busy || composerDisabled}
                      className="rounded-full border border-border/70 bg-background/80 px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground disabled:opacity-50"
                    >
                      {prompt}
                    </button>
                  ))}
                </div>

                {isLoadingActiveConversation && (
                  <p className="flex items-center justify-center gap-2 text-xs text-muted-foreground">
                    <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> Opening chat…
                  </p>
                )}

                <div className="pt-1">{composer}</div>
              </div>
            </div>
          ) : (
            <div className="mx-auto w-full max-w-3xl space-y-4 px-3 py-5 sm:px-6">
              {!isVerifiedActiveConversation && detail.isLoading && activeId && (
                <p className="flex items-center gap-2 text-xs text-muted-foreground">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> Loading transcript…
                </p>
              )}
              {visibleEntries.map((entry, index) => (
                <div
                  key={index}
                  className={cn(
                    'flex flex-col gap-1.5',
                    entry.role === 'user' ? 'items-end' : 'items-start',
                  )}
                >
                  <div
                    className={cn(
                      'max-w-[92%] break-words rounded-2xl px-3.5 py-2.5 text-sm leading-6',
                      entry.role === 'user'
                        ? 'whitespace-pre-wrap rounded-br-md bg-primary text-primary-foreground'
                        : 'rounded-bl-md border border-border/70 bg-card',
                    )}
                  >
                    {entry.role === 'assistant' ? (
                      <Markdown content={entry.content} />
                    ) : (
                      entry.content
                    )}
                  </div>
                  {entry.actions && entry.actions.length > 0 && (
                    <div className="w-full max-w-[92%]">
                      <AssistantStepsCard actions={entry.actions} />
                    </div>
                  )}
                  {entry.role === 'assistant' && entry.source && (
                    <span className="px-1 text-[10px] uppercase tracking-wide text-muted-foreground">
                      {entry.source === 'commands'
                        ? 'offline commands'
                        : status.data?.provider ?? 'model'}
                    </span>
                  )}
                </div>
              ))}
              {busy && (
                <p className="flex items-center gap-2 text-xs text-muted-foreground" aria-live="polite">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> Working on it…
                </p>
              )}
            </div>
          )}
        </div>

        {!isFresh && (
          <div className="shrink-0 border-t border-border/70 bg-background px-3 py-3 sm:px-6">
            <div className="mx-auto w-full max-w-3xl">{composer}</div>
          </div>
        )}
      </section>

      {robotOpen && (
        <aside className="relative hidden w-[320px] shrink-0 border-l border-border/70 xl:flex 2xl:w-[350px]">
          <RobotCompanion controller={robot} />
        </aside>
      )}

      {mobileRobotOpen && (
        <div className="fixed inset-x-0 bottom-0 top-16 z-50 xl:hidden">
          <div
            className="absolute inset-0 bg-black/60 backdrop-blur-sm"
            onClick={() => setMobileRobotOpen(false)}
            aria-hidden
          />
          <div className="relative h-full w-full overflow-hidden">
            <RobotCompanion
              controller={robot}
              className="h-full"
              onClose={() => setMobileRobotOpen(false)}
            />
          </div>
        </div>
      )}

      {mobileHistoryOpen && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div
            className="absolute inset-0 bg-black/50"
            onClick={() => setMobileHistoryOpen(false)}
            aria-hidden
          />
          <aside className="relative flex h-full w-72 flex-col border-r border-border bg-background">
            {sidebar}
            <button
              onClick={() => setMobileHistoryOpen(false)}
              aria-label="Close chat history"
              className="absolute right-2 top-3 rounded-lg p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground"
            >
              <X className="h-4 w-4" />
            </button>
          </aside>
        </div>
      )}
    </div>
  );
}
