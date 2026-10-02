'use client';

import * as React from 'react';
import Link from 'next/link';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { StatusBadge } from '@/components/ui/status';
import { DataTable, Column } from '@/components/ui/table';
import { fetchOpsHealth, fetchOpsSlos, type OpsHealth } from '@/lib/operations';

export default function OpsHealthPage() {
  const [health, setHealth] = React.useState<OpsHealth | null>(null);
  const [slos, setSlos] = React.useState<{ slo: string; target: number; value: number | null; met: boolean | null }[]>([]);
  const [error, setError] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [h, s] = await Promise.all([
          fetchOpsHealth(),
          fetchOpsSlos().catch(() => ({ slos: [] })),
        ]);
        if (!cancelled) { setHealth(h); setSlos(s.slos ?? []); }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Health unavailable');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const components = Object.entries(health?.components ?? {});
  const compColumns: Column<[string, string]>[] = [
    { key: 'c', header: 'Component', render: ([name]) => <span className="oa-code">{name}</span> },
    { key: 's', header: 'State', render: ([, state]) => <StatusBadge status={state} /> },
  ];
  const sloColumns: Column<{ slo: string; target: number; value: number | null; met: boolean | null }>[] = [
    { key: 'slo', header: 'SLO', render: (s) => <span className="oa-code">{s.slo}</span> },
    { key: 'target', header: 'Target', accessor: (s) => s.target },
    { key: 'value', header: 'Measured', render: (s) => <span>{s.value ?? 'no data'}</span> },
    { key: 'met', header: 'Budget', render: (s) => <span>{s.met === null ? '—' : s.met ? 'within budget' : 'exhausted'}</span> },
  ];

  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader
            title="Health"
            description="Liveness, readiness, dependencies and SLO error budgets."
            breadcrumbs={[{ label: 'Home', href: '/' }, { label: 'Operations', href: '/operations' }, { label: 'Health' }]}
          />
          {health ? (
            <div className="grid gap-4 md:grid-cols-2">
              <Card>
                <CardHeader><CardTitle>Platform: {health.status}</CardTitle></CardHeader>
                <CardContent>
                  <DataTable columns={compColumns} rows={components} keyOf={([name]) => name} loading={loading} error={error} emptyTitle="No components" />
                </CardContent>
              </Card>
              <Card>
                <CardHeader><CardTitle>SLOs</CardTitle></CardHeader>
                <CardContent>
                  <DataTable columns={sloColumns} rows={slos} keyOf={(s) => s.slo} loading={loading} error={error} emptyTitle="No SLOs configured" />
                </CardContent>
              </Card>
            </div>
          ) : (
            <Card><CardContent><p className="oa-caption">{loading ? 'Loading…' : error ?? 'Unavailable'}</p></CardContent></Card>
          )}
          <Link href="/operations" className="oa-caption hover:underline">Back to Operations</Link>
        </div>
      </Layout>
    </Protected>
  );
}
