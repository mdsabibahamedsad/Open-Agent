'use client';

import * as React from 'react';
import Link from 'next/link';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { DataTable, Column } from '@/components/ui/table';
import { StatusBadge } from '@/components/ui/status';
import { fetchOpsDeployments, type OpsDeployment } from '@/lib/operations';

export default function OpsDeploymentsPage() {
  const [rows, setRows] = React.useState<OpsDeployment[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  const load = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetchOpsDeployments();
      setRows(res.deployments ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load deployments');
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => { load(); }, [load]);

  const columns: Column<OpsDeployment>[] = [
    { key: 'service', header: 'Service', render: (d) => <span className="oa-code">{d.service}</span> },
    { key: 'version', header: 'Version', accessor: (d) => d.version },
    { key: 'env', header: 'Environment', accessor: (d) => d.environment },
    { key: 'status', header: 'Status', render: (d) => <StatusBadge status={d.status} /> },
    { key: 'deployed', header: 'Deployed', render: (d) => <span className="text-muted-foreground">{d.deployed ? new Date(d.deployed).toLocaleString() : '—'}</span> },
  ];

  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader
            title="Deployments"
            description="Release tracking across development, staging and production."
            breadcrumbs={[{ label: 'Home', href: '/' }, { label: 'Operations', href: '/operations' }, { label: 'Deployments' }]}
          />
          <DataTable columns={columns} rows={rows} keyOf={(d) => d.id} loading={loading} error={error} onRetry={load} emptyTitle="No deployments" emptyDescription="Deployment records appear here." />
          <Link href="/operations" className="oa-caption hover:underline">Back to Operations</Link>
        </div>
      </Layout>
    </Protected>
  );
}
