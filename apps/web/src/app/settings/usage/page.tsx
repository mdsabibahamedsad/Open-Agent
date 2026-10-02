'use client';

export const dynamic = 'force-dynamic';

import * as React from 'react';
import { useQuery } from '@tanstack/react-query';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { ErrorState } from '@/components/ui/states';
import { commerceApi } from '@/lib/commerce';

function monthBounds(): { start: string; end: string } {
  const now = new Date();
  const start = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), 1));
  const end = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() + 1, 1));
  return { start: start.toISOString(), end: end.toISOString() };
}

export default function UsagePage() {
  const bounds = React.useMemo(monthBounds, []);
  const [meter, setMeter] = React.useState('agent_runs');
  const metersQuery = useQuery({ queryKey: ['usage-meters'], queryFn: () => commerceApi.meters() });
  const quotasQuery = useQuery({ queryKey: ['usage-quotas'], queryFn: () => commerceApi.quotas() });
  const summaryQuery = useQuery({
    queryKey: ['usage-summary', meter, bounds.start, bounds.end],
    queryFn: () => commerceApi.usageSummary(meter, bounds.start, bounds.end),
  });
  const meters = metersQuery.data?.data ?? [];
  const quotas = quotasQuery.data?.data ?? [];

  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader
            title="Usage"
            description="Metered usage for the current period, with quotas and remaining allowance. No projections are invented."
            breadcrumbs={[{ label: 'Home', href: '/' }, { label: 'Settings', href: '/settings' }, { label: 'Usage' }]}
          />
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Usage by feature</CardTitle>
              <CardDescription>Current billing period (UTC).</CardDescription>
            </CardHeader>
            <CardContent className="max-w-xl space-y-3">
              <label className="block text-sm">
                Meter
                <select
                  value={meter}
                  onChange={(e) => setMeter(e.target.value)}
                  className="mt-1 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                >
                  {meters.map((m) => (
                    <option key={m.slug} value={m.slug}>{m.name} ({m.unit})</option>
                  ))}
                  {meters.length === 0 && <option value={meter}>{meter}</option>}
                </select>
              </label>
              {summaryQuery.isLoading && <p className="text-sm text-muted-foreground">Loading usage…</p>}
              {summaryQuery.isError && (
                <ErrorState title="Usage unavailable" description="Could not load." onRetry={() => summaryQuery.refetch()} />
              )}
              {summaryQuery.data && (
                <div className="rounded-md border px-3 py-3 text-sm">
                  <p className="text-2xl font-bold">{summaryQuery.data.total}</p>
                  <p className="text-muted-foreground">
                    {meter} · {summaryQuery.data.events} events · {summaryQuery.data.aggregation}
                  </p>
                </div>
              )}
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Quotas</CardTitle>
              <CardDescription>Entitlement quotas and remaining allowance.</CardDescription>
            </CardHeader>
            <CardContent>
              {quotas.length === 0 && <p className="text-sm text-muted-foreground">No quotas configured.</p>}
              <ul className="space-y-2">
                {quotas.map((q) => (
                  <li key={q.id} className="rounded-md border px-3 py-2 text-sm">
                    <span className="font-mono">{q.meter_id.slice(0, 8)}…</span>
                    <span className="ml-2 text-muted-foreground">
                      limit {q.limit_value ?? 'unlimited'} · {q.period}
                    </span>
                  </li>
                ))}
              </ul>
              <p className="oa-caption mt-3">Overages are never charged automatically; they require explicit product configuration.</p>
            </CardContent>
          </Card>
        </div>
      </Layout>
    </Protected>
  );
}
