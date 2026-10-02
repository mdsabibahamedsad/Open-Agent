'use client';

import { Suspense } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import * as React from 'react';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { Input } from '@/components/ui/input';
import { Select } from '@/components/ui/form';
import { DataTable, Column } from '@/components/ui/table';
import { StatusBadge } from '@/components/ui/status';
import { Button } from '@/components/ui/button';
import { PageLoading } from '@/components/ui/loading';
import { useOrgScopedList, useSearchParamsState } from '@/lib/queries';
import { Search } from 'lucide-react';
import type { RunSummary } from '@/types';

function RunsPageContent() {
  const [q, setQ] = React.useState('');
  const [status, setStatus] = React.useState('');
  const router = useRouter();
  const debounced = useSearchParamsState(q);
  const { items, total, isLoading, error, refetch } = useOrgScopedList<RunSummary>(
    'runs',
    ['/organizations/{orgId}/runs', '/runs', '/organizations/{orgId}/executions', '/executions'],
    { ...(debounced ? { search: debounced } : {}), ...(status ? { status } : {}) },
  );

  const columns: Column<RunSummary>[] = [
    { 
      key: 'id', 
      header: 'Run', 
      accessor: (r) => r.id, 
      render: (r) => <Link href={`/runs/${r.id}`} className="oa-code hover:underline">{r.id.slice(0, 8)}</Link> 
    },
    { key: 'workflow', header: 'Workflow', render: (r) => <Link href={`/workflows/${r.workflow_id}`} className="font-medium hover:underline">{r.workflow_name ?? '—'}</Link> },
    { key: 'status', header: 'Status', render: (r) => <StatusBadge status={r.status} /> },
    { key: 'started', header: 'Started', render: (r) => <span className="text-muted-foreground">{r.started_at ? new Date(r.started_at).toLocaleString() : '—'}</span> },
  ];

  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader
            title="Runs"
            description="Monitor executions. Live log streaming ships with the execution engine."
            breadcrumbs={[{ label: 'Home', href: '/' }, { label: 'Runs' }]}
          />
          <div className="flex flex-col gap-2 sm:flex-row">
            <div className="relative w-full max-w-sm">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
              <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search runs…" aria-label="Search runs" className="pl-9" />
            </div>
            <Select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Filter by status" className="sm:w-48">
              <option value="">All statuses</option>
              <option value="queued">Queued</option>
              <option value="running">Running</option>
              <option value="completed">Completed</option>
              <option value="failed">Failed</option>
              <option value="cancelled">Cancelled</option>
            </Select>
          </div>
          <DataTable
            columns={columns}
            rows={status ? items.filter((r) => r.status === status) : items}
            keyOf={(r) => r.id}
            loading={isLoading}
            error={error}
            onRetry={() => refetch()}
            emptyTitle="No executions yet"
            emptyDescription="Runs will appear here when you execute agents or workflows."
            emptyAction={
              <Button onClick={() => router.push('/workflows/new')}>
                Create workflow
              </Button>
            }
          />
          <p className="oa-caption">{total} run{total === 1 ? '' : 's'}</p>
        </div>
      </Layout>
    </Protected>
  );
}

export default function RunsPage() {
  return (
    <Suspense fallback={<div className="oa-page"><PageLoading label="Loading runs…" /></div>}>
      <RunsPageContent />
    </Suspense>
  );
}
