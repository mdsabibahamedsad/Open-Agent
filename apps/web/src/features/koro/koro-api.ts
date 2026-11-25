'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { useOrganization } from '@/context/OrganizationContext';
import type { KoroRequestContext } from './context';

export interface KoroStatus {
  ready: boolean;
  provider: string;
  model: string;
  model_size: string;
  base_url: string;
  models: string[];
  install_hint: string;
  api_key_set: boolean;
  local: boolean;
  customized: boolean;
}

export interface KoroSettings {
  base_url: string;
  model: string;
  provider: string;
  local: boolean;
  api_key_set: boolean;
  customized: boolean;
  default_base_url: string;
  default_model: string;
  models: string[];
}

export interface KoroSettingsInput {
  base_url: string;
  model: string;
  api_key?: string;
  clear_api_key?: boolean;
}

export interface KoroAction {
  type: string;
  /** `confirmation_required` carries a token to replay the action. */
  status: 'ok' | 'failed' | 'confirmation_required';
  detail: string;
  workflow_id?: string | null;
  data?: Record<string, unknown> | null;
}

export interface KoroChatResult {
  reply: string;
  source: 'model' | 'commands';
  actions: KoroAction[];
  workflow_id?: string | null;
  conversation_id?: string | null;
}

/** One saved assistant transcript (the full-page chat history). */
export interface AssistantConversation {
  id: string;
  title: string;
  message_count: number;
  created_at: string;
  updated_at: string;
}

/** An action as stored on a transcript message (no generated definition). */
export interface StoredAssistantAction {
  type: string;
  status: 'ok' | 'failed' | 'confirmation_required';
  detail: string;
  workflow_id?: string | null;
  /** Small identifiers kept for deep links (run id, version, restored_from). */
  data?: Record<string, unknown> | null;
}

export interface AssistantConversationMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  created_at: string;
  source?: string | null;
  actions?: StoredAssistantAction[];
}

export interface AssistantConversationDetail extends AssistantConversation {
  messages: AssistantConversationMessage[];
}

export interface KoroMessage {
  role: 'user' | 'assistant';
  content: string;
}

export interface LocalModel {
  name: string;
  size_bytes?: number | null;
  parameter_size?: string | null;
  quantization?: string | null;
  family?: string | null;
  modified_at?: string | number | null;
}

export interface LocalRuntime {
  id: string;
  name: string;
  base_url: string;
  api: 'ollama' | 'openai' | string;
  can_pull: boolean;
  install_url: string;
  reachable: boolean;
  version?: string | null;
  models: LocalModel[];
  error?: string | null;
}

export interface RecommendedModel {
  name: string;
  label: string;
  size: string;
  size_bytes: number;
  min_ram_gb: number;
  description: string;
  best_for: string;
}

export interface LocalHardware {
  platform: string;
  machine: string;
  cpu_count?: number | null;
  memory_bytes?: number | null;
  memory_gb?: number | null;
  disk_free_bytes?: number | null;
  disk_free_gb?: number | null;
}

export interface LocalModelsResponse {
  runtimes: LocalRuntime[];
  recommended: RecommendedModel[];
  hardware: LocalHardware;
  install: {
    ollama_installed: boolean;
    ollama_download_url: string;
    ollama_docs_url: string;
    lmstudio_download_url: string;
    instructions: Record<string, string>;
  };
  configured: {
    base_url: string;
    model: string;
    provider: string;
    local: boolean;
    ready: boolean;
    installed: boolean;
  };
}

export interface PullJob {
  id: string;
  model: string;
  base_url: string;
  status: 'running' | 'done' | 'error' | 'cancelled';
  progress: number;
  completed: number;
  total: number;
  detail: string;
  error: string;
  started_at: number;
  updated_at: number;
}

export interface TestModelResult {
  ok: boolean;
  latency_ms: number;
  reply: string;
  base_url: string;
  model: string;
  error?: string | null;
}

export interface ProviderProbe {
  ok: boolean;
  provider: string;
  local: boolean;
  base_url: string;
  models: string[];
  error?: string | null;
}

function base(orgId: string | null): string {
  return `/organizations/${encodeURIComponent(orgId ?? '')}/copilot`;
}

export function useKoroStatus(enabled = true) {
  const { currentOrgId } = useOrganization();
  return useQuery({
    queryKey: ['koro', 'status', currentOrgId],
    queryFn: () => api.get<KoroStatus>(`${base(currentOrgId)}/status`),
    enabled: enabled && !!currentOrgId,
    staleTime: 20_000,
    retry: false,
  });
}

export function useKoroSettings(enabled = true) {
  const { currentOrgId } = useOrganization();
  return useQuery({
    queryKey: ['koro', 'settings', currentOrgId],
    queryFn: () => api.get<KoroSettings>(`${base(currentOrgId)}/settings`),
    enabled: enabled && !!currentOrgId,
    staleTime: 20_000,
    retry: false,
  });
}

export function useUpdateKoroSettings() {
  const { currentOrgId } = useOrganization();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: KoroSettingsInput) =>
      api.put<KoroSettings>(`${base(currentOrgId)}/settings`, input),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['koro'] });
    },
  });
}

export function useKoroChat() {
  const { currentOrgId } = useOrganization();
  return useMutation({
    mutationFn: (input: {
      message: string;
      workflow_id?: string;
      history?: KoroMessage[];
      input?: Record<string, unknown>;
      /** The unsaved canvas, so edits start from what the user sees. */
      definition?: Record<string, unknown>;
      /** Return a validated definition instead of persisting a version. */
      preview?: boolean;
      /** Continue an existing assistant transcript. */
      conversation_id?: string;
      /** Start and save a new transcript with this turn. */
      persist?: boolean;
      /** Route / open-workflow context for the system prompt. */
      context?: KoroRequestContext;
      /** Per-chat model override; the saved organization default is untouched. */
      model?: string;
      /** Local endpoint for the override (hosted providers stay in Settings). */
      base_url?: string;
      /** Cancel the in-flight reply (the composer's Stop button). */
      signal?: AbortSignal;
    }) => {
      const { signal, ...body } = input;
      return api.post<KoroChatResult>(`${base(currentOrgId)}/chat`, body, { signal });
    },
  });
}

