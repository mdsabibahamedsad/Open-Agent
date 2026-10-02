'use client';

import * as React from 'react';
import Link from 'next/link';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { Button } from '@/components/ui/button';
import { DataTable, type Column } from '@/components/ui/table';
import { StatusBadge } from '@/components/ui/status';
import { PermissionGate } from '@/components/PermissionGate';
import { useToast } from '@/components/ui/toast';
import { toUserMessage } from '@/lib/api';
import { useConnectionMutations, useConnections } from '@/features/integrations/integrations-api';
import type { ConnectionRecord } from '@/features/integrations/types';

export default function IntegrationsPage() {
  const { items, isLoading, error, refetch } = useConnections();
  const { test, disconnect, remove } = useConnectionMutations();
  const { toast } = useToast();
  const [busy, setBusy] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (error) toast({ kind: 'error', title: 'Failed to load connections', description: toUserMessage(error) });
  }, [error, toast]);

  const run = async (id: string, fn: (id: string) => Promise<unknown>, label: string) => {
    setBusy(`${label}:${id}`);
    try {
      await fn(id);
      toast({ kind: 'success', title: `Connection ${label}d` });
      refetch();
    } catch (e) {
      toast({ kind: 'error', title: `${label} failed`, description: toUserMessage(e) });
    } finally {
      setBusy(null);
    }
  };

  const columns: Column<ConnectionRecord>[] = [
    {
      key: 'name',
      header: 'Connection',
      accessor: (r) => (
        <Link href={`/integrations/connected/${r.id}`} className="font-medium hover:underline">
          {r.name || r.connector_id}
        </Link>
      ),
    },
    { key: 'connector', header: 'Connector', accessor: (r) => r.connector_id },
    { key: 'status', header: 'Status', accessor: (r) => <StatusBadge status={r.status} /> },
    {
      key: 'caps',
      header: 'Capabilities',
      accessor: (r) => (r.granted_capabilities.length > 0 ? `${r.granted_capabilities.length} granted` : '—'),
    },
    {
      key: 'actions',
      header: '',
      accessor: (r) => (
        <span className="flex gap-2">
          <Button size="sm" variant="outline" disabled={busy !== null} onClick={() => run(r.id, test.mutateAsync, 'test')}>
            Test
          </Button>
          <Button size="sm" variant="outline" disabled={busy !== null} onClick={() => run(r.id, disconnect.mutateAsync, 'disconnect')}>
            Disconnect
          </Button>
          <Button size="sm" variant="ghost" disabled={busy !== null} onClick={() => run(r.id, remove.mutateAsync, 'delete')}>
            Delete
          </Button>
        </span>
      ),
    },
  ];

  return (
    <Protected>
      <Layout>
        <PermissionGate permission="connector:read" fallback={<p className="p-6">Connector view access required.</p>}>
          <div className="oa-page">
            <PageHeader
              title="Integrations"
              description="Connected services. Only backend-confirmed links appear — nothing is faked."
              breadcrumbs={[{ label: 'Home', href: '/' }, { label: 'Integrations' }]}
              actions={
                <Link href="/integrations/catalog">
                  <Button>Browse catalog</Button>
                </Link>
              }
            />
            <DataTable
              columns={columns}
              rows={items}
              keyOf={(r) => r.id}
              loading={isLoading}
              error={error ? toUserMessage(error) : null}
              onRetry={() => refetch()}
              emptyTitle="No connections yet"
              emptyDescription="Connect GitHub, Slack, Gmail, or another provider from the catalog."
            />
          </div>
        </PermissionGate>
      </Layout>
    </Protected>
  );
}
