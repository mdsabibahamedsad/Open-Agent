'use client';

import * as React from 'react';
import Link from 'next/link';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { DataTable, Column } from '@/components/ui/table';
import { StatusBadge } from '@/components/ui/status';
import { fetchDiagnostics } from '@/lib/operations';

export default function OpsDiagnosticsPage() {
  const [rows, setRows] = React.useState<{ component: string; ok: boolean; message: string; action: string }[]>([]);
  const [healthy, setHealthy] = React.useState<boolean | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  const load = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetchDiagnostics();
      setRows(res.diagnostics ?? []);
      setHealthy(res.healthy);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Diagnostics unavailable');
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => { load(); }, [load]);

  const columns: Column<{ component: string; ok: boolean; message: string; action: string }>[] = [
    { key: 'component', header: 'Component', render: (r) => <span className="oa-code">{r.component}</span> },
    { key: 'ok', header: 'Result', render: (r) => <StatusBadge status={r.ok ? 'HEALTHY' : 'UNAVAILABLE'} /> },
    { key: 'message', header: 'Message', accessor: (r) => r.message },
    { key: 'action', header: 'Action', accessor: (r) => r.action || '—' },
  ];

  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader
            title="Diagnostics"
            description="Self-hosted diagnostics across every subsystem. No secrets are exposed."
            breadcrumbs={[{ label: 'Home', href: '/' }, { label: 'Operations', href: '/operations' }, { label: 'Diagnostics' }]}
          />
          <Card>
            <CardHeader><CardTitle>Summary: {healthy === null ? '…' : healthy ? 'healthy' : 'issues found'}</CardTitle></CardHeader>
            <CardContent>
              <DataTable columns={columns} rows={rows} keyOf={(r) => r.component} loading={loading} error={error} onRetry={load} emptyTitle="No checks" />
            </CardContent>
          </Card>
          <Link href="/operations" className="oa-caption hover:underline">Back to Operations</Link>
        </div>
      </Layout>
    </Protected>
  );
}
