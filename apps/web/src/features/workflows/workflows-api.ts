'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, toUserMessage } from '@/lib/api';
import { useOrganization } from '@/context/OrganizationContext';
import type {
  WorkflowDefinition,
  WorkflowDetail,
  WorkflowExecutionRecord,
  WorkflowRecord,
  WorkflowVersionRecord,
} from './types';

interface Paginated<T> {
  data: T[];
  meta: { page: number; page_size: number; total_items: number; total_pages: number };
}

function base(orgId: string | null): string {
  return `/organizations/${orgId}/workflows`;
}

export const workflowKeys = {
  all: ['workflows'] as const,
  list: (org: string | null, params?: object) => ['workflows', 'list', org, params] as const,
  detail: (org: string | null, id: string) => ['workflows', 'detail', org, id] as const,
  versions: (org: string | null, id: string) => ['workflows', 'versions', org, id] as const,
  executions: (org: string | null, id: string) => ['workflows', 'executions', org, id] as const,
};

export function useWorkflows(params?: { search?: string; status?: string; page?: number; pageSize?: number }) {
  const { currentOrgId } = useOrganization();
  const query = useQuery({
    queryKey: workflowKeys.list(currentOrgId, params),
    queryFn: async () => {
      const res = await api.get<Paginated<WorkflowRecord> | WorkflowRecord[]>(base(currentOrgId), {
        search: params?.search || undefined,
        status: params?.status || undefined,
        page: params?.page ?? 1,
        page_size: params?.pageSize ?? 20,
      });
      if (Array.isArray(res)) return { items: res, total: res.length };
      return { items: res.data ?? [], total: res.meta?.total_items ?? (res.data ?? []).length };
    },
    staleTime: 30_000,
  });
  return {
    items: query.data?.items ?? [],
    total: query.data?.total ?? 0,
    isLoading: query.isLoading,
    error: query.error ? toUserMessage(query.error) : null,
    refetch: query.refetch,
  };
}

export function useWorkflow(id: string) {
  const { currentOrgId } = useOrganization();
  const query = useQuery({
    queryKey: workflowKeys.detail(currentOrgId, id),
    queryFn: () => api.get<WorkflowDetail>(`${base(currentOrgId)}/${id}`),
    enabled: !!currentOrgId && !!id,
    staleTime: 15_000,
  });
  return {
    workflow: query.data ?? null,
    isLoading: query.isLoading,
    error: query.error ? toUserMessage(query.error) : null,
    refetch: query.refetch,
  };
}

export function useWorkflowVersions(id: string) {
  const { currentOrgId } = useOrganization();
  const query = useQuery({
    queryKey: workflowKeys.versions(currentOrgId, id),
    queryFn: async () => {
      const res = await api.get<Paginated<WorkflowVersionRecord> | WorkflowVersionRecord[]>(
        `${base(currentOrgId)}/${id}/versions`,
      );
      if (Array.isArray(res)) return res;
      return res.data ?? [];
    },
    enabled: !!currentOrgId && !!id,
    staleTime: 30_000,
  });
  return { versions: query.data ?? [], isLoading: query.isLoading, refetch: query.refetch };
}

export function useWorkflowExecutions(id: string, page = 1) {
  const { currentOrgId } = useOrganization();
  const query = useQuery({
    queryKey: workflowKeys.executions(currentOrgId, `${id}?p=${page}`),
    queryFn: async () => {
      const res = await api.get<Paginated<WorkflowExecutionRecord> | WorkflowExecutionRecord[]>(
        `${base(currentOrgId)}/${id}/executions`,
        { page, page_size: 20 },
      );
      if (Array.isArray(res)) return { items: res, total: res.length };
      return { items: res.data ?? [], total: res.meta?.total_items ?? 0 };
    },
    enabled: !!currentOrgId && !!id,
    staleTime: 15_000,
  });
  return {
    items: query.data?.items ?? [],
    total: query.data?.total ?? 0,
    isLoading: query.isLoading,
    refetch: query.refetch,
  };
}

export interface ServerIssue {
  code: string;
  message: string;
  severity: 'error' | 'warning';
  node_id?: string;
  field?: string;
  edge_id?: string;
}

export function useValidateDefinition() {
  const { currentOrgId } = useOrganization();
  return useMutation({
    mutationFn: (definition: WorkflowDefinition) =>
      api.post<{ valid: boolean; errors: ServerIssue[]; warnings: ServerIssue[] }>(
        `${base(currentOrgId)}/validate`,
        { definition },
      ),
  });
}

export function useWorkflowMutations() {
  const { currentOrgId } = useOrganization();
  const queryClient = useQueryClient();
  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: workflowKeys.all });
  };

  const create = useMutation({
    mutationFn: (input: { name: string; slug?: string; description?: string; tags?: string[]; definition?: WorkflowDefinition }) =>
      api.post<WorkflowDetail>(base(currentOrgId), input),
    onSuccess: invalidate,
  });

  const update = useMutation({
    mutationFn: (input: { id: string; name?: string; description?: string; tags?: string[]; definition?: WorkflowDefinition; expected_updated_at?: string }) =>
      api.patch<WorkflowDetail>(`${base(currentOrgId)}/${input.id}`, {
        name: input.name,
        description: input.description,
        tags: input.tags,
        definition: input.definition,
        expected_updated_at: input.expected_updated_at,
      }),
    onSuccess: invalidate,
  });

  const publish = useMutation({
    mutationFn: (id: string) => api.post<WorkflowDetail>(`${base(currentOrgId)}/${id}/publish`),
    onSuccess: invalidate,
  });

  const unpublish = useMutation({
    mutationFn: (id: string) => api.post<WorkflowDetail>(`${base(currentOrgId)}/${id}/unpublish`),
    onSuccess: invalidate,
  });

  const duplicate = useMutation({
    mutationFn: (id: string) => api.post<WorkflowDetail>(`${base(currentOrgId)}/${id}/duplicate`),
    onSuccess: invalidate,
  });

  const remove = useMutation({
    mutationFn: (id: string) => api.delete<void>(`${base(currentOrgId)}/${id}`),
    onSuccess: invalidate,
  });

  const restore = useMutation({
    mutationFn: (input: { id: string; version: string }) =>
      api.post<WorkflowDetail>(`${base(currentOrgId)}/${input.id}/restore`, { version: input.version }),
    onSuccess: invalidate,
  });

  const importWorkflow = useMutation({
    mutationFn: (input: { payload: Record<string, unknown>; name?: string; slug?: string; description?: string }) =>
      api.post<WorkflowDetail>(`${base(currentOrgId)}/import`, input),
    onSuccess: invalidate,
  });

  const execute = useMutation({
    mutationFn: (id: string) => api.post<unknown>(`${base(currentOrgId)}/${id}/execute`, {}),
  });

  return { create, update, publish, unpublish, duplicate, remove, restore, importWorkflow, execute };
}
