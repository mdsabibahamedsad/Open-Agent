'use client';

import * as React from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select } from '@/components/ui/form';
import { DataTable, type Column } from '@/components/ui/table';
import { StatusBadge } from '@/components/ui/status';
import { ConfirmDialog } from '@/components/ui/dialog';
import { CreateWorkflowDialog } from '@/components/workflows/CreateWorkflowDialog';
import { PermissionGate } from '@/components/PermissionGate';
import { useToast } from '@/components/ui/toast';
import { toUserMessage } from '@/lib/api';
import { useSearchParamsState } from '@/lib/queries';
import { useWorkflows, useWorkflowMutations } from '@/features/workflows/workflows-api';
import type { WorkflowRecord } from '@/features/workflows/types';
import { Plus, Search, Pencil, Copy, Trash2 } from 'lucide-react';

export default function WorkflowsPage() {
  const [q, setQ] = React.useState('');
  const [status, setStatus] = React.useState('');
  const [createOpen, setCreateOpen] = React.useState(false);
  const [deleting, setDeleting] = React.useState<WorkflowRecord | null>(null);
  const debounced = useSearchParamsState(q);
  const { items, total, isLoading, error, refetch } = useWorkflows(
    debounced || status ? { search: debounced || undefined, status: status || undefined } : undefined,
  );
  const { duplicate, remove } = useWorkflowMutations();
  const { toast } = useToast();
  const router = useRouter();

  const onDuplicate = async (wf: WorkflowRecord) => {
    try {
      const copy = await duplicate.mutateAsync(wf.id);
      toast({ kind: 'success', title: `Duplicated as “${copy.name}”` });
      router.push(`/workflows/${copy.id}`);
    } catch (e) {
      toast({ kind: 'error', title: 'Duplicate failed', description: toUserMessage(e) });
    }
  };

  const onDelete = async () => {
    if (!deleting) return;
    try {
      await remove.mutateAsync(deleting.id);
      toast({ kind: 'success', title: `Deleted “${deleting.name}”` });
      setDeleting(null);
    } catch (e) {
      toast({ kind: 'error', title: 'Delete failed', description: toUserMessage(e) });
    }
  };

  const columns: Column<WorkflowRecord>[] = [
    {
      key: 'name', header: 'Name', sortable: true, accessor: (r) => r.name,
      render: (r) => (
        <span>
          <Link href={`/workflows/${r.id}`} className="font-medium text-primary hover:underline">{r.name}</Link>
          <span className="oa-caption ml-2">{r.slug}</span>
        </span>
      ),
    },
    { key: 'status', header: 'Status', render: (r) => <StatusBadge status={r.status || 'draft'} /> },
    {
      key: 'versions', header: 'Versions',
      render: (r) => <span className="tabular-nums text-muted-foreground">{r.version_count}</span>,
    },
    {
      key: 'updated', header: 'Updated',
      render: (r) => <span className="text-muted-foreground">{r.updated_at ? new Date(r.updated_at).toLocaleDateString() : '—'}</span>,
    },
    {
      key: 'actions', header: '', className: 'text-right',
      render: (r) => (
        <span className="flex justify-end gap-1" onClick={(e) => e.stopPropagation()}>
          <Link href={`/workflows/${r.id}/edit`} aria-label={`Edit ${r.name}`} className="rounded-md p-2 hover:bg-accent">
            <Pencil className="h-4 w-4" />
          </Link>
          <PermissionGate permission="workflow:create">
            <button aria-label={`Duplicate ${r.name}`} className="rounded-md p-2 hover:bg-accent" onClick={() => onDuplicate(r)}>
              <Copy className="h-4 w-4" />
            </button>
          </PermissionGate>
          <PermissionGate permission="workflow:delete">
            <button aria-label={`Delete ${r.name}`} className="rounded-md p-2 text-destructive hover:bg-destructive/10" onClick={() => setDeleting(r)}>
              <Trash2 className="h-4 w-4" />
            </button>
          </PermissionGate>
        </span>
      ),
    },
  ];

  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader
            title="Workflows"
            description="Author multi-step automations in the visual builder. Execution ships in a later phase."
            breadcrumbs={[{ label: 'Home', href: '/' }, { label: 'Workflows' }]}
            actions={
              <PermissionGate permission="workflow:create">
                <Button onClick={() => setCreateOpen(true)}><Plus className="mr-2 h-4 w-4" />New workflow</Button>
              </PermissionGate>
            }
          />
          <div className="flex flex-col gap-2 sm:flex-row">
            <div className="relative w-full max-w-sm">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
              <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search workflows…" aria-label="Search workflows" className="pl-9" />
            </div>
            <Select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Filter by status" className="sm:w-44">
              <option value="">All statuses</option>
              <option value="draft">Draft</option>
              <option value="active">Active</option>
              <option value="archived">Archived</option>
            </Select>
          </div>
          <DataTable
            columns={columns}
            rows={items}
            keyOf={(r) => r.id}
            loading={isLoading}
            error={error}
            onRetry={() => refetch()}
            emptyTitle="No workflows yet"
            emptyDescription="Create your first workflow to automate your AI workforce — start blank or from a template."
            emptyAction={
              <PermissionGate permission="workflow:create">
                <Button onClick={() => setCreateOpen(true)}><Plus className="mr-2 h-4 w-4" />New workflow</Button>
              </PermissionGate>
            }
          />
          <p className="oa-caption">{total} workflow{total === 1 ? '' : 's'}</p>
        </div>
      </Layout>

      <CreateWorkflowDialog open={createOpen} onClose={() => setCreateOpen(false)} />

      <ConfirmDialog
        open={!!deleting}
        onClose={() => setDeleting(null)}
        onConfirm={onDelete}
        title={`Delete “${deleting?.name}”?`}
        description="The workflow and its versions will be archived from this list. Past executions are preserved."
        confirmLabel="Delete"
        danger
      />
    </Protected>
  );
}
