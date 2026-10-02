'use client';

import * as React from 'react';
import Link from 'next/link';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { DataTable, Column } from '@/components/ui/table';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { fetchScimCredentials, mintScimCredential } from '@/lib/enterprise';

export default function ScimPage() {
  const [rows, setRows] = React.useState<{ id: string; name: string; prefix: string; expires: string; revoked: boolean }[]>([]);
  const [name, setName] = React.useState('');
  const [token, setToken] = React.useState('');
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  const load = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetchScimCredentials();
      setRows(res.credentials ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load SCIM');
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => { load(); }, [load]);

  const columns: Column<{ id: string; name: string; prefix: string; expires: string; revoked: boolean }>[] = [
    { key: 'name', header: 'Credential', accessor: (r) => r.name },
    { key: 'prefix', header: 'Prefix', render: (r) => <span className="oa-code">{r.prefix}…</span> },
    { key: 'revoked', header: 'Revoked', render: (r) => <span>{r.revoked ? 'yes' : 'no'}</span> },
  ];

  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader
            title="SCIM Provisioning"
            description="Enable → credential → endpoint → IdP → test → monitor. Secrets shown once."
            breadcrumbs={[{ label: 'Home', href: '/' }, { label: 'Enterprise', href: '/settings/enterprise' }, { label: 'SCIM' }]}
          />
          <Card>
            <CardHeader><CardTitle>New SCIM credential</CardTitle></CardHeader>
            <CardContent>
              <form className="flex gap-2" onSubmit={async (e) => {
                e.preventDefault();
                const res = await mintScimCredential(name || 'IdP sync');
                setToken(`${res.token}  endpoint: ${res.endpoint}`);
                setName(''); await load();
              }}>
                <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Credential name" aria-label="Credential name" />
                <Button type="submit">Generate</Button>
              </form>
              {token ? <p className="oa-code">Copy now (never shown again): {token}</p> : null}
              <p className="oa-caption">Base path: /api/v1/scim/v2 (Users, Groups per SCIM 2.0).</p>
            </CardContent>
          </Card>
          <DataTable columns={columns} rows={rows} keyOf={(r) => r.id} loading={loading} error={error} onRetry={load} emptyTitle="No SCIM credentials" />
          <Link href="/settings/enterprise" className="oa-caption hover:underline">Back to Enterprise Security</Link>
        </div>
      </Layout>
    </Protected>
  );
}
