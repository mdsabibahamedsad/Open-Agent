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
import { useEvaluations, useQualityOverview } from '@/features/quality/quality-api';
import { decisionTone, type EvaluationRecord } from '@/features/quality/types';
import { cn } from '@/lib/utils';

const TABS = [
  { key: '', label: 'All' },
  { key: 'FAILED', label: 'Failures' },
  { key: 'UNCERTAIN', label: 'Uncertain' },
  { key: 'PASSED', label: 'Passed' },
] as const;

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="rounded-lg border p-4">
      <div className="text-2xl font-semibold">{value}</div>
      <div className="text-sm text-muted-foreground">{label}</div>
    </div>
  );
}

export default function QualityPage() {
  const [tab, setTab] = React.useState<string>('');
  const [agentFilter, setAgentFilter] = React.useState('');
  const [workflowFilter, setWorkflowFilter] = React.useState('');
  const { items, isLoading, error, refetch } = useEvaluations(
    tab || agentFilter || workflowFilter
      ? {
          status: tab || undefined,
          agent_id: agentFilter || undefined,
          workflow_id: workflowFilter || undefined,
        }
      : undefined,
  );
  const { overview, refetch: refetchOverview } = useQualityOverview();
  const { toast } = useToast();

  React.useEffect(() => {
    if (error) toast({ kind: 'error', title: 'Failed to load evaluations', description: toUserMessage(error) });
  }, [error, toast]);

  const columns: Column<EvaluationRecord>[] = [
    {
      key: 'type',
      header: 'Type',
      accessor: (r) => (
        <Link href={`/quality/evaluations/${r.id}`} className="font-medium hover:underline">
          {r.evaluation_type}
        </Link>
      ),
    },
    {
      key: 'decision',
      header: 'Decision',
      accessor: (r) => (
        <span className={cn('inline-flex rounded-full border px-2.5 py-0.5 text-xs font-medium', decisionTone(r.decision))}>
          {r.decision ?? '—'}
        </span>
      ),
    },
    {
      key: 'score',
      header: 'Score',
      accessor: (r) => (typeof r.score === 'number' ? `${(r.score * 100).toFixed(1)}%` : '—'),
    },
    { key: 'failure', header: 'Failure', accessor: (r) => r.failure_class ?? r.uncertainty_reason ?? '—' },
    { key: 'status', header: 'Status', accessor: (r) => <StatusBadge status={r.status} /> },
    {
      key: 'completed',
      header: 'Completed',
      accessor: (r) => (r.completed_at ? new Date(r.completed_at).toLocaleString() : '—'),
    },
  ];

  const byDecision = overview?.by_decision ?? {};
  const pass = byDecision.PASS ?? 0;
  const fail = byDecision.FAIL ?? 0;
  const total = pass + fail;

  return (
    <Protected>
      <Layout>
        <PermissionGate permission="evaluation:read" fallback={<p className="p-6">Evaluation view access required.</p>}>
          <PageHeader
            title="Quality Center"
            description="Verify agent work with observable evidence — never claims alone."
            actions={
              <Button variant="outline" onClick={() => { refetch(); refetchOverview(); }}>
                Refresh
              </Button>
            }
          />
          <div className="grid gap-3 px-6 pt-4 sm:grid-cols-2 lg:grid-cols-4">
            <Stat label="Pass rate" value={total ? `${Math.round((pass / total) * 100)}%` : '—'} />
            <Stat label="Failed" value={fail} />
            <Stat label="Uncertain (needs human)" value={overview?.by_status?.UNCERTAIN ?? 0} />
            <Stat label="Open corrections" value={overview?.open_correction_plans ?? 0} />
          </div>
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
            <Link href="/quality/gates" className="rounded-full border px-3 py-1 text-sm hover:underline">
              Gates
            </Link>
            <Link href="/quality/benchmarks" className="rounded-full border px-3 py-1 text-sm hover:underline">
              Benchmarks
            </Link>
            <input
              value={agentFilter}
              onChange={(e) => setAgentFilter(e.target.value)}
              placeholder="Filter by agent ID"
              className="rounded-full border border-input bg-background px-3 py-1 text-sm"
              aria-label="Filter by agent ID"
            />
            <input
              value={workflowFilter}
              onChange={(e) => setWorkflowFilter(e.target.value)}
              placeholder="Filter by workflow ID"
              className="rounded-full border border-input bg-background px-3 py-1 text-sm"
              aria-label="Filter by workflow ID"
            />
          </div>
          <div className="p-6">
            <DataTable
              columns={columns}
              rows={items}
              keyOf={(r) => r.id}
              loading={isLoading}
              error={error ? toUserMessage(error) : null}
              onRetry={() => refetch()}
              emptyTitle="No evaluations"
              emptyDescription="Evaluations appear here once agent work is verified."
            />
          </div>
        </PermissionGate>
      </Layout>
    </Protected>
  );
}
