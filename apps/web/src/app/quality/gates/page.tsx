'use client';

import * as React from 'react';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { DataTable, type Column } from '@/components/ui/table';
import { PermissionGate } from '@/components/PermissionGate';
import { useQualityGates } from '@/features/quality/quality-api';

export default function GatesPage() {
  const { gates, isLoading } = useQualityGates();
  const columns: Column<{ id: string; name: string; failure_behavior: string }>[] = [
    { key: 'name', header: 'Gate', accessor: (r) => r.name },
    { key: 'behavior', header: 'On failure', accessor: (r) => r.failure_behavior },
    { key: 'id', header: 'ID', accessor: (r) => <span className="font-mono text-xs">{r.id}</span> },
  ];
  return (
    <Protected>
      <Layout>
        <PermissionGate permission="evaluation:read" fallback={<p className="p-6">Evaluation view access required.</p>}>
          <PageHeader
            title="Quality Gates"
            description="Reusable required-check bundles with thresholds and failure behavior."
          />
          <div className="p-6">
            <DataTable
              columns={columns}
              rows={gates}
              keyOf={(r) => r.id}
              loading={isLoading}
              emptyTitle="No gates"
              emptyDescription="Built-in and organization gates appear here."
            />
          </div>
        </PermissionGate>
      </Layout>
    </Protected>
  );
}
