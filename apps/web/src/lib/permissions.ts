'use client';

import { useOrganization } from '@/context/OrganizationContext';
import { useAuth } from '@/context/AuthContext';

/** Check a `resource:action` permission against current org context. */
export function usePermission(permission: string): boolean {
  const { permissions } = useOrganization();
  const { user } = useAuth();
  if (user?.is_platform_owner || user?.is_superadmin) return true;
  if (permissions.length === 0) return false;
  if (permissions.includes('*') || permissions.includes(permission)) return true;
  const [resource] = permission.split(':');
  return permissions.includes(`${resource}:*`);
}

export function useCan(): (permission: string) => boolean {
  const { permissions } = useOrganization();
  const { user } = useAuth();
  return (permission: string) => {
    if (user?.is_platform_owner || user?.is_superadmin) return true;
    if (permissions.length === 0) return false;
    if (permissions.includes('*') || permissions.includes(permission)) return true;
    const [resource] = permission.split(':');
    return permissions.includes(`${resource}:*`);
  };
}
