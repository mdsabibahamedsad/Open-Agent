'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { useOrganization } from '@/context/OrganizationContext';
import type { ConnectionRecord, ConnectorAction, ConnectorSummary, CredentialRecord, WebhookRecord } from './types';

function connectorsBase(orgId: string | null): string {
  return `/organizations/${orgId}/connectors`;
}

function connectionsBase(orgId: string | null): string {
  return `/organizations/${orgId}/integration-connections`;
}

export const integrationKeys = {
  all: ['integrations'] as const,
  catalog: (org: string | null, params?: object) => ['integrations', 'catalog', org, params] as const,
  detail: (org: string | null, id: string) => ['integrations', 'detail', org, id] as const,
  connections: (org: string | null, params?: object) => ['integrations', 'connections', org, params] as const,
  credentials: (org: string | null) => ['integrations', 'credentials', org] as const,
  webhooks: (org: string | null) => ['integrations', 'webhooks', org] as const,
};

export function useConnectorCatalog(params?: { category?: string; trust?: string; search?: string }) {
  const { currentOrgId } = useOrganization();
  const query = useQuery({
    queryKey: integrationKeys.catalog(currentOrgId, params),
    queryFn: async () => {
      const res = await api.get<{ items: ConnectorSummary[]; total: number }>(connectorsBase(currentOrgId), {
        category: params?.category || undefined,
        trust: params?.trust || undefined,
        search: params?.search || undefined,
      });
      return { items: res.items ?? [], total: res.total ?? 0 };
    },
    staleTime: 30_000,
  });
  return { items: query.data?.items ?? [], total: query.data?.total ?? 0, isLoading: query.isLoading, error: query.error, refetch: query.refetch };
}

export function useConnector(id: string) {
  const { currentOrgId } = useOrganization();
  const query = useQuery({
    queryKey: integrationKeys.detail(currentOrgId, id),
    queryFn: () => api.get<Record<string, unknown>>(`${connectorsBase(currentOrgId)}/${id}`),
    staleTime: 30_000,
  });
  return { connector: query.data, isLoading: query.isLoading, error: query.error, refetch: query.refetch };
}

export function useConnectorActions(id: string) {
  const { currentOrgId } = useOrganization();
  const query = useQuery({
    queryKey: [...integrationKeys.detail(currentOrgId, id), 'actions'],
    queryFn: () => api.get<{ items: ConnectorAction[] }>(`${connectorsBase(currentOrgId)}/${id}/actions`),
    staleTime: 30_000,
  });
  return { actions: query.data?.items ?? [], isLoading: query.isLoading, error: query.error };
}

export function useConnections(params?: { connector_id?: string; status?: string }) {
  const { currentOrgId } = useOrganization();
  const query = useQuery({
    queryKey: integrationKeys.connections(currentOrgId, params),
    queryFn: async () => {
      const res = await api.get<{ items: ConnectionRecord[]; total: number }>(connectionsBase(currentOrgId), {
        connector_id: params?.connector_id || undefined,
        status: params?.status || undefined,
        limit: 100,
      });
      return { items: res.items ?? [], total: res.total ?? 0 };
    },
    staleTime: 10_000,
    refetchInterval: 15_000,
  });
  return { items: query.data?.items ?? [], total: query.data?.total ?? 0, isLoading: query.isLoading, error: query.error, refetch: query.refetch };
}

export function useConnectionMutations() {
  const { currentOrgId } = useOrganization();
  const qc = useQueryClient();
  const invalidate = () => qc.invalidateQueries({ queryKey: integrationKeys.all });
  const create = useMutation({
    mutationFn: (body: Record<string, unknown>) => api.post<ConnectionRecord>(connectionsBase(currentOrgId), body),
    onSuccess: invalidate,
  });
  const test = useMutation({
    mutationFn: (id: string) => api.post(`${connectionsBase(currentOrgId)}/${id}/test`, {}),
    onSuccess: invalidate,
  });
  const disconnect = useMutation({
    mutationFn: (id: string) => api.post(`${connectionsBase(currentOrgId)}/${id}/disconnect`, {}),
    onSuccess: invalidate,
  });
  const remove = useMutation({
    mutationFn: (id: string) => api.delete(`${connectionsBase(currentOrgId)}/${id}`),
    onSuccess: invalidate,
  });
  const update = useMutation({
    mutationFn: (args: { id: string; patch: Record<string, unknown> }) =>
      api.patch(`${connectionsBase(currentOrgId)}/${args.id}`, args.patch),
    onSuccess: invalidate,
  });
  const execute = useMutation({
    mutationFn: (args: { id: string; action_id: string; input?: Record<string, unknown>; approval_id?: string }) =>
      api.post(`${connectionsBase(currentOrgId)}/${args.id}/execute`, {
        action_id: args.action_id,
        input: args.input ?? {},
        approval_id: args.approval_id,
      }),
    onSuccess: invalidate,
  });
  return { create, test, disconnect, remove, update, execute };
}

