'use client';

import * as React from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { DataTable, Column } from '@/components/ui/table';
import { StatusBadge } from '@/components/ui/status';
import { useOrganization } from '@/context/OrganizationContext';
import { getProject, listDeployments, DeploymentRow } from '@/lib/developer';
import { toUserMessage } from '@/lib/api';

export default function DeveloperProjectDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const { currentOrgId } = useOrganization();
  const detail = useQuery({
    queryKey: ['dev-project', currentOrgId, id],
    queryFn: () => getProject(currentOrgId ?? '', id),
    enabled: !!currentOrgId && !!id,
  });
  const deployments = useQuery({
    queryKey: ['dev-deployments', currentOrgId],
    queryFn: () => listDeployments(currentOrgId ?? ''),
    enabled: !!currentOrgId,
  });
  const recent: DeploymentRow[] = (deployments.data ?? []).slice(0, 10);
  const depCols: Column<DeploymentRow>[] = [
    { key: 'env', header: 'Environment', render: (r) => <span>{r.environment}</span> },
    { key: 'ext', header: 'Extension', render: (r) => <span className="oa-code">{r.extension.slice(0, 8)}</span> },
    { key: 'status', header: 'Status', render: (r) => <StatusBadge status={r.status} /> },
  ];

  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader
            title={detail.data?.slug ?? 'Project'}
            description={detail.data?.name}
            breadcrumbs={[{ label: 'Developer', href: '/developer' }, { label: 'Projects', href: '/developer/projects' }, { label: detail.data?.slug ?? id }]}
          />
          {detail.isLoading && <p className="text-sm text-muted-foreground">Loading project…</p>}
          {detail.error && <p className="text-sm text-destructive" role="alert">{toUserMessage(detail.error)}</p>}
          {detail.data && (
            <>
              <div className="flex items-center gap-2">
                <StatusBadge status={detail.data.status ?? 'active'} />
                {detail.data.description && <p className="text-sm text-muted-foreground">{detail.data.description}</p>}
              </div>
              <div className="grid gap-4 md:grid-cols-2">
                <Card>
                  <CardHeader><CardTitle className="text-base">Environments</CardTitle></CardHeader>
                  <CardContent>
                    {detail.data.environments.length === 0 ? (
                      <p className="text-sm text-muted-foreground">No environments configured.</p>
                    ) : (
                      <ul className="space-y-2 text-sm">
                        {detail.data.environments.map((e) => (
                          <li key={e.name} className="flex items-center justify-between rounded border px-3 py-2">
                            <span className="font-medium">{e.name}</span>
                            <span className="text-muted-foreground">{e.endpoint || 'no endpoint set'}</span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </CardContent>
                </Card>
                <Card>
                  <CardHeader><CardTitle className="text-base">Extensions in this project</CardTitle></CardHeader>
                  <CardContent>
                    {detail.data.extensions.length === 0 ? (
                      <p className="text-sm text-muted-foreground">
                        No extensions yet. <Link href="/developer/extensions/new" className="text-primary underline">Build one</Link>.
                      </p>
                    ) : (
                      <ul className="space-y-1 text-sm">
                        {detail.data.extensions.map((s) => <li key={s} className="oa-code w-fit">{s}</li>)}
                      </ul>
                    )}
                  </CardContent>
                </Card>
              </div>
              <section aria-label="Recent deployments">
                <h2 className="mb-2 text-lg font-semibold">Recent deployments (org-wide)</h2>
                <DataTable
                  columns={depCols} rows={recent} keyOf={(r) => r.id}
                  loading={deployments.isLoading}
                  error={deployments.error ? toUserMessage(deployments.error) : null}
                  onRetry={() => deployments.refetch()}
                  emptyTitle="No deployments yet"
                  emptyDescription="Deploy an extension version to see pipeline history here."
                />
              </section>
            </>
          )}
        </div>
      </Layout>
    </Protected>
  );
}
