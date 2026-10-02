'use client';

export const dynamic = 'force-dynamic';

import * as React from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { ErrorState } from '@/components/ui/states';
import { useToast } from '@/components/ui/toast';
import { toUserMessage } from '@/lib/api';
import { commerceApi, formatMinor } from '@/lib/commerce';

export default function BillingPage() {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const statusQuery = useQuery({ queryKey: ['billing-status'], queryFn: () => commerceApi.billingStatus() });
  const subsQuery = useQuery({ queryKey: ['billing-subs'], queryFn: () => commerceApi.subscriptions() });
  const invoicesQuery = useQuery({ queryKey: ['billing-invoices'], queryFn: () => commerceApi.invoices() });
  const entitlementsQuery = useQuery({
    queryKey: ['billing-entitlements'],
    queryFn: () => commerceApi.entitlements(),
  });

  const portal = useMutation({
    mutationFn: () => commerceApi.billingPortal(),
    onSuccess: (r) => {
      if (r.portal_url) window.location.href = r.portal_url;
      else toast({ kind: 'info', title: 'Billing portal', description: 'No portal URL returned by provider.' });
    },
    onError: (e) => toast({ kind: 'error', title: 'Portal unavailable', description: toUserMessage(e) }),
  });

  const cancel = useMutation({
    mutationFn: (id: string) => commerceApi.cancelSubscription(id, true),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['billing-subs'] });
      toast({ kind: 'success', title: 'Subscription cancellation requested' });
    },
    onError: (e) => toast({ kind: 'error', title: 'Cancel failed', description: toUserMessage(e) }),
  });

  const status = statusQuery.data;
  const subs = subsQuery.data?.data ?? [];
  const invoices = invoicesQuery.data?.data ?? [];
  const entitlements = entitlementsQuery.data?.data ?? [];

  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader
            title="Billing"
            description="Plan, subscriptions, invoices, payments, and entitlements. Payment secrets are never shown here."
            breadcrumbs={[{ label: 'Home', href: '/' }, { label: 'Settings', href: '/settings' }, { label: 'Billing' }]}
          />
          <div className="grid gap-3 md:grid-cols-3">
            <Card>
              <CardHeader><CardTitle className="text-base">Plan</CardTitle></CardHeader>
              <CardContent className="text-sm">
                {statusQuery.isLoading && <p className="text-muted-foreground">Loading…</p>}
                {status && (
                  <>
                    <p>Billing mode: <strong>{status.mode}</strong></p>
                    <p className="text-muted-foreground">Provider: {status.provider || '—'}</p>
                    {status.test_mode && <p className="mt-1 font-medium text-amber-600">Test mode — no real charges.</p>}
                    {!status.configured && (
                      <p className="mt-1 text-muted-foreground">Billing is not configured. Free and local packages work normally.</p>
                    )}
                  </>
                )}
              </CardContent>
            </Card>
            <Card>
              <CardHeader><CardTitle className="text-base">Provider portal</CardTitle></CardHeader>
              <CardContent className="text-sm">
                <p className="text-muted-foreground">Manage payment methods and invoices in the provider-hosted portal.</p>
                <Button className="mt-3" variant="outline" onClick={() => portal.mutate()} loading={portal.isPending}>
                  Open billing portal
                </Button>
              </CardContent>
            </Card>
            <Card>
              <CardHeader><CardTitle className="text-base">Entitlements</CardTitle></CardHeader>
              <CardContent className="text-sm">
                {entitlements.length === 0 ? (
                  <p className="text-muted-foreground">No active entitlements.</p>
                ) : (
                  <ul className="space-y-1">
                    {entitlements.slice(0, 5).map((e) => (
                      <li key={e.id}>
                        {e.features[0] ?? e.feature} · {e.source} · {e.status}
                      </li>
                    ))}
                  </ul>
                )}
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Subscriptions</CardTitle>
              <CardDescription>Provider state is authoritative; cancellations sync from webhooks.</CardDescription>
            </CardHeader>
            <CardContent>
              {subsQuery.isError && (
                <ErrorState title="Subscriptions unavailable" description="Could not load." onRetry={() => subsQuery.refetch()} />
              )}
              {subs.length === 0 && !subsQuery.isLoading && (
                <p className="text-sm text-muted-foreground">No subscriptions.</p>
              )}
              <ul className="space-y-2">
                {subs.map((s) => (
                  <li key={s.id} className="flex flex-wrap items-center justify-between gap-2 rounded-md border px-3 py-2 text-sm">
                    <span>
                      <strong>{s.status}</strong>
                      <span className="ml-2 text-muted-foreground">
                        {s.current_period_end ? `renews ${new Date(s.current_period_end).toLocaleDateString()}` : 'no period'}
                        {' · '}×{s.quantity}
                      </span>
                    </span>
                    {s.status === 'ACTIVE' && (
                      <Button size="sm" variant="outline" onClick={() => cancel.mutate(s.id)} loading={cancel.isPending}>
                        Cancel
                      </Button>
                    )}
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Invoices</CardTitle>
              <CardDescription>Invoices are retrieved over authenticated sessions only.</CardDescription>
            </CardHeader>
            <CardContent>
              {invoices.length === 0 && !invoicesQuery.isLoading && (
                <p className="text-sm text-muted-foreground">No invoices.</p>
              )}
              <ul className="space-y-2">
                {invoices.map((i) => (
                  <li key={i.id} className="flex items-center justify-between rounded-md border px-3 py-2 text-sm">
                    <span>
                      <strong>{formatMinor(i.total_minor, i.currency)}</strong>
                      <span className="ml-2 text-muted-foreground">{i.status}</span>
                    </span>
                    <a className="text-primary hover:underline" href={`/settings/billing/${i.id}`}>View</a>
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
        </div>
      </Layout>
    </Protected>
  );
}