export function useCredentials() {
  const { currentOrgId } = useOrganization();
  const query = useQuery({
    queryKey: integrationKeys.credentials(currentOrgId),
    queryFn: () =>
      api.get<{ items: CredentialRecord[] }>(`/organizations/${currentOrgId}/credentials`),
    staleTime: 30_000,
  });
  return { credentials: query.data?.items ?? [], isLoading: query.isLoading, error: query.error, refetch: query.refetch };
}

export function useCredentialMutations() {
  const { currentOrgId } = useOrganization();
  const qc = useQueryClient();
  const invalidate = () => qc.invalidateQueries({ queryKey: integrationKeys.credentials(currentOrgId) });
  const create = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api.post<CredentialRecord>(`/organizations/${currentOrgId}/credentials`, body),
    onSuccess: invalidate,
  });
  const rotate = useMutation({
    mutationFn: (args: { id: string; secrets: Record<string, unknown> }) =>
      api.post(`/organizations/${currentOrgId}/credentials/${args.id}/rotate`, { secrets: args.secrets, name: 'rotated', provider: 'rotated' }),
    onSuccess: invalidate,
  });
  const revoke = useMutation({
    mutationFn: (id: string) => api.post(`/organizations/${currentOrgId}/credentials/${id}/revoke`, {}),
    onSuccess: invalidate,
  });
  const remove = useMutation({
    mutationFn: (id: string) => api.delete(`/organizations/${currentOrgId}/credentials/${id}`),
    onSuccess: invalidate,
  });
  return { create, rotate, revoke, remove };
}

export function useWebhooks(connectionId?: string) {
  const { currentOrgId } = useOrganization();
  const query = useQuery({
    queryKey: integrationKeys.webhooks(currentOrgId),
    queryFn: () =>
      api.get<{ items: WebhookRecord[] }>(`/organizations/${currentOrgId}/connector-webhooks`, {
        connection_id: connectionId || undefined,
      }),
    staleTime: 15_000,
  });
  return { webhooks: query.data?.items ?? [], isLoading: query.isLoading, error: query.error, refetch: query.refetch };
}

export function useWebhookMutations() {
  const { currentOrgId } = useOrganization();
  const qc = useQueryClient();
  const invalidate = () => qc.invalidateQueries({ queryKey: integrationKeys.webhooks(currentOrgId) });
  const create = useMutation({
    mutationFn: (body: { connection_id: string; endpoint: string; event_types?: string[] }) =>
      api.post(`/organizations/${currentOrgId}/connector-webhooks?connection_id=${body.connection_id}`, {
        endpoint: body.endpoint,
        event_types: body.event_types ?? [],
      }),
    onSuccess: invalidate,
  });
  const rotate = useMutation({
    mutationFn: (id: string) =>
      api.post(`/organizations/${currentOrgId}/connector-webhooks/${id}/rotate`, {}),
    onSuccess: invalidate,
  });
  const remove = useMutation({
    mutationFn: (id: string) => api.delete(`/organizations/${currentOrgId}/connector-webhooks/${id}`),
    onSuccess: invalidate,
  });
  return { create, rotate, remove };
}

export function useSearchIntegrations(query: string, kind = 'action') {
  const { currentOrgId } = useOrganization();
  const enabled = query.trim().length > 1;
  const result = useQuery({
    queryKey: ['integrations', 'search', currentOrgId, query, kind],
    queryFn: () =>
      api.get<Record<string, unknown[]>>(`/organizations/${currentOrgId}/connectors/search`, {
        q: query,
        kind,
      }),
    enabled,
    staleTime: 30_000,
  });
  return { results: result.data, isLoading: result.isLoading, error: result.error };
}
