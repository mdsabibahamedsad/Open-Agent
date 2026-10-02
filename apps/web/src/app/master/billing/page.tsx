'use client';

export const dynamic = 'force-dynamic';

import * as React from 'react';
import { useQuery } from '@tanstack/react-query';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { ErrorState } from '@/components/ui/states';
import { useAuth } from '@/context/AuthContext';
import { api } from '@/lib/api';
import { formatMinor } from '@/lib/commerce';

export default function MasterBillingPage() {
  const { user } = useAuth();
  const allowed = !!(user?.is_platform_owner || user?.is_superadmin);
  const overview = useQuery({
    queryKey: ['master-billing-overview'],
    queryFn: () =>
      api.get<{
        payments_gross_minor: number;
        active_subscriptions: number;
        open_disputes: number;
        pending_payouts: number;
        unprocessed_webhooks: number;
      }>('/master/billing/overview'),
    enabled: allowed,
    staleTime: 30_000,
  });
  const payments = useQuery({
    queryKey: ['master-billing-payments'],
    queryFn: () =>
      api.get<{ data: { id: string; provider: string; amount_minor: number; currency: string; status: string }[] }>(
        '/master/billing/payments',
      ),
    enabled: allowed,
    staleTime: 15_000,
  });
  const cards: [string, React.ReactNode][] = [
    ['Gross payments', overview.data ? formatMinor(overview.data.payments_gross_minor, 'USD') : '—'],
    ['Active subscriptions', overview.data?.active_subscriptions ?? '—'],
    ['Open disputes', overview.data?.open_disputes ?? '—'],
    ['Pending payouts', overview.data?.pending_payouts ?? '—'],
    ['Unprocessed webhooks', overview.data?.unprocessed_webhooks ?? '—'],
  ];

  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader
            title="Billing administration"
            description="Platform transactions, subscriptions, refunds, disputes, payouts, and webhook health. Platform owners only."
            breadcrumbs={[{ label: 'Home', href: '/' }, { label: 'Master', href: '/master/marketplace' }, { label: 'Billing' }]}
          />
          {!allowed && <p className="text-sm text-destructive">Platform owner access required.</p>}
          {allowed && (
            <>
              {overview.isError && (
                <ErrorState title="Billing overview unavailable" description="Could not load." onRetry={() => overview.refetch()} />
              )}
              <div className="grid gap-3 md:grid-cols-5">
                {cards.map(([label, value]) => (
                  <Card key={label}>
                    <CardContent className="py-4">
                      <p className="text-2xl font-bold">{value}</p>
                      <p className="text-xs text-muted-foreground">{label}</p>
                    </CardContent>
                  </Card>
                ))}
              </div>
              <Card>
                <CardHeader><CardTitle className="text-base">Recent payments</CardTitle></CardHeader>
                <CardContent>
                  <ul className="space-y-2">
                    {(payments.data?.data ?? []).slice(0, 20).map((p) => (
                      <li key={p.id} className="flex items-center justify-between rounded-md border px-3 py-2 text-sm">
                        <span className="font-mono">{p.id.slice(0, 8)}… · {p.provider}</span>
                        <span>
                          <strong>{formatMinor(p.amount_minor, p.currency)}</strong>
                          <span className="ml-2 text-muted-foreground">{p.status}</span>
                        </span>
                      </li>
                    ))}
                    {(payments.data?.data ?? []).length === 0 && !payments.isLoading && (
                      <p className="text-sm text-muted-foreground">No payments recorded.</p>
                    )}
                  </ul>
                </CardContent>
              </Card>
            </>
          )}
        </div>
      </Layout>
    </Protected>
  );
}
