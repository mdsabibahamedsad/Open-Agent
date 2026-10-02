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
import { useConnections, useConnectionMutations, useWebhooks, useWebhookMutations, useCredentials } from '@/features/integrations/integrations-api';
import type { WebhookRecord } from '@/features/integrations/types';

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-3 gap-2 py-1.5 text-sm">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="col-span-2 break-words">{children}</dd>
    </div>
  );
}

export default function ConnectionDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const { items } = useConnections();
  const connection = items.find((c) => c.id === id);
  const { test, disconnect, update } = useConnectionMutations();
  const { webhooks, refetch: refetchHooks } = useWebhooks(id);
  const hooksMut = useWebhookMutations();
  const { credentials } = useCredentials();
  const { toast } = useToast();
  const { currentOrgId } = useOrganization();
  const [endpoint, setEndpoint] = React.useState('');
  const [hookSecret, setHookSecret] = React.useState<string | null>(null);

  const createWebhook = async () => {
    if (!endpoint.trim()) {
      toast({ kind: 'error', title: 'Endpoint path required' });
      return;
    }
    try {
      const res = await api.post<{ secret: string; url: string }>(
        `/organizations/${currentOrgId}/connector-webhooks?connection_id=${id}`,
        { endpoint: endpoint.trim(), verify_mode: 'hmac_sha256' },
      );
      setHookSecret(`ONE-TIME SECRET (save now): ${res.secret}\nURL: ${res.url}`);
      setEndpoint('');
      refetchHooks();
    } catch (e) {
      toast({ kind: 'error', title: 'Webhook creation failed', description: toUserMessage(e) });
    }
  };

  const hookColumns: Column<WebhookRecord>[] = [
    { key: 'endpoint', header: 'Endpoint', accessor: (r) => <span className="font-mono text-xs">/{r.endpoint}</span> },
    { key: 'events', header: 'Events', accessor: (r) => (r.event_types.length > 0 ? r.event_types.join(', ') : 'all') },
    { key: 'sig', header: 'Last signature', accessor: (r) => (r.last_signature_ok === null ? '—' : r.last_signature_ok ? 'valid' : 'INVALID') },
    { key: 'fail', header: 'Failures', accessor: (r) => r.failure_count },
    { key: 'status', header: 'Status', accessor: (r) => <StatusBadge status={r.is_active ? 'active' : 'disabled'} /> },
    {
      key: 'actions',
      header: '',
      accessor: (r) => (
        <span className="flex gap-2">
          <PermissionGate permission="webhook:update">
            <Button size="sm" variant="outline" loading={hooksMut.rotate.isPending} onClick={async () => {
              try {
                const res = await hooksMut.rotate.mutateAsync(r.id) as { secret?: string };
                setHookSecret(res?.secret ? `ONE-TIME SECRET (save now): ${res.secret}` : 'Secret rotated. New value shown only if returned once.');
                refetchHooks();
              } catch (e) {
                toast({ kind: 'error', title: 'Rotate failed', description: toUserMessage(e) });
              }
            }}>
              Rotate
            </Button>
          </PermissionGate>
          <PermissionGate permission="webhook:delete">
            <Button size="sm" variant="ghost" loading={hooksMut.remove.isPending} onClick={async () => {
              try {
                await hooksMut.remove.mutateAsync(r.id);
                toast({ kind: 'success', title: 'Webhook deleted' });
                refetchHooks();
              } catch (e) {
                toast({ kind: 'error', title: 'Delete failed', description: toUserMessage(e) });
              }
            }}>
              Delete
            </Button>
          </PermissionGate>
        </span>
      ),
    },
  ];

  const attachCredential = async (credentialId: string) => {
    if (!credentialId) return;
    try {
      await update.mutateAsync({ id, patch: { credential_id: credentialId } });
      toast({ kind: 'success', title: 'Credential attached' });
    } catch (e) {
      toast({ kind: 'error', title: 'Attach failed', description: toUserMessage(e) });
    }
  };

  return (
    <Protected>
      <Layout>
        <PermissionGate permission="connector:read" fallback={<p className="p-6">Connector view access required.</p>}>
          <div className="space-y-6 p-6">
            <Breadcrumbs items={[{ label: 'Integrations', href: '/integrations' }, { label: connection?.name ?? id.slice(0, 8) }]} />
            {!connection && <p>Loading…</p>}
            {connection && (
              <>
                <PageHeader
                  title={connection.name}
                  description={`Connector ${connection.connector_id} · v${connection.connector_version}`}
                  actions={
                    <>
                      <StatusBadge status={connection.status} />
                      <PermissionGate permission="connector:update">
                        <Button variant="outline" loading={test.isPending} onClick={async () => {
                          try {
                            await test.mutateAsync(connection.id);
                            toast({ kind: 'success', title: 'Connection test passed' });
                          } catch (e) {
                            toast({ kind: 'error', title: 'Connection test failed', description: toUserMessage(e) });
                          }
                        }}>
                          Test connection
                        </Button>
                        <Button variant="outline" loading={disconnect.isPending} onClick={async () => {
                          try {
                            await disconnect.mutateAsync(connection.id);
                            toast({ kind: 'success', title: 'Disconnected and revoked' });
                          } catch (e) {
                            toast({ kind: 'error', title: 'Disconnect failed', description: toUserMessage(e) });
                          }
                        }}>
                          Disconnect
                        </Button>
                      </PermissionGate>
                    </>
                  }
                />
                {connection.last_error && (
                  <div className="rounded-md border border-red-500/30 bg-red-500/5 p-3 text-sm" role="alert">
                    {connection.last_error}
                  </div>
                )}
                <div className="grid gap-6 lg:grid-cols-2">
                  <section className="rounded-lg border p-4">
                    <h2 className="font-semibold">Connection</h2>
                    <dl className="mt-2 divide-y divide-border">
                      <Row label="Scope">{connection.scope}</Row>
                      <Row label="Sharing">{connection.sharing_policy}</Row>
                      <Row label="Owner">{connection.owner_user_id ?? '—'}</Row>
                      <Row label="Credential">{connection.credential_id ? `${connection.credential_id.slice(0, 8)}… (encrypted)` : 'none attached'}</Row>
                      <Row label="Last used">{connection.last_used_at ? new Date(connection.last_used_at).toLocaleString() : '—'}</Row>
                    </dl>
                    <PermissionGate permission="connector:update">
                      <div className="mt-3 flex gap-2">
                        <select
                          aria-label="Attach credential"
                          className="flex-1 rounded-md border border-input bg-background px-3 py-2 text-sm"
                          defaultValue=""
                          onChange={(e) => attachCredential(e.target.value)}
                        >
                          <option value="">Attach credential… (values never shown)</option>
                          {credentials.map((c) => (
                            <option key={c.id} value={c.id}>{c.name} · {c.provider} · {c.status}</option>
                          ))}
                        </select>
                        <Link href="/settings" className="self-center text-sm text-primary hover:underline">
                          Manage
                        </Link>
                      </div>
                    </PermissionGate>
                    <h3 className="mt-4 font-semibold">Granted capabilities</h3>
                    <ul className="mt-1 space-y-1 text-sm">
                      {connection.granted_capabilities.map((c) => (
                        <li key={c} className="font-mono text-xs">{c}</li>
                      ))}
                      {connection.granted_capabilities.length === 0 && <li className="text-muted-foreground">None granted.</li>}
                    </ul>
                    <h3 className="mt-4 font-semibold">Health</h3>
                    <pre className="mt-1 max-h-40 overflow-auto rounded bg-secondary p-2 text-xs">
                      {JSON.stringify(connection.health ?? {}, null, 2)}
                    </pre>
                  </section>
                  <section className="rounded-lg border p-4">
                    <h2 className="font-semibold">Inbound webhooks</h2>
                    <p className="text-sm text-muted-foreground">HMAC-signed endpoints. Secrets are shown once and stored as hashes.</p>
                    <PermissionGate permission="webhook:create">
                      <div className="mt-2 flex gap-2">
                        <Input value={endpoint} onChange={(e) => setEndpoint(e.target.value)} placeholder="github-prs" aria-label="Endpoint path" className="font-mono text-xs" />
                        <Button onClick={createWebhook}>Add</Button>
                      </div>
                    </PermissionGate>
                    {hookSecret && (
                      <pre className="mt-2 overflow-auto rounded border border-amber-500/30 bg-amber-500/5 p-2 text-xs">{hookSecret}</pre>
                    )}
                    <div className="mt-3">
                      <DataTable columns={hookColumns} rows={webhooks} keyOf={(r) => r.id} emptyTitle="No webhooks" />
                    </div>
                    <p className="mt-3 text-sm">
                      <Link href={`/integrations/${connection.connector_id}`} className="text-primary hover:underline">
                        View connector →
                      </Link>
                    </p>
                  </section>
                </div>
              </>
            )}
          </div>
        </PermissionGate>
      </Layout>
    </Protected>
  );
}
