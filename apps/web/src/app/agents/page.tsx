'use client';

import * as React from 'react';
import Link from 'next/link';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { DataTable, Column } from '@/components/ui/table';
import { StatusBadge } from '@/components/ui/status';
import { PermissionGate } from '@/components/PermissionGate';
import { useOrgScopedList } from '@/lib/queries';
import { useSearchParamsState } from '@/lib/queries';
import { Plus, Search } from 'lucide-react';
import type { AgentSummary } from '@/types';

export default function AgentsPage() {
  const [q, setQ] = React.useState('');
  const debounced = useSearchParamsState(q);
  const { items, total, isLoading, error, refetch } = useOrgScopedList<AgentSummary>(
    'agents',
    ['/organizations/{orgId}/agents', '/agents'],
    debounced ? { search: debounced } : undefined,
  );

  const columns: Column<AgentSummary>[] = [
    { key: 'name', header: 'Name', sortable: true, accessor: (r) => r.name, render: (r) => <span className="font-medium">{r.name}</span> },
    { key: 'status', header: 'Status', render: (r) => <StatusBadge status={r.status || 'draft'} /> },
    { key: 'model', header: 'Model', render: (r) => <span className="text-muted-foreground">{r.model ?? '—'}</span> },
    { key: 'updated', header: 'Updated', render: (r) => <span className="text-muted-foreground">{r.updated_at ? new Date(r.updated_at).toLocaleDateString() : '—'}</span> },
  ];

  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader
            title="Agents"
            description="Build and operate autonomous agents. Runtime arrives in a later phase; this list is backend-driven."
            breadcrumbs={[{ label: 'Home', href: '/' }, { label: 'Agents' }]}
            actions={
              <PermissionGate permission="agent:create">
                <Button><Plus className="mr-2 h-4 w-4" />Create agent</Button>
              </PermissionGate>
            }
          />
          <div className="flex items-center gap-2">
            <div className="relative w-full max-w-sm">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
              <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search agents…" aria-label="Search agents" className="pl-9" />
            </div>
          </div>
          <DataTable
            columns={columns}
            rows={items}
            keyOf={(r) => r.id}
            loading={isLoading}
            error={error}
            onRetry={() => refetch()}
            emptyTitle="No agents yet"
            emptyDescription="Create your first agent to give your workforce capabilities. The full agent runtime ships in a later phase."
            emptyAction={<Button><Plus className="mr-2 h-4 w-4" />Create agent</Button>}
          />
          <p className="oa-caption">{total} agent{total === 1 ? '' : 's'} · URL-synchronized search coming with backend filters</p>
        </div>
      </Layout>
    </Protected>
  );
}
