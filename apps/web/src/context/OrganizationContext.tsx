'use client';

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { useAuth } from '@/context/AuthContext';
import type { Organization } from '@/types';

interface OrgContextValue {
  organizations: Organization[];
  currentOrg: Organization | null;
  currentOrgId: string | null;
  isLoading: boolean;
  error: string | null;
  switchOrg: (id: string) => void;
  refresh: () => Promise<void>;
  permissions: string[];
}

const OrgContext = createContext<OrgContextValue | null>(null);

const ORG_KEY = 'oa:org-id';

async function fetchOrganizations(): Promise<Organization[]> {
  // Backend may not expose a list endpoint yet; try candidates and fall back to [].
  const candidates = ['/organizations', '/orgs', '/me/organizations', '/auth/organizations'];
  for (const path of candidates) {
    try {
      const data = await api.get<{ organizations?: Organization[]; data?: Organization[] } | Organization[]>(path);
      if (Array.isArray(data)) return data;
      if (Array.isArray(data.organizations)) return data.organizations as Organization[];
      if (Array.isArray(data.data)) return data.data as Organization[];
    } catch {
      // try next
    }
  }
  return [];
}

export function OrganizationProvider({ children }: { children: React.ReactNode }) {
  const { status } = useAuth();
  const queryClient = useQueryClient();
  const [currentOrgId, setCurrentOrgId] = useState<string | null>(() => {
    if (typeof window === 'undefined') return null;
    try {
      return window.localStorage.getItem(ORG_KEY);
    } catch {
      return null;
    }
  });

  const enabled = status === 'authenticated';
  const orgsQuery = useQuery({
    queryKey: ['organizations'],
    queryFn: fetchOrganizations,
    enabled,
    staleTime: 60_000,
    retry: 1,
  });

  const organizations = useMemo(() => orgsQuery.data ?? [], [orgsQuery.data]);

  useEffect(() => {
    if (!currentOrgId && organizations.length > 0) {
      const first = organizations[0].id;
      setCurrentOrgId(first);
      try {
        window.localStorage.setItem(ORG_KEY, first);
      } catch {
        /* noop */
      }
    }
    if (currentOrgId && organizations.length > 0 && !organizations.some((o) => o.id === currentOrgId)) {
      const first = organizations[0].id;
      setCurrentOrgId(first);
      try {
        window.localStorage.setItem(ORG_KEY, first);
      } catch {
        /* noop */
      }
    }
  }, [organizations, currentOrgId]);

  const switchOrg = useCallback(
    (id: string) => {
      setCurrentOrgId(id);
      try {
        window.localStorage.setItem(ORG_KEY, id);
      } catch {
        /* noop */
      }
      // Org-scoped queries must refetch.
      queryClient.invalidateQueries();
    },
    [queryClient],
  );

  const refresh = useCallback(async () => {
    await orgsQuery.refetch();
  }, [orgsQuery]);

  // Permissions: derived from membership/role when backend exposes them.
  // Fall back to empty (deny-by-default in UI; backend remains authoritative).
  const permissionsQuery = useQuery({
    queryKey: ['permissions', currentOrgId],
    queryFn: async (): Promise<string[]> => {
      if (!currentOrgId) return [];
      try {
        const data = await api.get<{ permissions?: string[]; data?: string[] } | string[]>(
          `/organizations/${currentOrgId}/my-permissions`,
        );
        if (Array.isArray(data)) return data;
        if (Array.isArray((data as { permissions?: string[] }).permissions))
          return (data as { permissions: string[] }).permissions;
        return [];
      } catch {
        return [];
      }
    },
    enabled: enabled && !!currentOrgId,
    staleTime: 60_000,
  });

  const value: OrgContextValue = {
    organizations,
    currentOrg: organizations.find((o) => o.id === currentOrgId) ?? null,
    currentOrgId,
    isLoading: orgsQuery.isLoading,
    error: orgsQuery.error instanceof Error ? orgsQuery.error.message : null,
    switchOrg,
    refresh,
    permissions: permissionsQuery.data ?? [],
  };

  return <OrgContext.Provider value={value}>{children}</OrgContext.Provider>;
}

export function useOrganization(): OrgContextValue {
  const ctx = useContext(OrgContext);
  if (!ctx) throw new Error('useOrganization must be used within OrganizationProvider');
  return ctx;
}
