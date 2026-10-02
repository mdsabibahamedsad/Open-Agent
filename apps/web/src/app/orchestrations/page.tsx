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
import { Plus } from 'lucide-react';
import { useCreateOrchestration, useOrchestrations } from '@/features/orchestrations/api';
import type { OrchestrationSummary } from '@/features/orchestrations/types';

export default function OrchestrationsPage() {
  const { items, total, isLoading, error, refetch } = useOrchestrations();
  const create = useCreateOrchestration();
  const [objective, setObjective] = React.useState('');
  const [formError, setFormError] = React.useState<string | null>(null);

  const columns: Column<OrchestrationSummary>[] = [
    {
      key: 'objective',
      header: 'Objective',
      accessor: (r) => r.objective,
      render: (r) => (
        <Link href={`/orchestrations/${r.id}`} className="font-medium underline-offset-4 hover:underline">
          {r.objective.length > 80 ? `${r.objective.slice(0, 80)}…` : r.objective}
        </Link>
      ),
    },
    { key: 'status', header: 'Status', render: (r) => <StatusBadge status={r.status} /> },
    {
      key: 'created',
      header: 'Created',
      render: (r) => (
        <span className="text-muted-foreground">{new Date(r.created_at).toLocaleString()}</span>
      ),
    },
  ];

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError(null);
    if (!objective.trim()) {
      setFormError('Objective is required.');
      return;
    }
    try {
      await create.mutateAsync({ objective: objective.trim() });
      setObjective('');
      void refetch();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : 'Failed to create orchestration.');
    }
  };

  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader
            title="Orchestrations"
            description="Coordinate teams of specialized agents on complex objectives."
            breadcrumbs={[{ label: 'Home', href: '/' }, { label: 'Orchestrations' }]}
          />
          <PermissionGate permission="agent:create">
            <form onSubmit={submit} className="flex flex-col gap-2 rounded-lg border p-4 sm:flex-row sm:items-center">
              <Input
                value={objective}
                onChange={(e) => setObjective(e.target.value)}
                placeholder="e.g. Research the AI automation market and prepare a SaaS proposal"
                aria-label="New orchestration objective"
                className="flex-1"
              />
              <Button type="submit" disabled={create.isPending}>
                <Plus className="mr-2 h-4 w-4" />
                {create.isPending ? 'Creating…' : 'New orchestration'}
              </Button>
            </form>
            {formError && (
              <p role="alert" className="text-sm text-destructive">
                {formError}
              </p>
            )}
          </PermissionGate>
          <DataTable
            columns={columns}
            rows={items}
            keyOf={(r) => r.id}
            loading={isLoading}
            error={error}
            onRetry={() => refetch()}
            emptyTitle="No orchestrations yet"
            emptyDescription="Create one above to coordinate a team of agents."
            total={total}
          />
        </div>
      </Layout>
    </Protected>
  );
}
