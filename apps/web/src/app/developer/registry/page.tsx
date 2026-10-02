'use client';

import { useQuery } from '@tanstack/react-query';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { DataTable, Column } from '@/components/ui/table';
import { listLocalPackages } from '@/lib/developer';
import { toUserMessage } from '@/lib/api';

export default function LocalRegistryPage() {
  const query = useQuery({ queryKey: ['local-registry'], queryFn: listLocalPackages, staleTime: 30_000 });
  const rows = query.data?.packages ?? [];
  const cols: Column<{ artifact: string }>[] = [
    { key: 'a', header: 'Artifact', render: (r) => <span className="oa-code">{r.artifact}</span> },
  ];
  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader title="Local registry" description="Offline .oaext packages on this host. Honest empty state when the registry directory is absent."
            breadcrumbs={[{ label: 'Developer', href: '/developer' }, { label: 'Registry' }]} />
          {query.data && (
            <p className="text-sm text-muted-foreground">Registry directory: <span className="oa-code">{query.data.registry || '(not configured)'}</span></p>
          )}
          <DataTable columns={cols} rows={rows} keyOf={(r) => r.artifact}
            loading={query.isLoading}
            error={query.error ? toUserMessage(query.error) : null}
            onRetry={() => query.refetch()}
            emptyTitle="No local packages"
            emptyDescription="Package an extension (detail → Package), then copy the .oaext artifact into the local registry directory for offline installs." />
          <div className="grid gap-4 md:grid-cols-2">
            <Card>
              <CardHeader><CardTitle className="text-base">Publish locally</CardTitle>
                <CardDescription>Deterministic builds — same manifest + files, same digest.</CardDescription></CardHeader>
              <CardContent><pre className="overflow-auto rounded bg-muted p-3 text-xs">oa ext package &lt;id&gt;{"\n"}cp dist/*.oaext $OPENAGENT_LOCAL_REGISTRY/{"\n"}oa registry list-local</pre></CardContent>
            </Card>
            <Card>
              <CardHeader><CardTitle className="text-base">Install offline</CardTitle></CardHeader>
              <CardContent><pre className="overflow-auto rounded bg-muted p-3 text-xs">oa ext install &lt;id&gt; --version 1.0.0 --env production{"\n"}# installs verify digest + signature before activation</pre></CardContent>
            </Card>
          </div>
        </div>
      </Layout>
    </Protected>
  );
}
