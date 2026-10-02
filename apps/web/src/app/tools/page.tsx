'use client';

import * as React from 'react';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { Input } from '@/components/ui/input';
import { DataTable, Column } from '@/components/ui/table';
import { StatusBadge } from '@/components/ui/status';
import { useOrgScopedList, useSearchParamsState } from '@/lib/queries';
import { Search } from 'lucide-react';

interface ToolRow { id: string; name: string; category?: string; status?: string; }

export default function ToolsPage() {
  const [q, setQ] = React.useState('');
  const debounced = useSearchParamsState(q);
  const { items, isLoading, error, refetch } = useOrgScopedList<ToolRow>(
    'tools', ['/organizations/{orgId}/tools', '/tools'], debounced ? { search: debounced } : undefined,
  );
  const columns: Column<ToolRow>[] = [
    { key: 'name', header: 'Tool', sortable: true, accessor: (r) => r.name, render: (r) => <span className="font-medium">{r.name}</span> },
    { key: 'cat', header: 'Category', render: (r) => <span className="text-muted-foreground">{r.category ?? '—'}</span> },
    { key: 'status', header: 'Status', render: (r) => <StatusBadge status={r.status ?? 'active'} /> },
  ];
  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader title="Tools" description="Tool and plugin catalog foundation. Full Tool system ships later." breadcrumbs={[{ label: 'Home', href: '/' }, { label: 'Tools' }]} />
          <div className="relative w-full max-w-sm">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search tools…" aria-label="Search tools" className="pl-9" />
          </div>
          <DataTable columns={columns} rows={items} keyOf={(r) => r.id} loading={isLoading} error={error} onRetry={() => refetch()}
            emptyTitle="No tools installed" emptyDescription="The tool registry will list installed and available tools here once the backend exposes them." />
        </div>
      </Layout>
    </Protected>
  );
}
