'use client';

import * as React from 'react';
import Link from 'next/link';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { DataTable, Column } from '@/components/ui/table';
import { fetchCloudStorage } from '@/lib/cloud';

interface StorageRow { id: string; name: string; size: number; category: string }

export default function CloudStoragePage() {
  const [rows, setRows] = React.useState<StorageRow[]>([]);
  const [usage, setUsage] = React.useState(0);
  const [count, setCount] = React.useState(0);
  const [error, setError] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(true);

  const load = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetchCloudStorage();
      setUsage(res.usage_bytes);
      setCount(res.artifact_count);
      setRows(res.largest ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load storage');
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => { load(); }, [load]);

  const columns: Column<StorageRow>[] = [
    { key: 'id', header: 'Artifact', render: (r) => <span className="oa-code">{r.id.slice(0, 12)}</span> },
    { key: 'name', header: 'Name', accessor: (r) => r.name },
    { key: 'size', header: 'Size (bytes)', accessor: (r) => r.size },
    { key: 'category', header: 'Category', accessor: (r) => r.category },
  ];

  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader
            title="Storage"
            description="Object storage usage, largest artifacts and retention."
            breadcrumbs={[{ label: 'Home', href: '/' }, { label: 'Cloud', href: '/cloud' }, { label: 'Storage' }]}
          />
          <div className="grid gap-4 md:grid-cols-2">
            <Card><CardHeader><CardTitle>Usage</CardTitle></CardHeader><CardContent><p className="text-3xl font-semibold">{(usage / 1048576).toFixed(1)} MB</p><p className="oa-caption">{count} active artifacts</p></CardContent></Card>
            <Card><CardHeader><CardTitle>Retention</CardTitle></CardHeader><CardContent><p className="oa-caption">Retention is enforced per organization policy (Cloud settings). Expired artifacts move to EXPIRED, then are garbage-collected.</p></CardContent></Card>
          </div>
          <DataTable columns={columns} rows={rows} keyOf={(r) => r.id} loading={loading} error={error} onRetry={load} emptyTitle="No artifacts" emptyDescription="Artifacts appear here after cloud executions produce outputs." />
          <Link href="/cloud" className="oa-caption hover:underline">Back to Cloud overview</Link>
        </div>
      </Layout>
    </Protected>
  );
}
