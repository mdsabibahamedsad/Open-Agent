'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { useOrganization } from '@/context/OrganizationContext';
import type { EvaluationRecord, QualityOverview } from './types';

function base(orgId: string | null): string {
  return `/organizations/${orgId}/evaluations`;
}

export const qualityKeys = {
  all: ['quality'] as const,
  overview: (org: string | null) => ['quality', 'overview', org] as const,
  list: (org: string | null, params?: object) => ['quality', 'evaluations', org, params] as const,
  detail: (org: string | null, id: string) => ['quality', 'evaluation', org, id] as const,
  plans: (org: string | null) => ['quality', 'plans', org] as const,
  gates: (org: string | null) => ['quality', 'gates', org] as const,
  benchmarks: (org: string | null) => ['quality', 'benchmarks', org] as const,
};

export function useQualityOverview() {
  const { currentOrgId } = useOrganization();
  const query = useQuery({
    queryKey: qualityKeys.overview(currentOrgId),
    queryFn: () => api.get<QualityOverview>(`/organizations/${currentOrgId}/quality/overview`),
    staleTime: 15_000,
    refetchInterval: 30_000,
  });
  return { overview: query.data, isLoading: query.isLoading, error: query.error, refetch: query.refetch };
}

export function useEvaluations(params?: { status?: string; decision?: string; evaluation_type?: string; agent_id?: string; workflow_id?: string }) {
  const { currentOrgId } = useOrganization();
  const query = useQuery({
    queryKey: qualityKeys.list(currentOrgId, params),
    queryFn: async () => {
      const res = await api.get<{ items: EvaluationRecord[]; total: number }>(base(currentOrgId), {
        status: params?.status || undefined,
        decision: params?.decision || undefined,
        evaluation_type: params?.evaluation_type || undefined,
        agent_id: params?.agent_id || undefined,
        workflow_id: params?.workflow_id || undefined,
        limit: 100,
      });
      return { items: res.items ?? [], total: res.total ?? 0 };
    },
    staleTime: 10_000,
    refetchInterval: 15_000,
  });
  return {
    items: query.data?.items ?? [],
    total: query.data?.total ?? 0,
    isLoading: query.isLoading,
    error: query.error,
    refetch: query.refetch,
  };
}

export function useEvaluation(id: string) {
  const { currentOrgId } = useOrganization();
  const query = useQuery({
    queryKey: qualityKeys.detail(currentOrgId, id),
    queryFn: () => api.get<EvaluationRecord>(`${base(currentOrgId)}/${id}`),
    staleTime: 5_000,
    refetchInterval: 10_000,
  });
  return { evaluation: query.data, isLoading: query.isLoading, error: query.error, refetch: query.refetch };
}

export function useEvaluationMutations(id: string) {
  const { currentOrgId } = useOrganization();
  const qc = useQueryClient();
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: qualityKeys.detail(currentOrgId, id) });
    qc.invalidateQueries({ queryKey: qualityKeys.all });
  };
  const post = (action: string) => (body: unknown) =>
    api.post<EvaluationRecord>(`${base(currentOrgId)}/${id}/${action}`, body);
  const verify = useMutation({ mutationFn: post('verify'), onSuccess: invalidate });
  const finalize = useMutation({ mutationFn: post('finalize'), onSuccess: invalidate });
  const retry = useMutation({ mutationFn: post('retry'), onSuccess: invalidate });
  const correct = useMutation({ mutationFn: post('correct'), onSuccess: invalidate });
  const feedback = useMutation({ mutationFn: post('feedback'), onSuccess: invalidate });
  return { verify, finalize, retry, correct, feedback };
}

export function useCorrectionPlans() {
  const { currentOrgId } = useOrganization();
  const query = useQuery({
    queryKey: qualityKeys.plans(currentOrgId),
    queryFn: () =>
      api.get<{ items: Array<{ id: string; evaluation_id: string; strategy: string; status: string }> }>(
        `/organizations/${currentOrgId}/correction-plans`,
      ),
    staleTime: 15_000,
  });
  return { plans: query.data?.items ?? [], isLoading: query.isLoading, error: query.error };
}

export function useQualityGates() {
  const { currentOrgId } = useOrganization();
  const query = useQuery({
    queryKey: qualityKeys.gates(currentOrgId),
    queryFn: () =>
      api.get<{ items: Array<{ id: string; name: string; failure_behavior: string }> }>(
        `/organizations/${currentOrgId}/quality-gates`,
      ),
    staleTime: 30_000,
  });
  return { gates: query.data?.items ?? [], isLoading: query.isLoading, error: query.error };
}

export function useBenchmarks() {
  const { currentOrgId } = useOrganization();
  const query = useQuery({
    queryKey: qualityKeys.benchmarks(currentOrgId),
    queryFn: () =>
      api.get<{ items: Array<{ id: string; name: string; dataset_size: number }> }>(
        `/organizations/${currentOrgId}/benchmarks`,
      ),
    staleTime: 30_000,
  });
  return { benchmarks: query.data?.items ?? [], isLoading: query.isLoading, error: query.error };
}
