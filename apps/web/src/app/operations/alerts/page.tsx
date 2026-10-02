'use client';

import * as React from 'react';
import Link from 'next/link';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { DataTable, Column } from '@/components/ui/table';
import { StatusBadge } from '@/components/ui/status';
import { Button } from '@/components/ui/button';
import { fetchOpsAlerts, ackOpsAlert, type OpsAlert } from '@/lib/operations';

export default function OpsAlertsPage() {
  const [alerts, setAlerts] = React.useState<OpsAlert[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  const load = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetchOpsAlerts();
      setAlerts(res.alerts ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load alerts');
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => { load(); }, [load]);

  const columns: Column<OpsAlert>[] = [
    { key: 'severity', header: 'Severity', render: (a) => <StatusBadge status={a.severity} /> },
    { key: 'source', header: 'Source', accessor: (a) => a.source || '—' },
    { key: 'condition', header: 'Condition', render: (a) => <span className="oa-code">{a.condition} {a.observed} / {a.threshold}</span> },
    { key: 'status', header: 'Status', render: (a) => <StatusBadge status={a.status} /> },
    {
      key: 'actions', header: 'Actions',
      render: (a) => a.status === 'FIRING' ? (
        <Button variant="outline" size="sm" onClick={async () => { await ackOpsAlert(a.id); await load(); }}>
          Acknowledge
        </Button>
      ) : <span className="oa-caption">—</span>,
    },
  ];

  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader
            title="Alerts"
            description="Alert rules, firing conditions and acknowledgement."
            breadcrumbs={[{ label: 'Home', href: '/' }, { label: 'Operations', href: '/operations' }, { label: 'Alerts' }]}
          />
          <DataTable columns={columns} rows={alerts} keyOf={(a) => a.id} loading={loading} error={error} onRetry={load} emptyTitle="No alerts" emptyDescription="Alert rules fire here when thresholds breach." />
          <Link href="/operations" className="oa-caption hover:underline">Back to Operations</Link>
        </div>
      </Layout>
    </Protected>
  );
}
