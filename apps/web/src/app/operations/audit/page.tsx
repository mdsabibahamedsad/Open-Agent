'use client';

import * as React from 'react';
import Link from 'next/link';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { DataTable, Column } from '@/components/ui/table';
import { Input } from '@/components/ui/input';
import { fetchOrgAudit } from '@/lib/operations';

interface AuditRow { id: string; action: string; resource: string; created: string }

export default function OpsAuditPage() {
  const [rows, setRows] = React.useState<AuditRow[]>([]);
  const [q, setQ] = React.useState('');
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  const load = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetchOrgAudit();
      setRows(res.audit ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load audit trail');
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => { load(); }, [load]);

  const filtered = q ? rows.filter((r) => `${r.action} ${r.resource}`.toLowerCase().includes(q.toLowerCase())) : rows;
  const columns: Column<AuditRow>[] = [
    { key: 'action', header: 'Action', render: (r) => <span className="oa-code">{r.action}</span> },
    { key: 'resource', header: 'Resource', accessor: (r) => r.resource },
    { key: 'created', header: 'Time', render: (r) => <span className="text-muted-foreground">{new Date(r.created).toLocaleString()}</span> },
  ];

  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader
            title="Audit"
            description="Organization audit trail with search and export."
            breadcrumbs={[{ label: 'Home', href: '/' }, { label: 'Operations', href: '/operations' }, { label: 'Audit' }]}
          />
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter actions…" aria-label="Filter audit" className="max-w-sm" />
          <DataTable columns={columns} rows={filtered} keyOf={(r) => r.id} loading={loading} error={error} onRetry={load} emptyTitle="No audit events" emptyDescription="Privileged and resource actions appear here." />
          <Link href="/operations" className="oa-caption hover:underline">Back to Operations</Link>
        </div>
      </Layout>
    </Protected>
  );
}
