'use client';

import * as React from 'react';
import Link from 'next/link';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { StatusBadge } from '@/components/ui/status';
import { DataTable, Column } from '@/components/ui/table';
import { fetchCloudHealth, fetchCloudUsage, type CloudOverview } from '@/lib/cloud';

export default function CloudHealthPage() {
  const [overview, setOverview] = React.useState<CloudOverview | null>(null);
  const [usage, setUsage] = React.useState<Record<string, number>>({});
  const [error, setError] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [health, u] = await Promise.all([
          fetchCloudHealth(),
          fetchCloudUsage().catch(() => ({ usage: {} })),
        ]);
        if (!cancelled) { setOverview(health); setUsage(u.usage ?? {}); }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Health unavailable');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const components = Object.entries(overview?.components ?? {});
  const compColumns: Column<[string, string]>[] = [
    { key: 'c', header: 'Component', render: ([name]) => <span className="oa-code">{name}</span> },
    { key: 's', header: 'State', render: ([, state]) => <StatusBadge status={state} /> },
  ];
  const usageRows = Object.entries(usage);

  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader
            title="Health"
            description="Platform health, incident mode and metered usage."
            breadcrumbs={[{ label: 'Home', href: '/' }, { label: 'Cloud', href: '/cloud' }, { label: 'Health' }]}
          />
          {overview ? (
            <div className="grid gap-4 md:grid-cols-2">
              <Card>
                <CardHeader><CardTitle>Platform: {overview.status}</CardTitle></CardHeader>
                <CardContent>
                  <DataTable columns={compColumns} rows={components} keyOf={([name]) => name} loading={loading} error={error} emptyTitle="No components" />
                </CardContent>
              </Card>
              <Card>
                <CardHeader><CardTitle>Usage meters</CardTitle></CardHeader>
                <CardContent>
                  {usageRows.length === 0 ? <p className="oa-caption">No usage staged yet.</p> : (
                    <ul>{usageRows.map(([meter, qty]) => <li key={meter} className="oa-caption">{meter}: {qty}</li>)}</ul>
                  )}
                  <p className="oa-caption">Incident mode: {overview.incident_mode}</p>
                </CardContent>
              </Card>
            </div>
          ) : (
            <Card><CardContent><p className="oa-caption">{loading ? 'Loading…' : error ?? 'Unavailable'}</p></CardContent></Card>
          )}
          <Link href="/cloud" className="oa-caption hover:underline">Back to Cloud overview</Link>
        </div>
      </Layout>
    </Protected>
  );
}
