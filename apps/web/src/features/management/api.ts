'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, toUserMessage } from '@/lib/api';
import { useOrganization } from '@/context/OrganizationContext';
import type {
  Delegation,
  DynamicTeam,
  Escalation,
  Handoff,
  ManagerConsole,
  OrgChart,
  Review,
} from './types';

function base(orgId: string | null): string {
  return `/organizations/${orgId}/management`;
}

export const mgmtKeys = {
  all: ['management'] as const,
  delegations: (org: string | null, run?: string) =>
    ['management', 'delegations', org, run] as const,
  handoffs: (org: string | null, run?: string) => ['management', 'handoffs', org, run] as const,
  escalations: (org: string | null) => ['management', 'escalations', org] as const,
  teams: (org: string | null, run?: string) => ['management', 'teams', org, run] as const,
  reviews: (org: string | null, task?: string) => ['management', 'reviews', org, task] as const,
  console: (org: string | null, run?: string) => ['management', 'console', org, run] as const,
  chart: (org: string | null) => ['management', 'chart', org] as const,
};

async function list<T>(path: string): Promise<T[]> {
  const res = await api.get<{ data: T[] } | T[]>(path);
  if (Array.isArray(res)) return res;
  return res.data ?? [];
}

export function useDelegations(runId?: string) {
  const { currentOrgId } = useOrganization();
  const query = useQuery({
    queryKey: mgmtKeys.delegations(currentOrgId, runId),
    queryFn: () =>
      list<Delegation>(
        `${base(currentOrgId)}/delegations${runId ? `?run_id=${runId}` : ''}`,
      ),
    enabled: !!currentOrgId,
    refetchInterval: 5000,
  });
  return { items: query.data ?? [], isLoading: query.isLoading };
}

export function useHandoffs(runId?: string) {
  const { currentOrgId } = useOrganization();
  const query = useQuery({
    queryKey: mgmtKeys.handoffs(currentOrgId, runId),
    queryFn: () =>
      list<Handoff>(`${base(currentOrgId)}/handoffs${runId ? `?run_id=${runId}` : ''}`),
    enabled: !!currentOrgId,
    refetchInterval: 5000,
  });
  return { items: query.data ?? [], isLoading: query.isLoading };
}

export function useEscalations() {
  const { currentOrgId } = useOrganization();
  const query = useQuery({
    queryKey: mgmtKeys.escalations(currentOrgId),
    queryFn: () => list<Escalation>(`${base(currentOrgId)}/escalations`),
    enabled: !!currentOrgId,
    refetchInterval: 5000,
  });
  return { items: query.data ?? [], isLoading: query.isLoading, refetch: query.refetch };
}

export function useTeams(runId?: string) {
  const { currentOrgId } = useOrganization();
  const query = useQuery({
    queryKey: mgmtKeys.teams(currentOrgId, runId),
    queryFn: () => list<DynamicTeam>(`${base(currentOrgId)}/teams${runId ? `?run_id=${runId}` : ''}`),
    enabled: !!currentOrgId,
    refetchInterval: 5000,
  });
  return { items: query.data ?? [], isLoading: query.isLoading };
}

export function useReviews(taskId?: string) {
  const { currentOrgId } = useOrganization();
  const query = useQuery({
    queryKey: mgmtKeys.reviews(currentOrgId, taskId),
    queryFn: () =>
      list<Review>(`${base(currentOrgId)}/reviews${taskId ? `?task_id=${taskId}` : ''}`),
    enabled: !!currentOrgId,
    refetchInterval: 5000,
  });
  return { items: query.data ?? [], isLoading: query.isLoading, refetch: query.refetch };
}

export function useManagerConsole(runId?: string) {
  const { currentOrgId } = useOrganization();
  const query = useQuery({
    queryKey: mgmtKeys.console(currentOrgId, runId),
    queryFn: () =>
      api.get<ManagerConsole>(`${base(currentOrgId)}/console${runId ? `?run_id=${runId}` : ''}`),
    enabled: !!currentOrgId,
    refetchInterval: 5000,
  });
  return { console: query.data ?? null, isLoading: query.isLoading };
}

export function useOrgChart() {
  const { currentOrgId } = useOrganization();
  const query = useQuery({
    queryKey: mgmtKeys.chart(currentOrgId),
    queryFn: () => api.get<OrgChart>(`${base(currentOrgId)}/organization/chart`),
    enabled: !!currentOrgId,
    staleTime: 30_000,
  });
  return { chart: query.data ?? null, isLoading: query.isLoading };
}

export function useManagementMutation(path: string, method: 'post' | 'delete' = 'post') {
  const { currentOrgId } = useOrganization();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body?: unknown) =>
      method === 'post'
        ? api.post(`${base(currentOrgId)}${path}`, body ?? {})
        : api.delete(`${base(currentOrgId)}${path}`),
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: mgmtKeys.all });
    },
  });
}

/** Live event stream over SSE with polling fallback handled by callers. */
export function streamUrl(orgId: string | null, runId: string, since?: string): string | null {
  if (!orgId || typeof window === 'undefined') return null;
  const baseUrl =
    process.env.NEXT_PUBLIC_API_URL?.replace(/\/api\/v1\/?$/, '') ?? 'http://localhost:8000';
  const params = since ? `?since=${encodeURIComponent(since)}` : '';
  return `${baseUrl}/api/v1/organizations/${orgId}/management/runs/${runId}/stream${params}`;
}

export function toErrorMessage(err: unknown): string {
  return toUserMessage(err);
}
