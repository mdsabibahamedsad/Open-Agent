'use client';

import { useQuery } from '@tanstack/react-query';
import { api, toUserMessage } from '@/lib/api';
import { useOrganization } from '@/context/OrganizationContext';
import type { ExecutionDetail } from '@/types';

export function useExecution(
  executionId: string,
  orgId: string | null,
) {
  const query = useQuery({
    queryKey: ['execution', executionId, orgId],
    queryFn: async () => {
      if (!orgId) throw new Error('No organization context');
      const data = await api.get<ExecutionDetail>(
        `/organizations/${orgId}/workflows/executions/${executionId}`,
      );
      return data;
    },
    enabled: !!orgId && !!executionId,
    staleTime: 5_000,
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data) return false;
      const runningStates = ['queued', 'running', 'waiting', 'paused'];
      return runningStates.includes(data.status) ? 3000 : false;
    },
  });

  return {
    execution: query.data ?? null,
    isLoading: query.isLoading,
    error: query.error ? toUserMessage(query.error) : null,
    refetch: query.refetch,
  };
}