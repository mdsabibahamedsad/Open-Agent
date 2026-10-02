'use client';

import * as React from 'react';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { EmptyState, ErrorState } from '@/components/ui/states';
import { StatusBadge } from '@/components/ui/status';
import { useOrganization } from '@/context/OrganizationContext';
import { installationsApi, Installation } from '@/lib/packages';
import { TrustBadge, UpdateControls } from '@/features/packages/ui';
import { Package } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';

export default function InstalledPackagesPage() {
  const { currentOrgId } = useOrganization();
  const query = useQuery({
    queryKey: ['installations', currentOrgId],
    queryFn: () => installationsApi.list(currentOrgId!, { page_size: 50 }),
    enabled: Boolean(currentOrgId),
    staleTime: 15_000,
  });
  const items: Installation[] = (query.data?.data as Installation[]) ?? [];

  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader
            title="Installed packages"
            description="Every package installed into this organization: version, trust, security posture, updates and rollback."
            breadcrumbs={[{ label: 'Home', href: '/' }, { label: 'Settings', href: '/settings' }, { label: 'Packages' }]}
          />
          {query.isLoading && <p className="text-sm text-muted-foreground">Loading installations…</p>}
          {query.isError && (
            <ErrorState
              title="Installations unavailable"
              description={query.error instanceof Error ? query.error.message : 'Could not load installations.'}
              onRetry={() => query.refetch()}
            />
          )}
          {!query.isLoading && !query.isError && items.length === 0 && (
            <Card>
              <CardContent>
                <EmptyState
                  icon={Package}
                  title="Nothing installed"
                  description="Discover reusable workforces, agents and skills in the Template Center."
                />
              </CardContent>
            </Card>
          )}
          <div className="flex flex-col gap-3">
            {items.map((inst) => (
              <Card key={inst.id}>
                <CardContent className="flex flex-wrap items-center gap-2 py-4">
                  <div className="min-w-0 flex-1">
                    <p className="font-medium">{inst.package_name || inst.package_slug}</p>
                    <p className="text-sm text-muted-foreground">
                      v{inst.version} · {inst.package_slug}
                      {inst.update_available && (
                        <span className="ml-2 text-yellow-600">Update available: v{inst.update_available}</span>
                      )}
                      {inst.error && <span className="ml-2 text-destructive">{inst.error}</span>}
                    </p>
                  </div>
                  <StatusBadge status={inst.status} />
                  <TrustBadge trust={inst.trust} official={inst.official} />
                  {inst.official && <Badge variant="success">Official</Badge>}
                  <UpdateControls installation={inst} />
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      </Layout>
    </Protected>
  );
}
