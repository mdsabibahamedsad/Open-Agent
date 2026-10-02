'use client';

import * as React from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { DataTable, Column } from '@/components/ui/table';
import { useOrganization } from '@/context/OrganizationContext';
import {
  listWebhooks, createWebhook, listDevEvents, listUsage,
  DevWebhook, UsageRow,
} from '@/lib/developer';
import { toUserMessage } from '@/lib/api';

export default function DeveloperSettingsPage() {
  const { currentOrgId } = useOrganization();
  const qc = useQueryClient();
  const [url, setUrl] = React.useState('');
  const [events, setEvents] = React.useState('');
  const [saving, setSaving] = React.useState(false);
  const [formError, setFormError] = React.useState<string | null>(null);
  const [secretOnce, setSecretOnce] = React.useState<string | null>(null);
  const [copied, setCopied] = React.useState(false);

  const webhooks = useQuery({
    queryKey: ['dev-webhooks', currentOrgId],
    queryFn: () => listWebhooks(currentOrgId ?? ''),
    enabled: !!currentOrgId,
  });
  const catalog = useQuery({
    queryKey: ['dev-event-catalog', currentOrgId],
    queryFn: () => listDevEvents(currentOrgId ?? ''),
    enabled: !!currentOrgId,
  });
  const usage = useQuery({
    queryKey: ['dev-usage', currentOrgId],
    queryFn: () => listUsage(currentOrgId ?? '', 30),
    enabled: !!currentOrgId,
  });

  const whCols: Column<DevWebhook>[] = [
    { key: 'u', header: 'URL', render: (r) => <span className="text-sm">{r.url}</span> },
    { key: 'e', header: 'Events', render: (r) => <span className="text-xs text-muted-foreground">{r.events.join(', ') || '—'}</span> },
    { key: 's', header: 'Enabled', render: (r) => <span className="text-sm">{r.enabled === false ? 'No' : 'Yes'}</span> },
  ];
  const usageCols: Column<UsageRow>[] = [
    { key: 'x', header: 'Extension', render: (r) => <span>{r.extension}</span> },
    { key: 'd', header: 'Day', render: (r) => <span className="text-muted-foreground">{String(r.day)}</span> },
    { key: 'i', header: 'Installs', render: (r) => <span>{r.installs}</span> },
    { key: 'n', header: 'Invocations', render: (r) => <span>{r.invocations}</span> },
    { key: 'e', header: 'Errors', render: (r) => <span>{r.errors}</span> },
  ];

  async function onCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!currentOrgId) return;
    setSaving(true);
    setFormError(null);
    setSecretOnce(null);
    try {
      const out = await createWebhook(currentOrgId, {
        url: url.trim(),
        events: events.split(',').map((s) => s.trim()).filter(Boolean),
      });
      setSecretOnce(out.signing_secret_once);
      setUrl('');
      setEvents('');
      await qc.invalidateQueries({ queryKey: ['dev-webhooks'] });
    } catch (err) {
      setFormError(toUserMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader title="Webhooks & usage" description="Event delivery with per-webhook signing secrets, plus aggregated usage (no customer PII)."
            breadcrumbs={[{ label: 'Developer', href: '/developer' }, { label: 'Webhooks & usage' }]} />

          <div className="grid gap-4 lg:grid-cols-2">
            <section aria-label="Webhooks" className="space-y-3">
              <h2 className="text-lg font-semibold">Webhooks</h2>
              <DataTable columns={whCols} rows={webhooks.data ?? []} keyOf={(r) => r.id}
                loading={webhooks.isLoading}
                error={webhooks.error ? toUserMessage(webhooks.error) : null}
                onRetry={() => webhooks.refetch()}
                emptyTitle="No webhooks yet" emptyDescription="Register an HTTPS endpoint to receive signed developer events." />
              <form onSubmit={onCreate} className="space-y-3 rounded-lg border p-4" aria-label="Create webhook">
                <h3 className="font-medium">New webhook</h3>
                <Input label="URL (https, or http://localhost for dev)" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://example.com/hook" required />
                <Input label="Events (comma-separated)" value={events} onChange={(e) => setEvents(e.target.value)} placeholder="deployment.completed.v1" helperText="Must match names in the event catalog below." />
                {formError && <p className="text-sm text-destructive" role="alert">{formError}</p>}
                <Button type="submit" loading={saving} disabled={!currentOrgId}>Create webhook</Button>
              </form>
              {secretOnce && (
                <div className="rounded-lg border border-amber-500/50 p-4" role="alert">
                  <p className="text-sm font-medium">Signing secret — shown once</p>
                  <p className="mt-1 text-xs text-muted-foreground">Copy it now. It will never be shown again and is not logged elsewhere.</p>
                  <div className="mt-2 flex items-center gap-2">
                    <code className="flex-1 overflow-auto rounded bg-muted p-2 text-xs">{secretOnce}</code>
                    <Button size="sm" variant="outline" onClick={async () => { await navigator.clipboard.writeText(secretOnce); setCopied(true); setTimeout(() => setCopied(false), 1500); }}>
                      {copied ? 'Copied' : 'Copy'}
                    </Button>
                  </div>
                </div>
              )}
            </section>

            <section aria-label="Event catalog" className="space-y-3">
              <h2 className="text-lg font-semibold">Event catalog</h2>
              {catalog.isLoading && <p className="text-sm text-muted-foreground">Loading events…</p>}
              {catalog.error && <p className="text-sm text-destructive" role="alert">{toUserMessage(catalog.error)}</p>}
              <Card>
                <CardContent className="pt-6">
                  <ul className="grid gap-1 text-sm">
                    {(catalog.data ?? []).map((ev) => (
                      <li key={ev.name} className="flex items-center justify-between gap-2">
                        <span className="oa-code">{ev.name}</span>
                        <span className="text-xs text-muted-foreground">v{ev.version}</span>
                      </li>
                    ))}
                    {(catalog.data ?? []).length === 0 && !catalog.isLoading && (
                      <li className="text-sm text-muted-foreground">No events reported.</li>
                    )}
                  </ul>
                </CardContent>
              </Card>
            </section>
          </div>

          <section aria-label="Usage">
            <h2 className="mb-2 text-lg font-semibold">Usage (aggregated, last 30 days)</h2>
            <Card>
              <CardHeader>
                <CardTitle className="text-sm">Aggregated analytics</CardTitle>
                <CardDescription>Counts only — installs, invocations, errors, latency. No customer PII is exposed.</CardDescription>
              </CardHeader>
              <CardContent>
                <DataTable columns={usageCols} rows={usage.data ?? []} keyOf={(r, i) => `${r.extension}-${r.day}-${i}`}
                  loading={usage.isLoading}
                  error={usage.error ? toUserMessage(usage.error) : null}
                  onRetry={() => usage.refetch()}
                  emptyTitle="No usage yet" emptyDescription="Install and invoke an extension to populate aggregated analytics." />
              </CardContent>
            </Card>
          </section>
        </div>
      </Layout>
    </Protected>
  );
}
