'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { useOrganization } from '@/context/OrganizationContext';
import type { ApprovalPolicyRecord, ApprovalRecord } from './types';

function base(orgId: string | null): string {
  return `/organizations/${orgId}/approvals`;
}

function policyBase(orgId: string | null): string {
  return `/organizations/${orgId}/approval-policies`;
}

export const approvalKeys = {
  all: ['approvals'] as const,
  list: (org: string | null, params?: object) => ['approvals', 'list', org, params] as const,
  detail: (org: string | null, id: string) => ['approvals', 'detail', org, id] as const,
  policies: (org: string | null) => ['approvals', 'policies', org] as const,
};

export function useApprovals(params?: { status?: string; risk_level?: string }) {
  const { currentOrgId } = useOrganization();
  const query = useQuery({
    queryKey: approvalKeys.list(currentOrgId, params),
    queryFn: async () => {
      const res = await api.get<{ items: ApprovalRecord[]; total: number }>(base(currentOrgId), {
        status: params?.status || undefined,
        risk_level: params?.risk_level || undefined,
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

export function useApproval(id: string) {
  const { currentOrgId } = useOrganization();
  const query = useQuery({
    queryKey: approvalKeys.detail(currentOrgId, id),
    queryFn: () => api.get<ApprovalRecord>(`${base(currentOrgId)}/${id}`),
    staleTime: 5_000,
    refetchInterval: 10_000,
  });
  return { approval: query.data, isLoading: query.isLoading, error: query.error, refetch: query.refetch };
}

export function useApprovalMutations(id: string) {
  const { currentOrgId } = useOrganization();
  const qc = useQueryClient();
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: approvalKeys.detail(currentOrgId, id) });
    qc.invalidateQueries({ queryKey: approvalKeys.all });
  };
  const post = (action: string) => (body: { reason?: string; escalate_to?: string }) =>
    api.post<ApprovalRecord>(`${base(currentOrgId)}/${id}/${action}`, body);
  const approve = useMutation({ mutationFn: post('approve'), onSuccess: invalidate });
  const reject = useMutation({ mutationFn: post('reject'), onSuccess: invalidate });
  const cancel = useMutation({ mutationFn: post('cancel'), onSuccess: invalidate });
  const escalate = useMutation({ mutationFn: post('escalate'), onSuccess: invalidate });
  return { approve, reject, cancel, escalate };
}

export function useApprovalPolicies() {
  const { currentOrgId } = useOrganization();
  const query = useQuery({
    queryKey: approvalKeys.policies(currentOrgId),
    queryFn: () => api.get<{ items: ApprovalPolicyRecord[] }>(policyBase(currentOrgId)),
    staleTime: 30_000,
  });
  return { policies: query.data?.items ?? [], isLoading: query.isLoading, error: query.error };
}

export function useSimulate() {
  const { currentOrgId } = useOrganization();
  return useMutation({
    mutationFn: (body: {
      action_type: string;
      action_category: string;
      target_type?: string;
      target_id?: string;
      environment?: string;
      tool_name?: string;
    }) => api.post(`${base(currentOrgId)}/simulate`, body),
  });
}
