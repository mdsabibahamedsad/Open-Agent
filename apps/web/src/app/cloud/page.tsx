'use client';

import * as React from 'react';
import Link from 'next/link';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { StatusBadge } from '@/components/ui/status';
import { PageLoading } from '@/components/ui/loading';
import { fetchCloudHealth, fetchCloudQueues, fetchCloudStorage, type CloudOverview } from '@/lib/cloud';

export default function CloudOverviewPage() {
  const [overview, setOverview] = React.useState<CloudOverview | null>(null);
  const [queues, setQueues] = React.useState<{ queue: string; depth: number }[]>([]);
  const [storage, setStorage] = React.useState<{ usage_bytes: number; artifact_count: number } | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [health, q, s] = await Promise.all([
          fetchCloudHealth(),
          fetchCloudQueues().catch(() => ({ queues: [] })),
          fetchCloudStorage().catch(() => ({ usage_bytes: 0, artifact_count: 0, largest: [] })),
        ]);
        if (!cancelled) {
          setOverview(health);
          setQueues(q.queues ?? []);
          setStorage({ usage_bytes: s.usage_bytes, artifact_count: s.artifact_count });
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Cloud runtime unavailable. Enable OPENAGENT_CLOUD_ENABLED to use hosted execution.');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const queued = queues.reduce((n, q) => n + (q.depth || 0), 0);

  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader
            title="Cloud"
            description="Hosted execution: workers, queues, regions, storage and usage."
            breadcrumbs={[{ label: 'Home', href: '/' }, { label: 'Cloud' }]}
          />
          {loading ? <PageLoading label="Loading cloud overview…" /> : error ? (
            <Card><CardContent><p className="oa-caption">{error}</p></CardContent></Card>
          ) : (
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
              <Card>
                <CardHeader><CardTitle>Platform status</CardTitle></CardHeader>
                <CardContent>
                  <StatusBadge status={overview?.status ?? 'UNKNOWN'} />
                  <p className="oa-caption">Mode {overview?.incident_mode} · runtime {overview?.runtime_mode}</p>
                </CardContent>
              </Card>
              <Card>
                <CardHeader><CardTitle>Queued executions</CardTitle></CardHeader>
                <CardContent>
                  <p className="text-3xl font-semibold">{queued}</p>
                  <Link href="/cloud/queues" className="oa-caption hover:underline">View queues</Link>
                </CardContent>
              </Card>
              <Card>
                <CardHeader><CardTitle>Worker utilization</CardTitle></CardHeader>
                <CardContent>
                  <p className="text-3xl font-semibold">{Math.round((overview?.workers.utilization ?? 0) * 100)}%</p>
                  <p className="oa-caption">{overview?.workers.busy ?? 0} busy / {overview?.workers.workers ?? 0} workers</p>
                  <Link href="/cloud/workers" className="oa-caption hover:underline">View workers</Link>
                </CardContent>
              </Card>
              <Card>
                <CardHeader><CardTitle>Storage</CardTitle></CardHeader>
                <CardContent>
                  <p className="text-3xl font-semibold">{((storage?.usage_bytes ?? 0) / 1048576).toFixed(1)} MB</p>
                  <p className="oa-caption">{storage?.artifact_count ?? 0} artifacts</p>
                  <Link href="/cloud/storage" className="oa-caption hover:underline">View storage</Link>
                </CardContent>
              </Card>
            </div>
          )}
          <nav className="flex flex-wrap gap-3" aria-label="Cloud sections">
            {[
              ['/cloud/executions', 'Executions'],
              ['/cloud/workers', 'Workers'],
              ['/cloud/queues', 'Queues'],
              ['/cloud/regions', 'Regions'],
              ['/cloud/storage', 'Storage'],
              ['/cloud/health', 'Health'],
              ['/cloud/settings', 'Settings'],
            ].map(([href, label]) => (
              <Link key={href} href={href} className="oa-caption hover:underline">{label}</Link>
            ))}
          </nav>
        </div>
      </Layout>
    </Protected>
  );
}
