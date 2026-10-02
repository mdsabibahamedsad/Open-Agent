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
import { useApprovals } from '@/features/approvals/approvals-api';
import { riskTone, type ApprovalRecord } from '@/features/approvals/types';
import { cn } from '@/lib/utils';

const TABS = [
  { key: 'PENDING', label: 'Pending' },
  { key: '', label: 'All' },
  { key: 'APPROVED', label: 'Approved' },
  { key: 'REJECTED', label: 'Rejected' },
  { key: 'EXPIRED', label: 'Expired' },
] as const;

export default function ApprovalsPage() {
  const [tab, setTab] = React.useState<string>('PENDING');
  const { items, total, isLoading, error, refetch } = useApprovals(tab ? { status: tab } : undefined);
  const { toast } = useToast();

  React.useEffect(() => {
    if (error) toast({ kind: 'error', title: 'Failed to load approvals', description: toUserMessage(error) });
  }, [error, toast]);

  const columns: Column<ApprovalRecord>[] = [
    {
      key: 'action',
      header: 'Action',
      accessor: (r) => (
        <Link href={`/approvals/${r.id}`} className="font-medium hover:underline">
          {r.action_description || r.action_type || r.id.slice(0, 8)}
        </Link>
      ),
    },
    { key: 'category', header: 'Category', accessor: (r) => r.action_category ?? '—' },
    {
      key: 'risk',
      header: 'Risk',
      accessor: (r) => (
        <span className={cn('inline-flex rounded-full border px-2.5 py-0.5 text-xs font-medium', riskTone(r.risk_level))}>
          {r.risk_level ?? '—'}{typeof r.risk_score === 'number' ? ` · ${r.risk_score}` : ''}
        </span>
      ),
    },
    { key: 'target', header: 'Target', accessor: (r) => r.target_reference || r.target_id || '—' },
    { key: 'status', header: 'Status', accessor: (r) => <StatusBadge status={r.status} /> },
    {
      key: 'expires',
      header: 'Expires',
      accessor: (r) => (r.expires_at ? new Date(r.expires_at).toLocaleString() : '—'),
    },
  ];

  return (
    <Protected>
      <Layout>
        <PermissionGate permission="approval:read" fallback={<p className="p-6">Approval view access required.</p>}>
          <PageHeader
            title="Approval Center"
            description="Review and decide human-gated agent actions. Nothing executes without a persisted approval."
            actions={<Button variant="outline" onClick={() => refetch()}>Refresh</Button>}
          />
          <div className="flex gap-2 px-6 pt-4">
            {TABS.map((t) => (
              <button
                key={t.label}
                onClick={() => setTab(t.key)}
                className={cn(
                  'rounded-full border px-3 py-1 text-sm',
                  tab === t.key ? 'bg-primary text-primary-foreground' : 'bg-secondary',
                )}
              >
                {t.label}
              </button>
            ))}
          </div>
          <div className="p-6">
            <DataTable
              columns={columns}
              rows={items}
              keyOf={(r) => r.id}
              loading={isLoading}
              error={error ? toUserMessage(error) : null}
              onRetry={() => refetch()}
              emptyTitle="No approvals"
              emptyDescription={tab === 'PENDING' ? 'Nothing waiting for review.' : 'No requests in this state yet.'}
              total={total}
            />
          </div>
        </PermissionGate>
      </Layout>
    </Protected>
  );
}
