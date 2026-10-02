'use client';

import * as React from 'react';
import Link from 'next/link';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { DataTable, Column } from '@/components/ui/table';
import { Button } from '@/components/ui/button';
import { fetchDevices, revokeDevice } from '@/lib/enterprise';

export default function DevicesPage() {
  const [rows, setRows] = React.useState<{ id: string; key: string; platform: string; trust: string; last_seen: string | null }[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  const load = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetchDevices();
      setRows(res.devices ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load devices');
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => { load(); }, [load]);

  const columns: Column<{ id: string; key: string; platform: string; trust: string; last_seen: string | null }>[] = [
    { key: 'key', header: 'Device', render: (d) => <span className="oa-code">{d.key}</span> },
    { key: 'platform', header: 'Platform', accessor: (d) => d.platform || '—' },
    { key: 'trust', header: 'Trust', accessor: (d) => d.trust },
    {
      key: 'actions', header: 'Actions',
      render: (d) => d.trust !== 'REVOKED' ? (
        <Button variant="outline" size="sm" onClick={async () => {
          if (!confirm('Revoke this device? Its sessions stop working.')) return;
          await revokeDevice(d.id); await load();
        }}>Revoke</Button>
      ) : <span className="oa-caption">revoked</span>,
    },
  ];

  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader
            title="Devices"
            description="Device trust, last use and revocation."
            breadcrumbs={[{ label: 'Home', href: '/' }, { label: 'Enterprise', href: '/settings/enterprise' }, { label: 'Devices' }]}
          />
          <Card><CardHeader><CardTitle>Sessions</CardTitle></CardHeader><CardContent><p className="oa-caption">Use account session controls to log out sessions; revoking a device invalidates its sessions promptly.</p></CardContent></Card>
          <DataTable columns={columns} rows={rows} keyOf={(d) => d.id} loading={loading} error={error} onRetry={load} emptyTitle="No devices" emptyDescription="Devices register on login." />
          <Link href="/settings/enterprise" className="oa-caption hover:underline">Back to Enterprise Security</Link>
        </div>
      </Layout>
    </Protected>
  );
}
