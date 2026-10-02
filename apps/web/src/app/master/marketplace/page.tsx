'use client';

import * as React from 'react';
import Link from 'next/link';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { EmptyState, ErrorState } from '@/components/ui/states';
import { StatusBadge } from '@/components/ui/status';
import { useAuth } from '@/context/AuthContext';
import { toUserMessage } from '@/lib/api';
import { masterApi, reportsApi } from '@/lib/marketplace';
import { ShieldCheck } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';

type QueueKind = 'listings' | 'reports' | 'reviews' | 'advisories' | 'revoked';

export default function MasterMarketplacePage() {
  const { user } = useAuth();
  const allowed = !!(user?.is_platform_owner || user?.is_superadmin);
  const [queue, setQueue] = React.useState<QueueKind>('listings');
  const [actionReason, setActionReason] = React.useState('');
  const [msg, setMsg] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState<string | null>(null);

  const overview = useQuery({
    queryKey: ['master-overview'],
    queryFn: () => masterApi.overview(),
    enabled: allowed,
    staleTime: 30_000,
  });
  const queueQuery = useQuery({
    queryKey: ['master-queue', queue],
    queryFn: () => masterApi.queue(queue, { page_size: 20 }),
    enabled: allowed,
    staleTime: 15_000,
  });
  const items = (queueQuery.data?.data ?? []) as Record<string, unknown>[];

  const act = async (targetType: string, targetId: string, action: string) => {
    if (!actionReason) {
      setMsg('A reason is required for every moderation action.');
      return;
    }
    setBusy(`${action}:${targetId}`);
    setMsg(null);
    try {
      await masterApi.action({ target_type: targetType, target_id: targetId, action, reason: actionReason });
      setMsg(`${action} applied with audit trail.`);
      void queueQuery.refetch();
      void overview.refetch();
    } catch (e: unknown) {
      setMsg(toUserMessage(e));
    } finally {
      setBusy(null);
    }
  };

  const triage = async (id: string, status: string) => {
    setBusy(`triage:${id}`);
    setMsg(null);
    try {
      await reportsApi.triage(id, { status });
      setMsg('Report triaged.');
      void queueQuery.refetch();
    } catch (e: unknown) {
      setMsg(toUserMessage(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader
            title="Marketplace moderation"
            description="Platform control: review queues, publishers, security alerts, revocations, categories and policies. Every action here is authenticated, authorized and audited."
            breadcrumbs={[{ label: 'Home', href: '/' }, { label: 'Platform', href: '/platform' }, { label: 'Marketplace' }]}
          />
          {!allowed ? (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2"><ShieldCheck className="h-5 w-5" />Restricted</CardTitle>
              </CardHeader>
              <CardContent><p className="text-sm text-muted-foreground">Only the platform owner can access marketplace moderation.</p></CardContent>
            </Card>
          ) : (
            <>
              {overview.data && (
                <div className="grid gap-3 md:grid-cols-4">
                  {[
                    ['Published listings', overview.data.published_listings],
                    ['Pending reviews', overview.data.pending_reviews],
                    ['Security alerts', overview.data.security_alerts],
                    ['Revoked packages', overview.data.revoked_packages],
                    ['Publishers', overview.data.publishers],
                    ['Private marketplaces', overview.data.private_marketplaces],
                    ['Marketplace events', overview.data.marketplace_events],
                  ].map(([label, value]) => (
                    <Card key={String(label)}>
                      <CardContent className="py-4">
                        <p className="text-2xl font-bold">{value ?? 0}</p>
                        <p className="text-xs text-muted-foreground">{label}</p>
                      </CardContent>
                    </Card>
                  ))}
                </div>
              )}
              <div className="flex max-w-xl items-center gap-2 text-sm">
                <label htmlFor="mod-reason" className="shrink-0 font-medium">Action reason</label>
                <Input id="mod-reason" placeholder="Required for every action…" value={actionReason} onChange={(e) => setActionReason(e.target.value)} />
              </div>
              {msg && <p role="status" className="text-sm text-muted-foreground">{msg}</p>}
              <Tabs value={queue} onValueChange={(v) => setQueue(v as QueueKind)}>
                <TabsList>
                  <TabsTrigger value="listings">Pending reviews</TabsTrigger>
                  <TabsTrigger value="reports">Reports</TabsTrigger>
                  <TabsTrigger value="reviews">Flagged reviews</TabsTrigger>
                  <TabsTrigger value="advisories">Security alerts</TabsTrigger>
                  <TabsTrigger value="revoked">Revoked</TabsTrigger>
                </TabsList>
                {(['listings', 'reports', 'reviews', 'advisories', 'revoked'] as QueueKind[]).map((kind) => (
                  <TabsContent key={kind} value={kind}>
                    {queueQuery.isLoading && <p className="text-sm text-muted-foreground">Loading queue…</p>}
                    {queueQuery.isError && (
                      <ErrorState title="Queue unavailable" description="Could not load the moderation queue." onRetry={() => queueQuery.refetch()} />
                    )}
                    {!queueQuery.isLoading && !queueQuery.isError && items.length === 0 && (
                      <Card><CardContent><EmptyState title="Queue empty" description="Nothing needs attention here. Zero means zero — not fabricated." /></CardContent></Card>
                    )}
                    <div className="flex flex-col gap-2">
                      {items.map((item) => (
                        <QueueRow
                          key={String(item.id)}
                          kind={queue}
                          item={item}
                          busy={busy}
                          onAct={act}
                          onTriage={triage}
                        />
                      ))}
                    </div>
                  </TabsContent>
                ))}
              </Tabs>
            </>
          )}
        </div>
      </Layout>
    </Protected>
  );
}

function QueueRow({
  kind,
  item,
  busy,
  onAct,
  onTriage,
}: {
  kind: QueueKind;
  item: Record<string, unknown>;
  busy: string | null;
  onAct: (targetType: string, targetId: string, action: string) => void;
  onTriage: (id: string, status: string) => void;
}) {
  const id = String(item.id ?? '');
  const title = String(item.title ?? item.slug ?? item.target_type ?? id);
  const status = String(item.status ?? '');
  const btn = (label: string, key: string, fn: () => void, variant: 'default' | 'outline' | 'destructive' = 'outline') => (
    <Button key={key} size="sm" variant={variant} disabled={busy === key} onClick={fn}>
      {label}
    </Button>
  );
  return (
    <Card>
      <CardContent className="flex flex-wrap items-center gap-2 py-3 text-sm">
        <div className="min-w-0 flex-1">
          <p className="font-medium">
            {kind === 'listings' ? <Link href={`/marketplace/${item.slug}`} className="hover:underline">{title}</Link> : title}
          </p>
          <p className="truncate text-muted-foreground">
            {status && <><StatusBadge status={status} /> </>}
            {String(item.reason ?? item.status_reason ?? '')}
          </p>
        </div>
        {kind === 'listings' && (
          <>
            {btn('Approve', `APPROVE:${id}`, () => onAct('listing', id, 'APPROVE'))}
            {btn('Reject', `REJECT:${id}`, () => onAct('listing', id, 'REJECT'), 'destructive')}
            {btn('Feature', `FEATURE:${id}`, () => onAct('listing', id, 'FEATURE'))}
          </>
        )}
        {kind === 'reports' && (
          <>
            <Badge variant="outline">{String(item.target_type)} · {String(item.reason)}</Badge>
            {btn('Investigating', `triage:${id}`, () => onTriage(id, 'INVESTIGATING'))}
            {btn('Resolve', `triage-res:${id}`, () => onTriage(id, 'RESOLVED'))}
            {btn('Dismiss', `triage-dis:${id}`, () => onTriage(id, 'DISMISSED'))}
          </>
        )}
        {kind === 'reviews' && (
          <>
            {btn('Hide', `HIDE_REVIEW:${id}`, () => onAct('review', id, 'HIDE_REVIEW'))}
            {btn('Remove', `REMOVE_REVIEW:${id}`, () => onAct('review', id, 'REMOVE_REVIEW'), 'destructive')}
            {btn('Restore', `RESTORE:${id}`, () => onAct('review', id, 'RESTORE'))}
          </>
        )}
        {kind === 'revoked' && (
          <>{btn('Restore', `RESTORE:${id}`, () => onAct('listing', id, 'RESTORE'))}</>
        )}
      </CardContent>
    </Card>
  );
}
