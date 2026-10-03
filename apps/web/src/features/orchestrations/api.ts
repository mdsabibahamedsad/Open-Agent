"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, toUserMessage } from "@/lib/api";
import { useOrganization } from "@/context/OrganizationContext";
import type {
  AgentMessage,
  OrchestrationEvent,
  OrchestrationSummary,
  OrchestrationTask,
  RunAgentGroup,
} from "./types";
import { TERMINAL_RUN_STATUSES } from "./types";

interface Paginated<T> {
  data: T[];
  meta: { total_items: number };
}

function base(orgId: string | null): string {
  return `/organizations/${orgId}/orchestrations`;
}

export const orchKeys = {
  all: ["orchestrations"] as const,
  list: (org: string | null, params?: object) =>
    ["orchestrations", "list", org, params] as const,
  detail: (org: string | null, id: string) =>
    ["orchestrations", "detail", org, id] as const,
  tasks: (org: string | null, id: string) =>
    ["orchestrations", "tasks", org, id] as const,
  agents: (org: string | null, id: string) =>
    ["orchestrations", "agents", org, id] as const,
  messages: (org: string | null, id: string) =>
    ["orchestrations", "messages", org, id] as const,
  events: (org: string | null, id: string) =>
    ["orchestrations", "events", org, id] as const,
};

export function useOrchestrations(params?: {
  status?: string;
  page?: number;
  pageSize?: number;
}) {
  const { currentOrgId } = useOrganization();
  const query = useQuery({
    queryKey: orchKeys.list(currentOrgId, params),
    queryFn: async () => {
      const res = await api.get<Paginated<OrchestrationSummary>>(
        base(currentOrgId),
        {
          status: params?.status || undefined,
          page: params?.page ?? 1,
          page_size: params?.pageSize ?? 20,
        },
      );
      return { items: res.data ?? [], total: res.meta?.total_items ?? 0 };
    },
    enabled: !!currentOrgId,
    staleTime: 15_000,
  });
  return {
    items: query.data?.items ?? [],
    total: query.data?.total ?? 0,
    isLoading: query.isLoading,
    error: query.error ? toUserMessage(query.error) : null,
    refetch: query.refetch,
  };
}

export function useOrchestration(id: string) {
  const { currentOrgId } = useOrganization();
  const query = useQuery({
    queryKey: orchKeys.detail(currentOrgId, id),
    queryFn: () => api.get<OrchestrationSummary>(`${base(currentOrgId)}/${id}`),
    enabled: !!currentOrgId && !!id,
    refetchInterval: (q) => {
      const data = q.state.data as OrchestrationSummary | undefined;
      if (!data) return false;
      return TERMINAL_RUN_STATUSES.includes(data.status) ? false : 3000;
    },
  });
  return {
    run: query.data ?? null,
    isLoading: query.isLoading,
    error: query.error ? toUserMessage(query.error) : null,
    refetch: query.refetch,
  };
}

export function useOrchestrationTasks(id: string) {
  const { currentOrgId } = useOrganization();
  const query = useQuery({
    queryKey: orchKeys.tasks(currentOrgId, id),
    queryFn: () =>
      api.get<OrchestrationTask[]>(`${base(currentOrgId)}/${id}/tasks`),
    enabled: !!currentOrgId && !!id,
    refetchInterval: 3000,
  });
  const items = Array.isArray(query.data)
    ? query.data
    : ((query.data as unknown as { data?: OrchestrationTask[] })?.data ?? []);
  return {
    tasks: items,
    isLoading: query.isLoading,
    error: query.error ? toUserMessage(query.error) : null,
    refetch: query.refetch,
  };
}

export function useOrchestrationAgents(id: string) {
  const { currentOrgId } = useOrganization();
  const query = useQuery({
    queryKey: orchKeys.agents(currentOrgId, id),
    queryFn: () =>
      api.get<{ data: RunAgentGroup[] }>(`${base(currentOrgId)}/${id}/agents`),
    enabled: !!currentOrgId && !!id,
    refetchInterval: 3000,
  });
  return { groups: query.data?.data ?? [], isLoading: query.isLoading };
}

export function useOrchestrationMessages(id: string) {
  const { currentOrgId } = useOrganization();
  const query = useQuery({
    queryKey: orchKeys.messages(currentOrgId, id),
    queryFn: () =>
      api.get<AgentMessage[]>(`${base(currentOrgId)}/${id}/messages`),
    enabled: !!currentOrgId && !!id,
    refetchInterval: 5000,
  });
  const items = Array.isArray(query.data) ? query.data : [];
  return { messages: items, isLoading: query.isLoading };
}

export function useOrchestrationEvents(id: string) {
  const { currentOrgId } = useOrganization();
  const query = useQuery({
    queryKey: orchKeys.events(currentOrgId, id),
    queryFn: () =>
      api.get<OrchestrationEvent[]>(`${base(currentOrgId)}/${id}/events`),
    enabled: !!currentOrgId && !!id,
    refetchInterval: 5000,
  });
  const items = Array.isArray(query.data) ? query.data : [];
  return { events: items, isLoading: query.isLoading };
}

export function useOrchestrationMutations(id: string) {
  const { currentOrgId } = useOrganization();
  const qc = useQueryClient();
  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: orchKeys.detail(currentOrgId, id) });
    void qc.invalidateQueries({ queryKey: orchKeys.tasks(currentOrgId, id) });
    void qc.invalidateQueries({ queryKey: orchKeys.events(currentOrgId, id) });
  };
  // Hooks must be unconditional: build each mutation explicitly via a
  // properly-named custom hook (same call order on every render).
  const useOrchMutation = (path: string) =>
    useMutation({
      mutationFn: (body?: unknown) =>
        api.post(`${base(currentOrgId)}/${id}${path}`, body ?? {}),
      onSettled: invalidate,
    });
  return {
    start: useOrchMutation("/start"),
    pause: useOrchMutation("/pause"),
    resume: useOrchMutation("/resume"),
    cancel: useOrchMutation("/cancel"),
  };
}

export function useCreateOrchestration() {
  const { currentOrgId } = useOrganization();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { objective: string; template?: string }) =>
      api.post<OrchestrationSummary>(base(currentOrgId), body),
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: orchKeys.all });
    },
  });
}

export function useTaskMutations(runId: string) {
  const { currentOrgId } = useOrganization();
  const qc = useQueryClient();
  const invalidate = () => {
    void qc.invalidateQueries({
      queryKey: orchKeys.tasks(currentOrgId, runId),
    });
  };
  return {
    retry: useMutation({
      mutationFn: (taskId: string) =>
        api.post(`${base(currentOrgId)}/${runId}/tasks/${taskId}/retry`, {}),
      onSettled: invalidate,
    }),
    reassign: useMutation({
      mutationFn: (input: { taskId: string; agent_id: string }) =>
        api.post(
          `${base(currentOrgId)}/${runId}/tasks/${input.taskId}/reassign`,
          {
            agent_id: input.agent_id,
          },
        ),
      onSettled: invalidate,
    }),
  };
}
