'use client';

import * as React from 'react';
import Link from 'next/link';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { Breadcrumbs, PageHeader } from '@/components/ui/page';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { PermissionGate } from '@/components/PermissionGate';
import { useToast } from '@/components/ui/toast';
import { toUserMessage, api } from '@/lib/api';
import { useOrganization } from '@/context/OrganizationContext';

interface EndpointRow {
  name: string;
  method: string;
  path: string;
}

export default function ConnectorBuilderPage() {
  const { currentOrgId } = useOrganization();
  const { toast } = useToast();
  const [connectorId, setConnectorId] = React.useState('');
  const [name, setName] = React.useState('');
  const [baseUrl, setBaseUrl] = React.useState('https://');
  const [authType, setAuthType] = React.useState('api_key');
  const [endpoints, setEndpoints] = React.useState<EndpointRow[]>([{ name: 'List items', method: 'GET', path: '/items' }]);
  const [busy, setBusy] = React.useState(false);

  const slug = connectorId.toLowerCase().replace(/[^a-z0-9_.-]/g, '_');

  const addEndpoint = () => setEndpoints((rows) => [...rows, { name: '', method: 'GET', path: '/' }]);
  const setRow = (i: number, patch: Partial<EndpointRow>) =>
    setEndpoints((rows) => rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));

  const build = async () => {
    if (!slug || !name.trim()) {
      toast({ kind: 'error', title: 'Connector id and name are required' });
      return;
    }
    if (!baseUrl.startsWith('https://')) {
      toast({ kind: 'error', title: 'Base URL must be https' });
      return;
    }
    setBusy(true);
    try {
      const actions = endpoints.map((e, i) => ({
        id: `${slug}.${e.name.toLowerCase().replace(/[^a-z0-9]+/g, '_') || `action_${i}`}`,
        name: e.name || `Action ${i + 1}`,
        description: `${e.method} ${e.path} on ${baseUrl}`,
        input_schema: { type: 'object', properties: {}, required: [] },
        output_schema: { type: 'object' },
        required_capabilities: [`${slug}.api.use`],
        risk_level: e.method === 'GET' ? 'LOW' : 'HIGH',
        timeout_seconds: 30,
        rate_limit_per_minute: 30,
        mutation: e.method !== 'GET',
        http: { method: e.method, path: e.path },
      }));
      await api.post(`/organizations/${currentOrgId}/connectors`, {
        manifest: {
          id: slug,
          name: name.trim(),
          version: '1.0.0',
          category: 'automation',
          type: 'HTTP_GENERIC',
          trust: 'CUSTOM',
          description: `Custom API connector for ${baseUrl}. Unknown mutations default HIGH risk.`,
          auth: { type: authType, base_url: baseUrl },
          capabilities: [{ id: `${slug}.api.use`, description: 'Use custom endpoints', risk_level: 'MEDIUM' }],
          actions,
          triggers: [],
          resources: [],
          scopes: [],
        },
      });
      toast({ kind: 'success', title: `Connector '${slug}' registered` });
    } catch (e) {
      toast({ kind: 'error', title: 'Registration failed', description: toUserMessage(e) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Protected>
      <Layout>
        <PermissionGate permission="connector:admin" fallback={<p className="p-6">Connector admin access required.</p>}>
          <div className="space-y-6 p-6">
            <Breadcrumbs items={[{ label: 'Integrations', href: '/integrations' }, { label: 'Custom API builder' }]} />
            <PageHeader
              title="Custom API connector"
              description="Define a generic HTTP connector without coding. Mutations default to HIGH risk until policy says otherwise."
            />
            <section className="grid max-w-3xl gap-3 rounded-lg border p-4">
              <label className="text-sm">
                Connector id
                <Input className="mt-1 font-mono" value={connectorId} onChange={(e) => setConnectorId(e.target.value)} placeholder="acme_crm" />
              </label>
              <label className="text-sm">
                Display name
                <Input className="mt-1" value={name} onChange={(e) => setName(e.target.value)} placeholder="Acme CRM" />
              </label>
              <label className="text-sm">
                Base URL (https only — private hosts blocked)
                <Input className="mt-1 font-mono" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://api.example.com" />
              </label>
              <label className="text-sm">
                Authentication
                <select value={authType} onChange={(e) => setAuthType(e.target.value)} className="mt-1 w-full rounded-md border border-input bg-background px-3 py-2 text-sm" aria-label="Authentication type">
                  <option value="api_key">API key</option>
                  <option value="bearer_token">Bearer token</option>
                  <option value="basic">Basic auth</option>
                  <option value="oauth2">OAuth 2.0</option>
                </select>
              </label>
            </section>
            <section className="max-w-3xl rounded-lg border p-4">
              <h2 className="font-semibold">Endpoints</h2>
              {endpoints.map((row, i) => (
                <div key={i} className="mt-2 grid gap-2 sm:grid-cols-[1fr_110px_1fr]">
                  <Input value={row.name} onChange={(e) => setRow(i, { name: e.target.value })} placeholder="Action name" aria-label="Action name" />
                  <select value={row.method} onChange={(e) => setRow(i, { method: e.target.value })} className="rounded-md border border-input bg-background px-3 py-2 text-sm" aria-label="HTTP method">
                    {['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD'].map((m) => (
                      <option key={m} value={m}>{m}</option>
                    ))}
                  </select>
                  <Input value={row.path} onChange={(e) => setRow(i, { path: e.target.value })} placeholder="/items" aria-label="Path" className="font-mono" />
                </div>
              ))}
              <Button variant="outline" onClick={addEndpoint} className="mt-3">Add endpoint</Button>
            </section>
            <div className="flex gap-2">
              <Button onClick={build} loading={busy}>Validate &amp; register</Button>
              <Link href="/integrations/catalog" className="text-sm self-center text-primary hover:underline">Back to catalog</Link>
            </div>
          </div>
        </PermissionGate>
      </Layout>
    </Protected>
  );
}
