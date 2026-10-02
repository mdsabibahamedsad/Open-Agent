'use client';

import * as React from 'react';
import Link from 'next/link';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { DataTable, Column } from '@/components/ui/table';
import { StatusBadge } from '@/components/ui/status';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select } from '@/components/ui/form';
import {
  fetchSsoConfigs, createSsoConfig, testSsoConfig, enableSsoConfig,
  disableSsoConfig, claimDomain, verifyDomain, fetchGroupMappings,
  upsertGroupMapping, type SsoConfig,
} from '@/lib/enterprise';

export default function SsoPage() {
  const [configs, setConfigs] = React.useState<SsoConfig[]>([]);
  const [mappings, setMappings] = React.useState<{ id: string; group: string; role: string; sensitive: boolean }[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [name, setName] = React.useState('');
  const [provider, setProvider] = React.useState('oidc');
  const [issuer, setIssuer] = React.useState('');
  const [domain, setDomain] = React.useState('');
  const [challenge, setChallenge] = React.useState('');
  const [testEmail, setTestEmail] = React.useState('');
  const [preview, setPreview] = React.useState('');
  const [group, setGroup] = React.useState('');
  const [role, setRole] = React.useState('member');

  const load = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [c, m] = await Promise.all([fetchSsoConfigs(), fetchGroupMappings().catch(() => ({ mappings: [] }))]);
      setConfigs(c.configurations ?? []);
      setMappings(m.mappings ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load SSO');
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => { load(); }, [load]);

  const columns: Column<SsoConfig>[] = [
    { key: 'name', header: 'Provider', accessor: (c) => `${c.name} (${c.type})` },
    { key: 'issuer', header: 'Issuer', render: (c) => <span className="oa-code">{c.issuer || '—'}</span> },
    { key: 'status', header: 'Status', render: (c) => <StatusBadge status={c.status} /> },
    {
      key: 'actions', header: 'Actions',
      render: (c) => (
        <span className="flex gap-2">
          {c.status !== 'ACTIVE' ? (
            <Button variant="outline" size="sm" onClick={async () => {
              if (!confirm('Enable SSO? A verified domain is required first.')) return;
              try { await enableSsoConfig(c.id); await load(); }
              catch (e) { alert(e instanceof Error ? e.message : 'Enable failed'); }
            }}>Enable</Button>
          ) : (
            <Button variant="outline" size="sm" onClick={async () => { await disableSsoConfig(c.id); await load(); }}>Disable</Button>
          )}
          <Button variant="outline" size="sm" onClick={async () => {
            const email = testEmail || 'user@example.com';
            const res = await testSsoConfig(c.id, email, []);
            setPreview(`role=${res.proposed_role} teams=${res.proposed_teams.join(',')} warnings=${res.warnings.join(';')}`);
          }}>Test</Button>
        </span>
      ),
    },
  ];

  const mapColumns: Column<{ id: string; group: string; role: string; sensitive: boolean }>[] = [
    { key: 'group', header: 'External group', render: (m) => <span className="oa-code">{m.group}</span> },
    { key: 'role', header: 'Role', accessor: (m) => m.role },
    { key: 'sensitive', header: 'Sensitive', render: (m) => <span>{m.sensitive ? 'YES — review' : 'no'}</span> },
  ];

  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader
            title="Single Sign-On"
            description="Choose provider → metadata → verify domain → test → preview mapping → enable."
            breadcrumbs={[{ label: 'Home', href: '/' }, { label: 'Enterprise', href: '/settings/enterprise' }, { label: 'SSO' }]}
          />
          <Card>
            <CardHeader><CardTitle>New provider (draft)</CardTitle></CardHeader>
            <CardContent>
              <form className="flex flex-col gap-2 sm:flex-row" onSubmit={async (e) => {
                e.preventDefault();
                await createSsoConfig({ provider_type: provider, name, issuer });
                setName(''); setIssuer(''); await load();
              }}>
                <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Display name" aria-label="Provider name" />
                <Select value={provider} onChange={(e) => setProvider(e.target.value)} aria-label="Provider type">
                  <option value="oidc">OIDC</option>
                  <option value="saml">SAML</option>
                  <option value="oauth2">OAuth 2.0</option>
                </Select>
                <Input value={issuer} onChange={(e) => setIssuer(e.target.value)} placeholder="Issuer URL" aria-label="Issuer" />
                <Button type="submit">Create draft</Button>
              </form>
            </CardContent>
          </Card>
          <DataTable columns={columns} rows={configs} keyOf={(c) => c.id} loading={loading} error={error} onRetry={load} emptyTitle="No SSO providers" emptyDescription="Add an OIDC or SAML provider to start." />
          <Card>
            <CardHeader><CardTitle>Domain verification</CardTitle></CardHeader>
            <CardContent>
              <div className="flex flex-col gap-2 sm:flex-row">
                <Input value={domain} onChange={(e) => setDomain(e.target.value)} placeholder="example.com" aria-label="Domain" className="sm:w-64" />
                <Button variant="outline" onClick={async () => {
                  const res = await claimDomain(domain);
                  setChallenge(res.challenge);
                }}>Claim</Button>
                <Input value={challenge} onChange={(e) => setChallenge(e.target.value)} placeholder="published challenge" aria-label="Challenge" className="sm:w-64" />
                <Button variant="outline" onClick={async () => {
                  await verifyDomain(domain, challenge);
                  setChallenge('verified');
                }}>Verify</Button>
              </div>
              {challenge && challenge !== 'verified' ? <p className="oa-code">Publish TXT: {challenge}</p> : null}
              <div className="flex gap-2">
                <Input value={testEmail} onChange={(e) => setTestEmail(e.target.value)} placeholder="test email for preview" aria-label="Test email" className="sm:w-64" />
                {preview ? <span className="oa-caption">{preview}</span> : null}
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Group mapping</CardTitle></CardHeader>
            <CardContent>
              <form className="flex gap-2" onSubmit={async (e) => {
                e.preventDefault();
                const res = await upsertGroupMapping({ external_group: group, role });
                if (res.warning) alert(res.warning);
                setGroup(''); await load();
              }}>
                <Input value={group} onChange={(e) => setGroup(e.target.value)} placeholder="External group" aria-label="External group" />
                <Select value={role} onChange={(e) => setRole(e.target.value)} aria-label="Role">
                  <option value="member">member</option>
                  <option value="developer">developer</option>
                  <option value="admin">admin</option>
                  <option value="viewer">viewer</option>
                </Select>
                <Button type="submit">Map</Button>
              </form>
              <DataTable columns={mapColumns} rows={mappings} keyOf={(m) => m.id} loading={loading} error={error} emptyTitle="No mappings" />
            </CardContent>
          </Card>
          <Link href="/settings/enterprise" className="oa-caption hover:underline">Back to Enterprise Security</Link>
        </div>
      </Layout>
    </Protected>
  );
}
