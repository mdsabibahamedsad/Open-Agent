'use client';

import * as React from 'react';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { DataTable, Column } from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { useOrganization } from '@/context/OrganizationContext';
import {
  DEVELOPER_ENDPOINTS, EndpointDef, buildTsSnippet, buildPythonSnippet,
  resolvePath, redactHeaders,
} from '@/lib/developer';
import { api } from '@/lib/api';

export default function ApiExplorerPage() {
  const { currentOrgId } = useOrganization();
  const [filter, setFilter] = React.useState('');
  const [selected, setSelected] = React.useState<EndpointDef>(DEVELOPER_ENDPOINTS[0]);
  const [body, setBody] = React.useState(DEVELOPER_ENDPOINTS[0].body ?? '');
  const [sending, setSending] = React.useState(false);
  const [status, setStatus] = React.useState<string | null>(null);
  const [response, setResponse] = React.useState<string | null>(null);
  const [respError, setRespError] = React.useState<string | null>(null);
  const [lang, setLang] = React.useState<'ts' | 'py'>('ts');

  React.useEffect(() => { setBody(selected.body ?? ''); }, [selected]);

  const rows = DEVELOPER_ENDPOINTS.filter(
    (e) => !filter || `${e.method} ${e.path} ${e.description}`.toLowerCase().includes(filter.toLowerCase()),
  );
  const cols: Column<EndpointDef>[] = [
    { key: 'm', header: 'Method', render: (r) => <Badge variant={r.method === 'GET' ? 'outline' : r.method === 'DELETE' ? 'destructive' : 'default'}>{r.method}</Badge> },
    { key: 'p', header: 'Path', render: (r) => <button onClick={() => setSelected(r)} className="oa-code text-left text-primary underline">{r.path}</button> },
    { key: 'd', header: 'Description', render: (r) => <span className="text-muted-foreground">{r.description}</span> },
  ];
  const resolved = resolvePath(selected.path, currentOrgId ?? '');
  const snippet = lang === 'ts' ? buildTsSnippet(selected, currentOrgId ?? '') : buildPythonSnippet(selected, currentOrgId ?? '');

  async function send() {
    setSending(true);
    setStatus(null);
    setResponse(null);
    setRespError(null);
    try {
      let parsed: unknown = undefined;
      if (body.trim()) {
        try { parsed = JSON.parse(body); } catch { setRespError('Body is not valid JSON.'); setSending(false); return; }
      }
      const method = selected.method.toLowerCase() as 'get' | 'post' | 'put' | 'delete';
      const t0 = Date.now();
      const out = await (method === 'get' || method === 'delete'
        ? api[method]<unknown>(resolved)
        : api[method]<unknown>(resolved, parsed));
      const redacted = redactHeaders({ Authorization: 'Bearer ***', 'X-Organization-ID': currentOrgId ?? '' });
      setStatus(`200 OK · ${Date.now() - t0}ms · headers ${JSON.stringify(redacted)}`);
      setResponse(JSON.stringify(out, null, 2));
    } catch (err) {
      setRespError(err instanceof Error ? err.message : 'Request failed');
    } finally {
      setSending(false);
    }
  }

  async function copy(text: string) {
    await navigator.clipboard.writeText(text);
  }

  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader title="API explorer" description="Browse developer + extension endpoints, try them with your org context, and copy SDK snippets."
            breadcrumbs={[{ label: 'Developer', href: '/developer' }, { label: 'API Explorer' }]} />
          <Input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter endpoints…" aria-label="Filter endpoints" className="max-w-sm" />
          <div className="grid gap-4 xl:grid-cols-2">
            <DataTable columns={cols} rows={rows} keyOf={(r) => `${r.method}${r.path}`}
              emptyTitle="No endpoints match" emptyDescription="Clear the filter to see the full catalog." />
            <div className="space-y-4">
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">{selected.method} {selected.path}</CardTitle>
                  <CardDescription>{selected.description} · resolves to <span className="oa-code">{resolved}</span></CardDescription>
                </CardHeader>
                <CardContent className="space-y-3">
                  {(selected.method === 'POST' || selected.method === 'PUT') && (
                    <label className="grid gap-1 text-sm font-medium">JSON body
                      <textarea value={body} onChange={(e) => setBody(e.target.value)} rows={6} aria-label="Request JSON body"
                        className="rounded-md border border-input bg-background p-3 font-mono text-xs" />
                    </label>
                  )}
                  <div className="flex gap-2">
                    <Button onClick={send} loading={sending} disabled={!currentOrgId}>
                      Send request
                    </Button>
                    {!currentOrgId && <span className="text-sm text-muted-foreground">Select an organization first.</span>}
                  </div>
                  {status && <p className="text-xs text-muted-foreground">{status} (sensitive headers redacted)</p>}
                  {respError && <p className="text-sm text-destructive" role="alert">{respError}</p>}
                  {response && <pre className="max-h-96 overflow-auto rounded bg-muted p-3 text-xs" aria-label="Response body">{response}</pre>}
                </CardContent>
              </Card>
              <Card>
                <CardHeader><CardTitle className="text-base">SDK snippet</CardTitle></CardHeader>
                <CardContent>
                  <div className="mb-2 flex gap-2" role="group" aria-label="Snippet language">
                    <Button size="sm" variant={lang === 'ts' ? 'default' : 'outline'} onClick={() => setLang('ts')}>TypeScript</Button>
                    <Button size="sm" variant={lang === 'py' ? 'default' : 'outline'} onClick={() => setLang('py')}>Python</Button>
                    <Button size="sm" variant="ghost" onClick={() => copy(snippet)}>Copy snippet</Button>
                  </div>
                  <pre className="max-h-72 overflow-auto rounded bg-muted p-3 text-xs">{snippet}</pre>
                </CardContent>
              </Card>
            </div>
          </div>
        </div>
      </Layout>
    </Protected>
  );
}
