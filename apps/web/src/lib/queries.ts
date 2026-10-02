'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { useOrganization } from '@/context/OrganizationContext';
import { useDebouncedValue } from '@/hooks/hooks';

async function safeList<T>(paths: string[], params?: Record<string, string | number | boolean | undefined | null>): Promise<{ items: T[]; total: number }> {
  for (const p of paths) {
    try {
      const data = await api.get<{ data?: T[]; items?: T[]; meta?: { total?: number } } | T[]>(p, params);
      if (Array.isArray(data)) return { items: data, total: data.length };
      const items = data.data ?? data.items ?? [];
      return { items, total: data.meta?.total ?? items.length };
    } catch {
      // try next candidate
    }
  }
  return { items: [], total: 0 };
}

export function useOrgScopedList<T>(
  key: string,
  paths: string[],
  params?: Record<string, string | number | boolean | undefined | null>,
  options?: { enabled?: boolean; staleTime?: number },
) {
  const { currentOrgId } = useOrganization();
  const query = useQuery({
    queryKey: [key, currentOrgId, params],
    queryFn: () => safeList<T>(paths.map((p) => (currentOrgId ? p.replace('{orgId}', currentOrgId) : p)), params),
    enabled: options?.enabled ?? true,
    staleTime: options?.staleTime ?? 30_000,
  });
  return {
    items: query.data?.items ?? [],
    total: query.data?.total ?? 0,
    isLoading: query.isLoading,
    error: query.error instanceof Error ? query.error.message : null,
    refetch: query.refetch,
  };
}

export function useSearchParamsState(search: string) {
  const debounced = useDebouncedValue(search, 300);
  return debounced;
}

export function useOrgScopedMutation<TData = unknown, TVariables = unknown>(
  mutationFn: (variables: TVariables) => Promise<TData>,
  options?: {
    onSuccess?: (data: TData) => void;
    onError?: (error: Error) => void;
    invalidateKeys?: string[];
  },
) {
  const { currentOrgId } = useOrganization();
  const queryClient = useQueryClient();
  const mutation = useMutation<TData, Error, TVariables>({
    mutationFn: (variables) => mutationFn(resolveOrgPath(variables, currentOrgId)),
    onSuccess: (data) => {
      for (const key of options?.invalidateKeys ?? []) {
        void queryClient.invalidateQueries({ queryKey: [key] });
      }
      options?.onSuccess?.(data);
    },
    onError: (error) => {
      options?.onError?.(error);
    },
  });
  return {
    mutate: mutation.mutate,
    mutateAsync: mutation.mutateAsync,
    isPending: mutation.isPending,
    isError: mutation.isError,
    error: mutation.error instanceof Error ? mutation.error.message : null,
    reset: mutation.reset,
  };
}

function resolveOrgPath<TVariables>(variables: TVariables, orgId: string | null): TVariables {
  // Pass-through: mutation functions already close over resolved paths.
  // Kept as a seam so future callers can use '{orgId}' templates.
  void orgId;
  return variables;
}
