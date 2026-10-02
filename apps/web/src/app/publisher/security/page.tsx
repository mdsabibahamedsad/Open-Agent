'use client';

import * as React from 'react';
import Link from 'next/link';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { ErrorState } from '@/components/ui/states';
import { StatusBadge } from '@/components/ui/status';
import { useOrganization } from '@/context/OrganizationContext';
import { studioApi, Advisory } from '@/lib/marketplace';
import { RiskBadge } from '@/features/packages/ui';
import { HealthBadge } from '@/features/marketplace/ui';
import { StudioShell } from '../shell';
import { useQuery } from '@tanstack/react-query';

export default function StudioSecurityPage() {
  const { currentOrgId } = useOrganization();
  const query = useQuery({
    queryKey: ['studio-security', currentOrgId],
    queryFn: () => studioApi.security(currentOrgId!),
    enabled: Boolean(currentOrgId),
    staleTime: 60_000,
  });
  const listings = (query.data?.data ?? []) as {
    listing_id: string;
    slug: string;
    title: string;
    status: string;
    security_status: string;
    trust_level: string;
    published_version: string;
  }[];
  const advisories: Advisory[] = query.data?.advisories ?? [];

  return (
    <StudioShell title="Security" description="Posture across your listings plus every advisory affecting them. Fix, then publish a new version.">
      {query.isLoading && <p className="text-sm text-muted-foreground">Loading security posture…</p>}
      {query.isError && (
        <ErrorState title="Security unavailable" description={query.error instanceof Error ? query.error.message : 'Could not load.'} onRetry={() => query.refetch()} />
      )}
      {query.data && (
        <>
          <Card>
            <CardHeader><CardTitle className="text-base">Listing posture</CardTitle></CardHeader>
            <CardContent className="space-y-2 text-sm">
              {listings.length === 0 && <p className="text-muted-foreground">No listings yet.</p>}
              {listings.map((l) => (
                <div key={l.listing_id} className="flex flex-wrap items-center gap-2">
                  <Link href={`/publisher/packages/${l.listing_id}`} className="font-medium hover:underline">{l.title}</Link>
                  <RiskBadge risk={l.security_status} />
                  <StatusBadge status={l.status} />
                  <span className="text-muted-foreground">v{l.published_version || '—'}</span>
                </div>
              ))}
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle className="text-base">Advisories ({advisories.length})</CardTitle></CardHeader>
            <CardContent className="space-y-3 text-sm">
              {advisories.length === 0 && <p className="text-muted-foreground">No advisories. Good standing.</p>}
              {advisories.map((a) => (
                <div key={a.id} className="rounded-md border p-3">
                  <p className="font-medium">{a.title}</p>
                  <div className="mt-1 flex flex-wrap gap-2">
                    <Badge variant={a.severity === 'LOW' ? 'secondary' : 'destructive'}>{a.severity}</Badge>
                    <HealthBadge status={a.status} />
                    <span className="text-muted-foreground">affected: {a.affected_versions || '—'}</span>
                  </div>
                  <p className="mt-1 text-muted-foreground">{a.recommended_action}{a.recommended_version ? ` → v${a.recommended_version}` : ''}</p>
                </div>
              ))}
            </CardContent>
          </Card>
        </>
      )}
    </StudioShell>
  );
}
