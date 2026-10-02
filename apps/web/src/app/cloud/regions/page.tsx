'use client';

import * as React from 'react';
import Link from 'next/link';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { DataTable, Column } from '@/components/ui/table';
import { StatusBadge } from '@/components/ui/status';
import { fetchCloudRegions, type CloudRegion } from '@/lib/cloud';

export default function CloudRegionsPage() {
  const [regions, setRegions] = React.useState<CloudRegion[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  const load = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetchCloudRegions();
      setRegions(res.regions ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load regions');
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => { load(); }, [load]);

  const columns: Column<CloudRegion>[] = [
    { key: 'region', header: 'Region', render: (r) => <span className="oa-code">{r.region}</span> },
    { key: 'name', header: 'Name', accessor: (r) => r.name },
    { key: 'health', header: 'Health', render: (r) => <StatusBadge status={r.health} /> },
    { key: 'caps', header: 'Capabilities', render: (r) => <span className="oa-caption">{(r.capabilities ?? []).join(', ') || '—'}</span> },
  ];

  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader
            title="Regions"
            description="Regional capacity, health and data-residency placement."
            breadcrumbs={[{ label: 'Home', href: '/' }, { label: 'Cloud', href: '/cloud' }, { label: 'Regions' }]}
          />
          <DataTable columns={columns} rows={regions} keyOf={(r) => r.region} loading={loading} error={error} onRetry={load} emptyTitle="No regions" emptyDescription="Regions are seeded on migration (local-1)." />
          <Link href="/cloud" className="oa-caption hover:underline">Back to Cloud overview</Link>
        </div>
      </Layout>
    </Protected>
  );
}
