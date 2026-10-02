'use client';

import * as React from 'react';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { DataTable, type Column } from '@/components/ui/table';
import { StatusBadge } from '@/components/ui/status';
import { PermissionGate } from '@/components/PermissionGate';
import { useToast } from '@/components/ui/toast';
import { toUserMessage } from '@/lib/api';
import { useWebhooks } from '@/features/integrations/integrations-api';
import type { WebhookRecord } from '@/features/integrations/types';

export default function WebhooksPage() {
  const { webhooks, isLoading, error, refetch } = useWebhooks();
  const { toast } = useToast();

  React.useEffect(() => {
    if (error) toast({ kind: 'error', title: 'Failed to load webhooks', description: toUserMessage(error) });
  }, [error, toast]);

  const columns: Column<WebhookRecord>[] = [
    { key: 'connector', header: 'Connector', accessor: (r) => r.connector_id },
    { key: 'endpoint', header: 'Endpoint', accessor: (r) => <span className="font-mono text-xs">/{r.endpoint}</span> },
    { key: 'events', header: 'Events', accessor: (r) => (r.event_types.length > 0 ? r.event_types.join(', ') : 'all') },
    { key: 'mode', header: 'Verify', accessor: (r) => r.verify_mode },
    { key: 'sig', header: 'Signature', accessor: (r) => (r.last_signature_ok === null ? '—' : r.last_signature_ok ? 'valid' : 'INVALID') },
    { key: 'fail', header: 'Failures', accessor: (r) => r.failure_count },
    { key: 'status', header: 'Status', accessor: (r) => <StatusBadge status={r.is_active ? 'active' : 'disabled'} /> },
  ];

  return (
    <Protected>
      <Layout>
        <PermissionGate permission="webhook:read" fallback={<p className="p-6">Webhook view access required.</p>}>
          <div className="oa-page">
            <PageHeader
              title="Inbound webhooks"
              description="Provider endpoints with signature status. Secrets are never exposed — only hashes and prefixes."
              breadcrumbs={[{ label: 'Home', href: '/' }, { label: 'Integrations', href: '/integrations' }, { label: 'Webhooks' }]}
            />
            <DataTable
              columns={columns}
              rows={webhooks}
              keyOf={(r) => r.id}
              loading={isLoading}
              error={error ? toUserMessage(error) : null}
              onRetry={() => refetch()}
              emptyTitle="No webhook endpoints"
              emptyDescription="Register endpoints from a connection detail page."
            />
          </div>
        </PermissionGate>
      </Layout>
    </Protected>
  );
}