// ---------------------------------------------------------------------------
// Chat history (assistant transcripts)
// ---------------------------------------------------------------------------

export function useAssistantConversations(enabled = true) {
  const { currentOrgId } = useOrganization();
  return useQuery({
    queryKey: ['koro', 'conversations', currentOrgId],
    queryFn: () =>
      api.get<AssistantConversation[]>(`${base(currentOrgId)}/conversations`),
    enabled: enabled && !!currentOrgId,
    staleTime: 10_000,
    retry: false,
  });
}

export function useAssistantConversation(id: string | null) {
  const { currentOrgId } = useOrganization();
  return useQuery({
    queryKey: ['koro', 'conversation', currentOrgId, id],
    queryFn: ({ signal }) =>
      api.get<AssistantConversationDetail>(
        `${base(currentOrgId)}/conversations/${encodeURIComponent(id ?? '')}`,
        undefined,
        { signal },
      ),
    enabled: !!currentOrgId && !!id,
    staleTime: 0,
    gcTime: 0,
    retry: false,
  });
}

export function useRenameAssistantConversation() {
  const { currentOrgId } = useOrganization();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { id: string; title: string }) =>
      api.patch<AssistantConversation>(
        `${base(currentOrgId)}/conversations/${encodeURIComponent(input.id)}`,
        { title: input.title },
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['koro', 'conversations'] });
    },
  });
}

export type DeleteAssistantConversationInput =
  | string
  | {
      id: string;
      orgId?: string | null;
    };

export function useDeleteAssistantConversation() {
  const { currentOrgId } = useOrganization();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: DeleteAssistantConversationInput) => {
      const id = typeof input === 'string' ? input : input.id;
      const orgId = typeof input === 'string' ? currentOrgId : (input.orgId ?? currentOrgId);
      const result = await api.delete<{ deleted: boolean; conversation_id: string }>(
        `${base(orgId)}/conversations/${encodeURIComponent(id)}`,
      );
      return { ...result, orgId, requestedId: id };
    },
    onSuccess: (data) => {
      const normalizedId = data.requestedId.trim().toLowerCase();
      void queryClient.invalidateQueries({
        queryKey: ['koro', 'conversations', data.orgId],
      });
      queryClient.removeQueries({
        queryKey: ['koro', 'conversation', data.orgId],
        predicate: (query) => {
          const cachedId = query.queryKey[3];
          return (
            cachedId === data.requestedId ||
            (typeof cachedId === 'string' && cachedId.trim().toLowerCase() === normalizedId)
          );
        },
      });
    },
  });
}

// ---------------------------------------------------------------------------
// Local model runtime management
// ---------------------------------------------------------------------------

export function useLocalModels(enabled = true) {
  const { currentOrgId } = useOrganization();
  return useQuery({
    queryKey: ['koro', 'runtimes', currentOrgId],
    queryFn: () => api.get<LocalModelsResponse>(`${base(currentOrgId)}/runtimes`),
    enabled: enabled && !!currentOrgId,
    staleTime: 15_000,
    retry: false,
  });
}

export function usePullModel() {
  const { currentOrgId } = useOrganization();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { model: string; base_url?: string }) =>
      api.post<PullJob>(`${base(currentOrgId)}/models/pull`, input),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['koro'] });
    },
  });
}

export function usePullJob(jobId: string | null) {
  const { currentOrgId } = useOrganization();
  return useQuery({
    queryKey: ['koro', 'pull', currentOrgId, jobId],
    queryFn: () => api.get<PullJob>(`${base(currentOrgId)}/models/pull/${jobId}`),
    enabled: !!currentOrgId && !!jobId,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === 'running' ? 900 : false;
    },
    retry: false,
  });
}

export function useCancelPull() {
  const { currentOrgId } = useOrganization();
  return useMutation({
    mutationFn: (jobId: string) =>
      api.post<PullJob>(`${base(currentOrgId)}/models/pull/${jobId}/cancel`, {}),
  });
}

export function useDeleteModel() {
  const { currentOrgId } = useOrganization();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { model: string; base_url?: string }) => {
      const params = new URLSearchParams({ model: input.model });
      if (input.base_url) params.set('base_url', input.base_url);
      return api.delete<{ deleted: boolean; model: string }>(
        `${base(currentOrgId)}/models?${params.toString()}`,
      );
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['koro'] });
    },
  });
}

export function useActivateModel() {
  const { currentOrgId } = useOrganization();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { base_url: string; model: string }) =>
      api.post<KoroSettings>(`${base(currentOrgId)}/models/activate`, input),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['koro'] });
    },
  });
}

export function useTestModel() {
  const { currentOrgId } = useOrganization();
  return useMutation({
    mutationFn: (input: { model: string; base_url?: string }) =>
      api.post<TestModelResult>(`${base(currentOrgId)}/models/test`, input),
  });
}

/**
 * Ask any OpenAI-compatible endpoint which models it serves before saving it.
 * The key is only used for this probe; saving goes through `useUpdateKoroSettings`.
 */
export function useProviderModels() {
  const { currentOrgId } = useOrganization();
  return useMutation({
    mutationFn: (input: { base_url: string; api_key?: string }) =>
      api.post<ProviderProbe>(`${base(currentOrgId)}/providers/models`, input),
  });
}
