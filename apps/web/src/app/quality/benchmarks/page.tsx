'use client';

import * as React from 'react';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { DataTable, type Column } from '@/components/ui/table';
import { PermissionGate } from '@/components/PermissionGate';
import { useBenchmarks } from '@/features/quality/quality-api';

export default function BenchmarksPage() {
  const { benchmarks, isLoading } = useBenchmarks();
  const columns: Column<{ id: string; name: string; dataset_size: number }>[] = [
    { key: 'name', header: 'Benchmark', accessor: (r) => r.name },
    { key: 'size', header: 'Items', accessor: (r) => r.dataset_size },
    { key: 'id', header: 'ID', accessor: (r) => <span className="font-mono text-xs">{r.id}</span> },
  ];
  return (
    <Protected>
      <Layout>
        <PermissionGate permission="evaluation:read" fallback={<p className="p-6">Evaluation view access required.</p>}>
          <PageHeader
            title="Benchmarks"
            description="Internal task datasets with runs, scores, and regression comparison."
          />
          <div className="p-6">
            <DataTable
              columns={columns}
              rows={benchmarks}
              keyOf={(r) => r.id}
              loading={isLoading}
              emptyTitle="No benchmarks"
              emptyDescription="Benchmarks appear here once created via the API."
            />
          </div>
        </PermissionGate>
      </Layout>
    </Protected>
  );
}
