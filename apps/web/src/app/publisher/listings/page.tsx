'use client';

import * as React from 'react';
import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { EmptyState, ErrorState } from '@/components/ui/states';
import { StatusBadge } from '@/components/ui/status';
import { useOrganization } from '@/context/OrganizationContext';
import { studioApi, ListingCard } from '@/lib/marketplace';
import { StudioShell } from '../shell';
import { useQuery } from '@tanstack/react-query';

export default function StudioListingsPage() {
  const { currentOrgId } = useOrganization();
  const [status, setStatus] = React.useState('');

  const query = useQuery({
    queryKey: ['studio-listings', currentOrgId, status],
    queryFn: () => studioApi.listings(currentOrgId!, status ? { status } : undefined),
    enabled: Boolean(currentOrgId),
    staleTime: 15_000,
  });
  const items: ListingCard[] = query.data?.data ?? [];

  return (
    <StudioShell title="Listings" description="Every listing owned by your publishers, across marketplaces and states.">
      <div className="flex flex-wrap items-center gap-2">
        <select aria-label="Status filter" className="rounded-md border border-input bg-background px-3 py-2 text-sm" value={status} onChange={(e) => setStatus(e.target.value)}>
          {['', 'DRAFT', 'SUBMITTED', 'VALIDATING', 'UNDER_REVIEW', 'APPROVED', 'PUBLISHED', 'SUSPENDED', 'DEPRECATED', 'REVOKED', 'ARCHIVED', 'REJECTED'].map((s) => (
            <option key={s} value={s}>{s === '' ? 'All states' : s}</option>
          ))}
        </select>
        <Link href="/publisher/packages/new" className="ml-auto">
          <Button size="sm">New listing</Button>
        </Link>
      </div>
      {query.isLoading && <p className="text-sm text-muted-foreground">Loading listings…</p>}
      {query.isError && (
        <ErrorState title="Listings unavailable" description={query.error instanceof Error ? query.error.message : 'Could not load.'} onRetry={() => query.refetch()} />
      )}
      {!query.isLoading && !query.isError && items.length === 0 && (
        <Card><CardContent><EmptyState title="No listings" description="Create your first listing from an existing package." action={<Link href="/publisher/packages/new" className="text-sm text-primary underline">New listing</Link>} /></CardContent></Card>
      )}
      <div className="flex flex-col gap-2">
        {items.map((l) => (
          <Card key={l.id}>
            <CardContent className="flex flex-wrap items-center gap-2 py-3">
              <div className="min-w-0 flex-1">
                <Link href={`/publisher/packages/${l.id}`} className="font-medium hover:underline">
                  {l.title}
                </Link>
                <p className="truncate text-sm text-muted-foreground">
                  {l.slug} · v{l.published_version || '—'} · ★ {l.rating_average.toFixed(1)} ({l.rating_count}) · {l.install_count} installs
                </p>
              </div>
              <StatusBadge status={l.status} />
              <Badge variant="outline">{l.pricing_model}</Badge>
              <Link href={`/marketplace/${l.slug}`}>
                <Button variant="ghost" size="sm">View</Button>
              </Link>
            </CardContent>
          </Card>
        ))}
      </div>
    </StudioShell>
  );
}
