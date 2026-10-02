'use client';

import * as React from 'react';
import Link from 'next/link';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { DataTable, Column } from '@/components/ui/table';
import { StatusBadge } from '@/components/ui/status';
import { Button } from '@/components/ui/button';
import { fetchCloudWorkers, drainCloudWorker, type CloudWorker } from '@/lib/cloud';

export default function CloudWorkersPage() {
  const [workers, setWorkers] = React.useState<CloudWorker[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  const load = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetchCloudWorkers();
      setWorkers(res.workers ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load workers');
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => { load(); }, [load]);

  const columns: Column<CloudWorker>[] = [
    { key: 'worker', header: 'Worker', render: (w) => <span className="oa-code">{w.worker}</span> },
    { key: 'region', header: 'Region', accessor: (w) => w.region },
    { key: 'pool', header: 'Pool', accessor: (w) => w.pool },
    { key: 'status', header: 'Status', render: (w) => <StatusBadge status={w.status} /> },
    { key: 'load', header: 'Load', render: (w) => <span>{w.active}/{w.capacity}</span> },
    { key: 'version', header: 'Version', accessor: (w) => w.version },
    {
      key: 'actions', header: 'Actions',
      render: (w) => (
        <Button
          variant="outline"
          size="sm"
          disabled={w.status === 'DRAINING' || w.status === 'OFFLINE'}
          onClick={async () => {
            if (!confirm(`Drain worker ${w.worker}? It will finish active work and stop accepting new tasks.`)) return;
            await drainCloudWorker(w.worker);
            await load();
          }}
        >
          Drain
        </Button>
      ),
    },
  ];

  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader
            title="Workers"
            description="Fleet registration, heartbeats, capacity and graceful draining."
            breadcrumbs={[{ label: 'Home', href: '/' }, { label: 'Cloud', href: '/cloud' }, { label: 'Workers' }]}
          />
          <DataTable columns={columns} rows={workers} keyOf={(w) => w.worker} loading={loading} error={error} onRetry={load} emptyTitle="No workers registered" emptyDescription="Start a cloud worker to join the fleet." />
          <Link href="/cloud" className="oa-caption hover:underline">Back to Cloud overview</Link>
        </div>
      </Layout>
    </Protected>
  );
}
