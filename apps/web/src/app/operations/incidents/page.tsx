'use client';

import * as React from 'react';
import Link from 'next/link';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { DataTable, Column } from '@/components/ui/table';
import { StatusBadge } from '@/components/ui/status';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { fetchOpsIncidents, openOpsIncident, type OpsIncident } from '@/lib/operations';

export default function OpsIncidentsPage() {
  const [incidents, setIncidents] = React.useState<OpsIncident[]>([]);
  const [title, setTitle] = React.useState('');
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  const load = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetchOpsIncidents();
      setIncidents(res.incidents ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load incidents');
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => { load(); }, [load]);

  const columns: Column<OpsIncident>[] = [
    { key: 'title', header: 'Incident', render: (i) => <Link href={`/operations/incidents/${i.id}`} className="font-medium hover:underline">{i.title}</Link> },
    { key: 'severity', header: 'Severity', render: (i) => <StatusBadge status={i.severity} /> },
    { key: 'status', header: 'Status', render: (i) => <StatusBadge status={i.status} /> },
    { key: 'created', header: 'Opened', render: (i) => <span className="text-muted-foreground">{new Date(i.created).toLocaleString()}</span> },
  ];

  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader
            title="Incidents"
            description="Lifecycle, timeline, responders and resolution."
            breadcrumbs={[{ label: 'Home', href: '/' }, { label: 'Operations', href: '/operations' }, { label: 'Incidents' }]}
          />
          <form
            className="flex gap-2"
            onSubmit={async (e) => {
              e.preventDefault();
              if (!title.trim()) return;
              await openOpsIncident({ title: title.trim() });
              setTitle('');
              await load();
            }}
          >
            <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Open a new incident…" aria-label="New incident title" className="max-w-md" />
            <Button type="submit">Open incident</Button>
          </form>
          <DataTable columns={columns} rows={incidents} keyOf={(i) => i.id} loading={loading} error={error} onRetry={load} emptyTitle="No incidents" emptyDescription="Incidents appear here with full timelines." />
          <Link href="/operations" className="oa-caption hover:underline">Back to Operations</Link>
        </div>
      </Layout>
    </Protected>
  );
}
