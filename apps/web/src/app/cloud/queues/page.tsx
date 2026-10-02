'use client';

import * as React from 'react';
import Link from 'next/link';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { DataTable, Column } from '@/components/ui/table';
import { fetchCloudQueues, type CloudQueue } from '@/lib/cloud';

export default function CloudQueuesPage() {
  const [queues, setQueues] = React.useState<CloudQueue[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  const load = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetchCloudQueues();
      setQueues(res.queues ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load queues');
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => { load(); }, [load]);

  const columns: Column<CloudQueue>[] = [
    { key: 'queue', header: 'Queue', render: (q) => <span className="oa-code">{q.queue}</span> },
    { key: 'depth', header: 'Depth', accessor: (q) => q.depth },
    { key: 'oldest', header: 'Oldest (s)', render: (q) => <span>{Math.round(q.oldest_job_age_s)}</span> },
    { key: 'processing', header: 'Processing', accessor: (q) => q.processing },
    { key: 'failed', header: 'Dead-letter', accessor: (q) => q.failed },
    { key: 'paused', header: 'Paused', render: (q) => <span>{q.paused ? 'Yes' : 'No'}</span> },
  ];

  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader
            title="Queues"
            description="Queue depth, oldest-job age, throughput pressure and dead-letter counts."
            breadcrumbs={[{ label: 'Home', href: '/' }, { label: 'Cloud', href: '/cloud' }, { label: 'Queues' }]}
          />
          <DataTable columns={columns} rows={queues} keyOf={(q) => q.queue} loading={loading} error={error} onRetry={load} emptyTitle="No queues" emptyDescription="Queues appear once the cloud runtime is enabled." />
          <Link href="/cloud" className="oa-caption hover:underline">Back to Cloud overview</Link>
        </div>
      </Layout>
    </Protected>
  );
}
