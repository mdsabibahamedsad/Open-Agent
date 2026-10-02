'use client';

import * as React from 'react';
import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { EmptyState, ErrorState } from '@/components/ui/states';
import { useOrganization } from '@/context/OrganizationContext';
import { studioApi } from '@/lib/marketplace';
import { StudioShell } from '../shell';
import { useQuery } from '@tanstack/react-query';

interface StudioPackage {
  id: string;
  slug: string;
  name: string;
  package_type: string;
  visibility: string;
  trust: string;
  official: boolean;
  latest_version: string;
}

export default function StudioPackagesPage() {
  const { currentOrgId } = useOrganization();
  const query = useQuery({
    queryKey: ['studio-packages', currentOrgId],
    queryFn: () => studioApi.packages(currentOrgId!),
    enabled: Boolean(currentOrgId),
    staleTime: 15_000,
  });
  const items = (query.data?.data ?? []) as StudioPackage[];

  return (
    <StudioShell title="Packages" description="Reusable packages backing your listings. Versions are managed in the Template Center; listings pin published versions.">
      <div className="flex justify-end">
        <Link href="/publisher/packages/new"><Button size="sm">New listing</Button></Link>
      </div>
      {query.isLoading && <p className="text-sm text-muted-foreground">Loading packages…</p>}
      {query.isError && (
        <ErrorState title="Packages unavailable" description={query.error instanceof Error ? query.error.message : 'Could not load.'} onRetry={() => query.refetch()} />
      )}
      {!query.isLoading && !query.isError && items.length === 0 && (
        <Card><CardContent><EmptyState title="No packages linked" description="Packages appear here once you create a listing for them." /></CardContent></Card>
      )}
      <div className="flex flex-col gap-2">
        {items.map((p) => (
          <Card key={p.id}>
            <CardContent className="flex flex-wrap items-center gap-2 py-3">
              <div className="min-w-0 flex-1">
                <p className="font-medium">{p.name}</p>
                <p className="truncate text-sm text-muted-foreground">
                  {p.slug} · {p.package_type} · v{p.latest_version || '—'} · {p.visibility}
                </p>
              </div>
              <Link href={`/templates/${p.slug}`}><Button variant="ghost" size="sm">Open in Template Center</Button></Link>
            </CardContent>
          </Card>
        ))}
      </div>
    </StudioShell>
  );
}
