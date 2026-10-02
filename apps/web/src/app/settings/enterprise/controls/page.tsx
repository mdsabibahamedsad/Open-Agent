'use client';

import * as React from 'react';
import Link from 'next/link';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { DataTable, Column } from '@/components/ui/table';
import { fetchSecurityControls, type SecurityControlRow } from '@/lib/enterprise';

export default function ControlsPage() {
  const [rows, setRows] = React.useState<SecurityControlRow[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  const load = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetchSecurityControls();
      setRows(res.controls ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load controls');
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => { load(); }, [load]);

  const columns: Column<SecurityControlRow>[] = [
    { key: 'control', header: 'Control', render: (c) => <span className="oa-code">{c.control}</span> },
    { key: 'name', header: 'Name', accessor: (c) => c.name },
    { key: 'category', header: 'Category', accessor: (c) => c.category },
    { key: 'status', header: 'Status', accessor: (c) => c.status },
    { key: 'evidence', header: 'Evidence', accessor: (c) => c.evidence },
  ];

  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader
            title="Compliance Controls"
            description="Control framework with evidence references. No certification is claimed."
            breadcrumbs={[{ label: 'Home', href: '/' }, { label: 'Enterprise', href: '/settings/enterprise' }, { label: 'Compliance' }]}
          />
          <DataTable columns={columns} rows={rows} keyOf={(c) => c.control} loading={loading} error={error} onRetry={load} emptyTitle="No controls" emptyDescription="Define controls and attach evidence via the API." />
          <Link href="/settings/enterprise" className="oa-caption hover:underline">Back to Enterprise Security</Link>
        </div>
      </Layout>
    </Protected>
  );
}
