'use client';

import * as React from 'react';
import Link from 'next/link';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { StatusBadge } from '@/components/ui/status';
import { PageLoading } from '@/components/ui/loading';
import { fetchOpsHealth, fetchOpsAlerts, fetchOpsIncidents, type OpsHealth } from '@/lib/operations';

export default function OperationsOverviewPage() {
  const [health, setHealth] = React.useState<OpsHealth | null>(null);
  const [alerts, setAlerts] = React.useState(0);
  const [incidents, setIncidents] = React.useState(0);
  const [error, setError] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [h, a, i] = await Promise.all([
          fetchOpsHealth(),
          fetchOpsAlerts({ status: 'FIRING' }).catch(() => ({ alerts: [] })),
          fetchOpsIncidents().catch(() => ({ incidents: [] })),
        ]);
        if (!cancelled) {
          setHealth(h);
          setAlerts((a.alerts ?? []).length);
          setIncidents((i.incidents ?? []).filter((x) => !['RESOLVED', 'CLOSED'].includes(x.status)).length);
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Operations unavailable');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader
            title="Operations"
            description="Command center: health, alerts, incidents, deployments and audit."
            breadcrumbs={[{ label: 'Home', href: '/' }, { label: 'Operations' }]}
          />
          {loading ? <PageLoading label="Loading operations…" /> : error ? (
            <Card><CardContent><p className="oa-caption">{error}</p></CardContent></Card>
          ) : (
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
              <Card>
                <CardHeader><CardTitle>Platform</CardTitle></CardHeader>
                <CardContent>
                  <StatusBadge status={health?.status ?? 'UNKNOWN'} />
                  <p className="oa-caption">Public status: {health?.public}</p>
                </CardContent>
              </Card>
              <Card>
                <CardHeader><CardTitle>Firing alerts</CardTitle></CardHeader>
                <CardContent>
                  <p className="text-3xl font-semibold">{alerts}</p>
                  <Link href="/operations/alerts" className="oa-caption hover:underline">View alerts</Link>
                </CardContent>
              </Card>
              <Card>
                <CardHeader><CardTitle>Open incidents</CardTitle></CardHeader>
                <CardContent>
                  <p className="text-3xl font-semibold">{incidents}</p>
                  <Link href="/operations/incidents" className="oa-caption hover:underline">View incidents</Link>
                </CardContent>
              </Card>
              <Card>
                <CardHeader><CardTitle>Maintenance</CardTitle></CardHeader>
                <CardContent>
                  <p className="text-3xl font-semibold">{health?.maintenance?.length ?? 0}</p>
                  <p className="oa-caption">upcoming windows</p>
                </CardContent>
              </Card>
            </div>
          )}
          <nav className="flex flex-wrap gap-3" aria-label="Operations sections">
            {[
              ['/operations/alerts', 'Alerts'],
              ['/operations/incidents', 'Incidents'],
              ['/operations/deployments', 'Deployments'],
              ['/operations/health', 'Health'],
              ['/operations/audit', 'Audit'],
              ['/operations/diagnostics', 'Diagnostics'],
            ].map(([href, label]) => (
              <Link key={href} href={href} className="oa-caption hover:underline">{label}</Link>
            ))}
          </nav>
        </div>
      </Layout>
    </Protected>
  );
}
