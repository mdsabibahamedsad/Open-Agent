'use client';

import * as React from 'react';
import Link from 'next/link';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { StatusBadge } from '@/components/ui/status';
import { DataTable, Column } from '@/components/ui/table';
import { fetchPlatformOverview, fetchPlatformFlags, fetchPlatformBackups } from '@/lib/operations';

export default function CommandCenterPage() {
  const [overview, setOverview] = React.useState<{ health: { status: string }; open_alerts: number; open_incidents: number; audit_chain: string } | null>(null);
  const [flags, setFlags] = React.useState<{ key: string; scope: string; enabled: boolean; strategy: string }[]>([]);
  const [backups, setBackups] = React.useState<Record<string, { status: string }>>({});
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [o, f, b] = await Promise.all([
          fetchPlatformOverview(),
          fetchPlatformFlags().catch(() => ({ flags: [] })),
          fetchPlatformBackups().catch(() => ({ backups: {} })),
        ]);
        if (!cancelled) {
          setOverview(o);
          setFlags(f.flags ?? []);
          setBackups(b.backups ?? {});
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Platform control unavailable (Master Account required)');
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const flagColumns: Column<{ key: string; scope: string; enabled: boolean; strategy: string }>[] = [
    { key: 'key', header: 'Flag', render: (f) => <span className="oa-code">{f.key}</span> },
    { key: 'scope', header: 'Scope', accessor: (f) => f.scope },
    { key: 'enabled', header: 'Enabled', render: (f) => <span>{f.enabled ? 'on' : 'off'}</span> },
    { key: 'strategy', header: 'Strategy', accessor: (f) => f.strategy },
  ];

  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader
            title="Command Center"
            description="Platform administration: health, incidents, flags, backups and audit."
            breadcrumbs={[{ label: 'Home', href: '/' }, { label: 'Command Center' }]}
          />
          {error ? <Card><CardContent><p className="oa-caption">{error}</p></CardContent></Card> : (
            <div className="grid gap-4 md:grid-cols-2">
              <Card>
                <CardHeader><CardTitle>Platform health</CardTitle></CardHeader>
                <CardContent>
                  {overview ? (
                    <>
                      <StatusBadge status={(overview.health as { status: string }).status ?? 'UNKNOWN'} />
                      <p className="oa-caption">{overview.open_alerts} firing alerts · {overview.open_incidents} open incidents</p>
                      <p className="oa-caption">Audit: {overview.audit_chain}</p>
                    </>
                  ) : <p className="oa-caption">Loading…</p>}
                </CardContent>
              </Card>
              <Card>
                <CardHeader><CardTitle>Backups</CardTitle></CardHeader>
                <CardContent>
                  {Object.keys(backups).length === 0 ? <p className="oa-caption">No backup reports yet.</p> : (
                    <ul>{Object.entries(backups).map(([kind, b]) => <li key={kind} className="oa-caption">{kind}: {b.status}</li>)}</ul>
                  )}
                </CardContent>
              </Card>
              <Card>
                <CardHeader><CardTitle>Feature flags</CardTitle></CardHeader>
                <CardContent>
                  <DataTable columns={flagColumns} rows={flags} keyOf={(f) => `${f.scope}:${f.key}`} loading={false} error={null} emptyTitle="No flags" />
                </CardContent>
              </Card>
            </div>
          )}
          <Link href="/" className="oa-caption hover:underline">Back home</Link>
        </div>
      </Layout>
    </Protected>
  );
}
