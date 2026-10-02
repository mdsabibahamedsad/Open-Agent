'use client';

import * as React from 'react';
import Link from 'next/link';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { Input } from '@/components/ui/input';
import { DataTable, type Column } from '@/components/ui/table';
import { PermissionGate } from '@/components/PermissionGate';
import { useToast } from '@/components/ui/toast';
import { toUserMessage } from '@/lib/api';
import { useSearchParamsState } from '@/lib/queries';
import { useConnectorCatalog, useSearchIntegrations } from '@/features/integrations/integrations-api';
import { trustTone, type ConnectorSummary } from '@/features/integrations/types';
import { cn } from '@/lib/utils';
import { Search } from 'lucide-react';

const CATEGORIES = [
  'ai', 'communication', 'developer', 'productivity', 'storage', 'database',
  'crm', 'marketing', 'analytics', 'finance', 'commerce', 'automation', 'infrastructure',
];

export default function ConnectorCatalogPage() {
  const [q, setQ] = React.useState('');
  const [category, setCategory] = React.useState('');
  const debounced = useSearchParamsState(q);
  const { items, isLoading, error, refetch } = useConnectorCatalog(
    debounced || category ? { search: debounced || undefined, category: category || undefined } : undefined,
  );
  const { results: actionResults, isLoading: actionLoading } = useSearchIntegrations(debounced, 'action');
  const { toast } = useToast();

  React.useEffect(() => {
    if (error) toast({ kind: 'error', title: 'Failed to load catalog', description: toUserMessage(error) });
  }, [error, toast]);

  const columns: Column<ConnectorSummary>[] = [
    {
      key: 'name',
      header: 'Connector',
      sortable: true,
      accessor: (r) => (
        <Link href={`/integrations/${r.id}`} className="font-medium hover:underline">
          {r.name}
        </Link>
      ),
    },
    { key: 'category', header: 'Category', accessor: (r) => r.category },
    {
      key: 'trust',
      header: 'Trust',
      accessor: (r) => (
        <span className={cn('inline-flex rounded-full border px-2.5 py-0.5 text-xs font-medium', trustTone(r.trust))}>
          {r.trust}
        </span>
      ),
    },
    {
      key: 'actions',
      header: 'Actions',
      accessor: (r) => `${r.actions} actions · ${r.triggers} triggers`,
    },
    { key: 'version', header: 'Version', accessor: (r) => r.version },
  ];

  return (
    <Protected>
      <Layout>
        <PermissionGate permission="connector:read" fallback={<p className="p-6">Connector view access required.</p>}>
          <div className="oa-page">
            <PageHeader
              title="Connector catalog"
              description="Search across connectors, capabilities, and actions. Trust levels drive policy."
              breadcrumbs={[{ label: 'Home', href: '/' }, { label: 'Integrations', href: '/integrations' }, { label: 'Catalog' }]}
            />
            <div className="flex flex-wrap items-center gap-3">
              <div className="relative w-full max-w-sm">
                <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
                <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search connectors or actions…" aria-label="Search connectors" className="pl-9" />
              </div>
              <select
                value={category}
                onChange={(e) => setCategory(e.target.value)}
                aria-label="Filter by category"
                className="rounded-md border border-input bg-background px-3 py-2 text-sm"
              >
                <option value="">All categories</option>
                {CATEGORIES.map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
            </div>
            <DataTable
              columns={columns}
              rows={items}
              keyOf={(r) => r.id}
              loading={isLoading}
              error={error ? toUserMessage(error) : null}
              onRetry={() => refetch()}
              emptyTitle="No connectors found"
              emptyDescription="Try a different search or category."
            />
            {debounced.trim().length > 1 && (
              <section className="mt-6 rounded-lg border p-4" aria-label="Action search">
                <h2 className="font-semibold">
                  Actions matching &ldquo;{debounced}&rdquo;{actionLoading ? '…' : ''}
                </h2>
                <p className="text-sm text-muted-foreground">
                  Capability-based discovery — agents query this endpoint instead of loading the full catalog.
                </p>
                <pre className="mt-2 max-h-64 overflow-auto rounded bg-secondary p-2 text-xs">
                  {JSON.stringify(actionResults ?? {}, null, 2)}
                </pre>
              </section>
            )}
          </div>
        </PermissionGate>
      </Layout>
    </Protected>
  );
}
