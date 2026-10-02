'use client';

import * as React from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { EmptyState, ErrorState } from '@/components/ui/states';
import { StatusBadge } from '@/components/ui/status';
import { useOrganization } from '@/context/OrganizationContext';
import { toUserMessage } from '@/lib/api';
import { listingsApi, ListingDetail } from '@/lib/marketplace';
import { packagesApi } from '@/lib/packages';
import { ChangelogView } from '@/features/marketplace/ui';
import { StudioShell } from '../../shell';
import { useQuery } from '@tanstack/react-query';

export default function StudioListingPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const { currentOrgId } = useOrganization();
  const [busy, setBusy] = React.useState<string | null>(null);
  const [message, setMessage] = React.useState<string | null>(null);
  const [reason, setReason] = React.useState('');
  const [versionId, setVersionId] = React.useState('');
  const [changelogNotes, setChangelogNotes] = React.useState('');

  const query = useQuery({
    queryKey: ['studio-listing', currentOrgId, id],
    queryFn: () => listingsApi.get(currentOrgId!, id),
    enabled: Boolean(currentOrgId && id),
    staleTime: 10_000,
  });
  const detail: ListingDetail | undefined = query.data;

  const versionsQuery = useQuery({
    queryKey: ['studio-pkg-versions', currentOrgId, detail?.package_id],
    queryFn: () => packagesApi.versions(currentOrgId!, detail!.package_id),
    enabled: Boolean(currentOrgId && detail?.package_id),
    staleTime: 30_000,
  });
  const pkgVersions = (versionsQuery.data?.data ?? []) as { id: string; version: string; status: string }[];

  const run = async (label: string, fn: () => Promise<unknown>) => {
    if (!currentOrgId) return;
    setBusy(label);
    setMessage(null);
    try {
      await fn();
      setMessage(`${label} succeeded.`);
      void query.refetch();
    } catch (e: unknown) {
      setMessage(toUserMessage(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <StudioShell title="Listing" description="Manage one listing through submit, review, publish, update and deprecation.">
      {query.isLoading && <p className="text-sm text-muted-foreground">Loading listing…</p>}
      {query.isError && (
        <ErrorState title="Listing unavailable" description={query.error instanceof Error ? query.error.message : 'Could not load.'} onRetry={() => query.refetch()} />
      )}
      {detail && (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-xl font-semibold">{detail.title}</h2>
            <StatusBadge status={detail.status} />
            <Badge variant="outline">v{detail.published_version || '—'}</Badge>
            <span className="ml-auto flex flex-wrap gap-2">
              {detail.status === 'DRAFT' && (
                <Button size="sm" disabled={!!busy} onClick={() => run('Submit', () => listingsApi.submit(currentOrgId!, detail.id))}>
                  Submit for review
                </Button>
              )}
              {detail.status === 'APPROVED' && (
                <Button size="sm" disabled={!!busy} onClick={() => run('Publish', () => listingsApi.action(currentOrgId!, detail.id, 'publish'))}>
                  Publish
                </Button>
              )}
              {(detail.status === 'PUBLISHED' || detail.status === 'SUSPENDED') && (
                <Button size="sm" variant="outline" disabled={!!busy} onClick={() => run('Deprecate', () => listingsApi.action(currentOrgId!, detail.id, 'deprecate', reason || 'Deprecated by publisher'))}>
                  Deprecate
                </Button>
              )}
              <Link href={`/marketplace/${detail.slug}`}><Button size="sm" variant="ghost">View live</Button></Link>
            </span>
          </div>
          {message && <p role="status" className="text-sm text-muted-foreground">{message}</p>}

          <Tabs defaultValue="versions">
            <TabsList>
              <TabsTrigger value="versions">Versions</TabsTrigger>
              <TabsTrigger value="lifecycle">Lifecycle</TabsTrigger>
              <TabsTrigger value="analytics">Analytics</TabsTrigger>
              <TabsTrigger value="timeline">Timeline</TabsTrigger>
            </TabsList>
            <TabsContent value="versions">
              <Card>
                <CardHeader><CardTitle className="text-base">Attach a package version</CardTitle></CardHeader>
                <CardContent className="space-y-3 text-sm">
                  <div className="flex flex-wrap gap-2">
                    <select aria-label="Package version" className="rounded-md border border-input bg-background px-3 py-2" value={versionId} onChange={(e) => setVersionId(e.target.value)}>
                      <option value="">Select version…</option>
                      {pkgVersions.map((v) => (
                        <option key={v.id} value={v.id}>v{v.version} ({v.status})</option>
                      ))}
                    </select>
                    <Input placeholder="Changelog notes" aria-label="Changelog notes" value={changelogNotes} onChange={(e) => setChangelogNotes(e.target.value)} className="max-w-sm" />
                    <Button size="sm" disabled={!versionId || !!busy} onClick={() => run('Attach version', () => listingsApi.addVersion(currentOrgId!, detail.id, { version_id: versionId, changelog: { notes: changelogNotes } }))}>
                      Attach & set current
                    </Button>
                  </div>
                  <div className="space-y-3">
                    {detail.versions.map((v) => (
                      <div key={v.version_id} className="rounded-md border p-3">
                        <p className="font-medium">v{v.version} {v.is_current && <Badge variant="secondary">current</Badge>}</p>
                        <ChangelogView changelog={v.changelog ?? {}} />
                      </div>
                    ))}
                    {detail.versions.length === 0 && <EmptyState title="No versions attached" description="Attach a validated package version first." />}
                  </div>
                </CardContent>
              </Card>
            </TabsContent>
            <TabsContent value="lifecycle">
              <Card>
                <CardHeader><CardTitle className="text-base">Danger zone</CardTitle></CardHeader>
                <CardContent className="space-y-3 text-sm">
                  <p className="text-muted-foreground">Revocation keeps history, blocks new installs and notifies installers. A reason is always required.</p>
                  <Input placeholder="Reason (required)" aria-label="Revocation reason" value={reason} onChange={(e) => setReason(e.target.value)} className="max-w-xl" />
                  <div>
                    <Button size="sm" variant="destructive" disabled={!reason || !!busy} onClick={() => run('Revoke', () => listingsApi.revoke(currentOrgId!, detail.id, { reason }))}>
                      Revoke listing
                    </Button>
                  </div>
                </CardContent>
              </Card>
            </TabsContent>
            <TabsContent value="analytics">
              <AnalyticsMini listingId={detail.id} />
            </TabsContent>
            <TabsContent value="timeline">
              <TimelineView listingId={detail.id} />
            </TabsContent>
          </Tabs>
        </>
      )}
    </StudioShell>
  );
}

function AnalyticsMini({ listingId }: { listingId: string }) {
  const { currentOrgId } = useOrganization();
  const query = useQuery({
    queryKey: ['studio-listing-analytics', listingId],
    queryFn: () => listingsApi.analytics(currentOrgId!, listingId, 30),
    enabled: Boolean(currentOrgId && listingId),
    staleTime: 60_000,
  });
  if (query.isLoading) return <p className="text-sm text-muted-foreground">Loading analytics…</p>;
  if (query.isError || !query.data) return <p className="text-sm text-muted-foreground">Analytics unavailable.</p>;
  const totals = query.data.totals as Record<string, number>;
  return (
    <Card>
      <CardContent className="grid grid-cols-2 gap-3 py-4 md:grid-cols-4">
        {Object.entries(totals).map(([k, v]) => (
          <div key={k}>
            <p className="text-xl font-bold">{v}</p>
            <p className="text-xs text-muted-foreground">{k.replaceAll('_', ' ')}</p>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function TimelineView({ listingId }: { listingId: string }) {
  const { currentOrgId } = useOrganization();
  const timeline = useQuery({
    queryKey: ['listing-timeline', currentOrgId, listingId],
    queryFn: () => listingsApi.timeline(currentOrgId!, listingId),
    enabled: Boolean(currentOrgId && listingId),
    staleTime: 30_000,
  });
  if (timeline.isLoading) return <p className="text-sm text-muted-foreground">Loading timeline…</p>;
  if (timeline.isError || !timeline.data) return <p className="text-sm text-muted-foreground">Timeline unavailable.</p>;
  if (timeline.data.data.length === 0) return <p className="text-sm text-muted-foreground">No events yet.</p>;
  return (
    <Card>
      <CardContent className="space-y-2 py-4 text-sm">
        {timeline.data.data.map((e, i) => (
          <p key={i}><Badge variant="outline">{e.kind}</Badge> <span className="font-medium">{e.type}</span> <span className="text-muted-foreground">{new Date(e.at).toLocaleString()}</span></p>
        ))}
      </CardContent>
    </Card>
  );
}
