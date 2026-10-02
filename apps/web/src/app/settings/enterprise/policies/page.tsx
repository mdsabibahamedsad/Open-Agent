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
import { fetchSecurityPolicies, simulatePolicy, type SecurityPolicyRow } from '@/lib/enterprise';

export default function PoliciesPage() {
  const [rows, setRows] = React.useState<SecurityPolicyRow[]>([]);
  const [policyId, setPolicyId] = React.useState('');
  const [action, setAction] = React.useState('workflow.execute');
  const [result, setResult] = React.useState('');
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  const load = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetchSecurityPolicies();
      setRows(res.policies ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load policies');
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => { load(); }, [load]);

  const columns: Column<SecurityPolicyRow>[] = [
    { key: 'id', header: 'Policy', render: (p) => <span className="oa-code">{p.id.slice(0, 8)}</span> },
    { key: 'scope', header: 'Scope', accessor: (p) => p.scope },
    { key: 'version', header: 'Version', accessor: (p) => p.version },
    { key: 'sections', header: 'Sections', render: (p) => <span className="oa-caption">{p.sections.join(', ')}</span> },
  ];

  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader
            title="Security Policies"
            description="Versioned policies with a safe simulator (ALLOW / DENY / STEP-UP)."
            breadcrumbs={[{ label: 'Home', href: '/' }, { label: 'Enterprise', href: '/settings/enterprise' }, { label: 'Policies' }]}
          />
          <Card>
            <CardHeader><CardTitle>Policy simulator</CardTitle></CardHeader>
            <CardContent>
              <form className="flex flex-col gap-2 sm:flex-row" onSubmit={async (e) => {
                e.preventDefault();
                const res = await simulatePolicy({ policy_id: policyId, actor: 'admin', action, environment: 'PRODUCTION', context: {} });
                setResult(`${res.verdict}: ${res.explanation}`);
              }}>
                <Input value={policyId} onChange={(e) => setPolicyId(e.target.value)} placeholder="Policy id" aria-label="Policy id" />
                <Input value={action} onChange={(e) => setAction(e.target.value)} placeholder="Action" aria-label="Action" />
                <Button type="submit">Simulate</Button>
              </form>
              {result ? <p className="oa-caption">{result}</p> : null}
            </CardContent>
          </Card>
          <DataTable columns={columns} rows={rows} keyOf={(p) => p.id} loading={loading} error={error} onRetry={load} emptyTitle="No policies" emptyDescription="Create versioned security policies via the API." />
          <Link href="/settings/enterprise" className="oa-caption hover:underline">Back to Enterprise Security</Link>
        </div>
      </Layout>
    </Protected>
  );
}
