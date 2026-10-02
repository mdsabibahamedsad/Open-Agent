'use client';

import Link from 'next/link';
import { useWorkflowExecutions, useWorkflowVersions } from '@/features/workflows/workflows-api';
import { DataTable, type Column } from '@/components/ui/table';
import { StatusBadge } from '@/components/ui/status';
import type { WorkflowExecutionRecord, WorkflowVersionRecord } from '@/features/workflows/types';

export function VersionHistory({
  workflowId,
  currentVersion,
  onPreview,
  onRestore,
  restoring,
}: {
  workflowId: string;
  currentVersion?: string;
  onPreview?: (v: WorkflowVersionRecord) => void;
  onRestore?: (v: WorkflowVersionRecord) => void;
  restoring?: boolean;
}) {
  const { versions, isLoading, refetch } = useWorkflowVersions(workflowId);

  const columns: Column<WorkflowVersionRecord>[] = [
    { key: 'version', header: 'Version', render: (r) => <span className="oa-code">{r.version}</span> },
    {
      key: 'status', header: 'Status',
      render: (r) => <StatusBadge status={r.status === 'published' ? 'published' : 'draft'} />,
    },
    {
      key: 'nodes', header: 'Graph',
      render: (r) => (
        <span className="text-muted-foreground">
          {r.definition.triggers.length}T · {r.definition.nodes.length}N · {r.definition.edges.length}E
        </span>
      ),
    },
    {
      key: 'created', header: 'Created',
      render: (r) => <span className="text-muted-foreground">{new Date(r.created_at).toLocaleString()}</span>,
    },
    {
      key: 'actions', header: '', className: 'text-right',
      render: (r) => (
        <span className="flex justify-end gap-3">
          {onPreview && (
            <button className="text-sm text-primary hover:underline" onClick={() => onPreview(r)}>
              Preview
            </button>
          )}
          {onRestore && r.version !== currentVersion && (
            <button
              className="text-sm text-primary hover:underline disabled:opacity-40"
              disabled={restoring}
              onClick={() => onRestore(r)}
              aria-label={`Restore version ${r.version} as a new draft`}
            >
              Restore
            </button>
          )}
          {onRestore && r.version === currentVersion && (
            <span className="oa-caption">Current</span>
          )}
        </span>
      ),
    },
  ];

  return (
    <DataTable
      columns={columns}
      rows={versions}
      keyOf={(r) => r.id}
      loading={isLoading}
      onRetry={() => refetch()}
      emptyTitle="No versions yet"
      emptyDescription="Versions are created every time you save a changed definition. They are immutable snapshots."
    />
  );
}

export function RunHistory({ workflowId }: { workflowId: string }) {
  const { items, total, isLoading, refetch } = useWorkflowExecutions(workflowId);

  const columns: Column<WorkflowExecutionRecord>[] = [
    { key: 'id', header: 'Run', render: (r) => <Link href={`/runs/${r.id}`} className="oa-code hover:underline">{r.id.slice(0, 8)}</Link> },
    { key: 'status', header: 'Status', render: (r) => <StatusBadge status={r.status} /> },
    { key: 'trigger', header: 'Trigger', render: (r) => <span className="capitalize">{r.trigger_type}</span> },
    {
      key: 'started', header: 'Started',
      render: (r) => <span className="text-muted-foreground">{r.started_at ? new Date(r.started_at).toLocaleString() : '—'}</span>,
    },
    {
      key: 'error', header: 'Error',
      render: (r) => r.error_message
        ? <span className="max-w-xs truncate text-destructive" title={r.error_message}>{r.error_message}</span>
        : <span className="text-muted-foreground">—</span>,
    },
  ];

  return (
    <>
      <DataTable
        columns={columns}
        rows={items}
        keyOf={(r) => r.id}
        loading={isLoading}
        onRetry={() => refetch()}
        emptyTitle="No runs yet"
        emptyDescription="Execution history appears here once the execution engine ships. Runs are never faked."
      />
      <p className="oa-caption mt-2">{total} run{total === 1 ? '' : 's'}</p>
    </>
  );
}
