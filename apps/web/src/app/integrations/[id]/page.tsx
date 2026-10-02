'use client';

import * as React from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { Breadcrumbs, PageHeader } from '@/components/ui/page';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { DataTable, type Column } from '@/components/ui/table';
import { StatusBadge } from '@/components/ui/status';
import { PermissionGate } from '@/components/PermissionGate';
import { useToast } from '@/components/ui/toast';
import { toUserMessage, api } from '@/lib/api';
import { useOrganization } from '@/context/OrganizationContext';
import { useConnector, useConnectorActions, useConnectionMutations, useConnections } from '@/features/integrations/integrations-api';
import { riskTone, trustTone, type ConnectorAction } from '@/features/integrations/types';
import { cn } from '@/lib/utils';

export default function ConnectorDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const { connector, isLoading, error } = useConnector(id);
  const { actions } = useConnectorActions(id);
  const { items: connections } = useConnections({ connector_id: id });
  const { create, execute } = useConnectionMutations();
  const { toast } = useToast();
  const { currentOrgId } = useOrganization();
  const [connecting, setConnecting] = React.useState(false);
  const [execAction, setExecAction] = React.useState('');
  const [execConnection, setExecConnection] = React.useState('');
  const [execInput, setExecInput] = React.useState('{}');
  const [execResult, setExecResult] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (error) toast({ kind: 'error', title: 'Failed to load connector', description: toUserMessage(error) });
  }, [error, toast]);

  const detail = (connector ?? {}) as Record<string, unknown>;
  const capabilities = (detail.capabilities ?? []) as Array<{ id: string; description: string; risk_level: string }>;
  const triggers = (detail.triggers ?? []) as Array<{ id: string; name: string; kind: string; event_types: string[] }>;
  const auth = (detail.auth ?? {}) as Record<string, unknown>;

  const onConnect = async () => {
    setConnecting(true);
    try {
      const created = await create.mutateAsync({
        connector_id: id,
        name: `${String(detail.name ?? id)} connection`,
        granted_capabilities: capabilities.map((c) => c.id),
      });
      const createdId = (created as { id: string }).id;
      if (String(auth.type ?? '') === 'oauth2') {
        const redirect = `${window.location.origin}/integrations/connected/${createdId}`;
        const init = await api.post<{ authorize_url: string; scopes: string[] }>(
          `/organizations/${currentOrgId}/integration-connections/${createdId}/connect`,
          { redirect_uri: redirect },
        );
        toast({
          kind: 'success',
          title: 'Approve requested scopes, then authorize',
          description: `Scopes: ${(init.scopes ?? []).join(', ') || 'none'}`,
        });
        window.location.href = init.authorize_url;
      } else {
        toast({ kind: 'success', title: 'Connection created — attach a credential to activate' });
      }
    } catch (e) {
      toast({ kind: 'error', title: 'Connect failed', description: toUserMessage(e) });
    } finally {
      setConnecting(false);
    }
  };

  const onExecute = async () => {
    if (!execAction || connections.length === 0) return;
    let input: Record<string, unknown> = {};
    try {
      input = JSON.parse(execInput || '{}') as Record<string, unknown>;
    } catch {
      toast({ kind: 'error', title: 'Invalid JSON input' });
      return;
    }
    try {
      const res = await execute.mutateAsync({ id: execConnection || connections[0].id, action_id: execAction, input });
      setExecResult(JSON.stringify(res, null, 2));
    } catch (e) {
      setExecResult(`ERROR: ${toUserMessage(e)}`);
    }
  };
  const selectedAction = actions.find((a) => a.id === execAction);
  const schemaProps = ((selectedAction?.input_schema as Record<string, unknown> | undefined)?.properties as Record<string, Record<string, unknown>> | undefined) ?? {};
  const schemaRequired = new Set(
    (((selectedAction?.input_schema as Record<string, unknown> | undefined)?.required as string[] | undefined) ?? []),
  );
  const setField = (key: string, raw: string) => {
    let current: Record<string, unknown> = {};
    try {
      current = (JSON.parse(execInput || '{}') as Record<string, unknown>) ?? {};
    } catch {
      current = {};
    }
    const spec = schemaProps[key] ?? {};
    const type = String(spec.type ?? 'string');
    let value: unknown = raw;
    if (raw === '' && !schemaRequired.has(key)) {
      delete current[key];
    } else if (type === 'number' || type === 'integer') {
      const n = Number(raw);
      value = Number.isFinite(n) ? n : raw;
      current[key] = value;
    } else if (type === 'boolean') {
      current[key] = raw === 'true' || raw === '1' || raw.toLowerCase() === 'yes';
    } else if (type === 'array') {
      try {
        current[key] = JSON.parse(raw);
      } catch {
        current[key] = raw.split(',').map((s) => s.trim()).filter(Boolean);
      }
    } else if (type === 'object') {
      try {
        current[key] = JSON.parse(raw || '{}');
      } catch {
        toast({ kind: 'error', title: `Invalid JSON for '${key}'` });
        return;
      }
    } else {
      current[key] = raw;
    }
    setExecInput(JSON.stringify(current, null, 2));
  };

  const actionColumns: Column<ConnectorAction>[] = [
    { key: 'action', header: 'Action', accessor: (r) => <span className="font-mono text-xs">{r.id}</span> },
    { key: 'desc', header: 'Description', accessor: (r) => r.description },
    {
      key: 'risk',
      header: 'Risk',
      accessor: (r) => (
        <span className={cn('inline-flex rounded-full border px-2.5 py-0.5 text-xs font-medium', riskTone(r.risk_level))}>
          {r.risk_level}
        </span>
      ),
    },
    { key: 'caps', header: 'Capabilities', accessor: (r) => r.required_capabilities.join(', ') },
  ];

  return (
    <Protected>
      <Layout>
        <PermissionGate permission="connector:read" fallback={<p className="p-6">Connector view access required.</p>}>
          <div className="space-y-6 p-6">
            <Breadcrumbs items={[{ label: 'Integrations', href: '/integrations' }, { label: 'Catalog', href: '/integrations/catalog' }, { label: id }]} />
            {isLoading && <p>Loading…</p>}
            {connector && (
              <>
                <PageHeader
                  title={String(detail.name ?? id)}
                  description={String(detail.description ?? '')}
                  actions={
                    <>
                      <span className={cn('inline-flex rounded-full border px-2.5 py-0.5 text-xs font-medium', trustTone(String(detail.trust ?? '')))}>
                        {String(detail.trust ?? '')}
                      </span>
                      <StatusBadge status={String(detail.status ?? 'active')} />
                      <PermissionGate permission="connector:create">
                        <Button onClick={onConnect} loading={connecting}>Connect</Button>
                      </PermissionGate>
                    </>
                  }
                />
                <div className="grid gap-6 lg:grid-cols-2">
                  <section className="rounded-lg border p-4">
                    <h2 className="font-semibold">Authentication</h2>
                    <dl className="mt-2 space-y-1 text-sm">
                      <div className="grid grid-cols-3 gap-2"><dt className="text-muted-foreground">Type</dt><dd className="col-span-2">{String(auth.type ?? 'none')}</dd></div>
                      <div className="grid grid-cols-3 gap-2"><dt className="text-muted-foreground">Scopes</dt><dd className="col-span-2 break-words">{(detail.scopes as string[] | undefined)?.join(', ') || '—'}</dd></div>
                      <div className="grid grid-cols-3 gap-2"><dt className="text-muted-foreground">Version</dt><dd className="col-span-2 font-mono text-xs">{String(detail.version ?? '')}</dd></div>
                      <div className="grid grid-cols-3 gap-2"><dt className="text-muted-foreground">Publisher</dt><dd className="col-span-2">{String(detail.publisher ?? '')}</dd></div>
                    </dl>
                    <h3 className="mt-4 font-semibold">Capabilities</h3>
                    <ul className="mt-1 space-y-1 text-sm">
                      {capabilities.map((c) => (
                        <li key={c.id}><span className="font-mono text-xs">{c.id}</span> <span className="text-muted-foreground">· {c.risk_level}</span></li>
                      ))}
                    </ul>
                    <h3 className="mt-4 font-semibold">Triggers</h3>
                    <ul className="mt-1 space-y-1 text-sm">
                      {triggers.map((t) => (
                        <li key={t.id}><span className="font-mono text-xs">{t.id}</span> <span className="text-muted-foreground">· {t.kind}</span></li>
                      ))}
                      {triggers.length === 0 && <li className="text-muted-foreground">No triggers.</li>}
                    </ul>
                  </section>
                  <section className="space-y-4">
                    <div className="rounded-lg border p-4">
                      <h2 className="font-semibold">Try an action</h2>
                      <p className="text-sm text-muted-foreground">Runs through policy → risk → approval → execution → verification.</p>
                      <div className="mt-2 flex flex-wrap gap-2">
                        <select
                          value={execConnection}
                          onChange={(e) => setExecConnection(e.target.value)}
                          className="rounded-md border border-input bg-background px-3 py-2 text-sm"
                          aria-label="Connection"
                        >
                          <option value="">Select connection…</option>
                          {connections.map((c) => (
                            <option key={c.id} value={c.id}>{c.name}</option>
                          ))}
                        </select>
                        <select
                          value={execAction}
                          onChange={(e) => { setExecAction(e.target.value); setExecInput('{}'); }}
                          className="rounded-md border border-input bg-background px-3 py-2 text-sm"
                          aria-label="Action"
                        >
                          <option value="">Select action…</option>
                          {actions.map((a) => (
                            <option key={a.id} value={a.id}>{a.id}</option>
                          ))}
                        </select>
                        <Button onClick={onExecute} loading={execute.isPending} disabled={!execAction || !execConnection}>
                          Run
                        </Button>
                      </div>
                      {selectedAction && Object.keys(schemaProps).length > 0 && (
                        <div className="mt-3 grid gap-2">
                          {Object.entries(schemaProps).map(([key, spec]) => (
                            <label key={key} className="grid gap-1 text-sm">
                              <span>
                                <span className="font-mono text-xs">{key}</span>
                                {' '}<span className="text-muted-foreground">· {String(spec.type ?? 'string')}{schemaRequired.has(key) ? ' · required' : ''}</span>
                              </span>
                              {Array.isArray((spec as Record<string, unknown>).enum) ? (
                                <select
                                  className="rounded-md border border-input bg-background px-3 py-2 text-sm"
                                  aria-label={key}
                                  onChange={(e) => setField(key, e.target.value)}
                                  defaultValue=""
                                >
                                  <option value="">Select…</option>
                                  {((spec as Record<string, unknown>).enum as unknown[]).map((v) => (
                                    <option key={String(v)} value={String(v)}>{String(v)}</option>
                                  ))}
                                </select>
                              ) : String(spec.type ?? '') === 'boolean' ? (
                                <select
                                  className="rounded-md border border-input bg-background px-3 py-2 text-sm"
                                  aria-label={key}
                                  onChange={(e) => setField(key, e.target.value)}
                                  defaultValue=""
                                >
                                  <option value="">Select…</option>
                                  <option value="true">true</option>
                                  <option value="false">false</option>
                                </select>
                              ) : (
                                <Input
                                  aria-label={key}
                                  placeholder={String((spec as Record<string, unknown>).description ?? key)}
                                  onChange={(e) => setField(key, e.target.value)}
                                  className="font-mono text-xs"
                                />
                              )}
                            </label>
                          ))}
                        </div>
                      )}
                      <details className="mt-3">
                        <summary className="cursor-pointer text-sm text-muted-foreground">Advanced: raw JSON input</summary>
                        <Input
                          value={execInput}
                          onChange={(e) => setExecInput(e.target.value)}
                          placeholder='{"key": "value"}'
                          aria-label="Action input JSON"
                          className="mt-2 min-w-52 flex-1 font-mono text-xs"
                        />
                      </details>
                      {connections.length === 0 && (
                        <p className="mt-2 text-sm text-muted-foreground">Create a connection first to execute actions.</p>
                      )}
                      {execResult && (
                        <pre className="mt-2 max-h-64 overflow-auto rounded bg-secondary p-2 text-xs">{execResult}</pre>
                      )}
                    </div>
                    <div className="rounded-lg border p-4">
                      <h2 className="font-semibold">Connections ({connections.length})</h2>
                      <ul className="mt-2 space-y-1 text-sm">
                        {connections.map((c) => (
                          <li key={c.id}>
                            <Link href={`/integrations/connected/${c.id}`} className="hover:underline">{c.name}</Link>
                            {' '}<StatusBadge status={c.status} />
                          </li>
                        ))}
                        {connections.length === 0 && <li className="text-muted-foreground">No connections yet.</li>}
                      </ul>
                    </div>
                  </section>
                </div>
                <div className="rounded-lg border p-4">
                  <h2 className="font-semibold">Actions ({actions.length})</h2>
                  <DataTable columns={actionColumns} rows={actions} keyOf={(r) => r.id} emptyTitle="No actions" />
                </div>
                <Link href="/integrations/catalog" className="text-sm text-primary hover:underline">Back to catalog</Link>
              </>
            )}
          </div>
        </PermissionGate>
      </Layout>
    </Protected>
  );
}
