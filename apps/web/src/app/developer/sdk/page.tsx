'use client';

import * as React from 'react';
import { useQuery } from '@tanstack/react-query';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { DataTable, Column } from '@/components/ui/table';
import { getSdkMeta, EXTENSION_TYPE_DESCRIPTIONS } from '@/lib/developer';
import { toUserMessage } from '@/lib/api';

function Copy({ text, label }: { text: string; label: string }) {
  const [ok, setOk] = React.useState(false);
  return (
    <Button
      size="sm" variant="outline" aria-label={`Copy ${label}`}
      onClick={async () => { await navigator.clipboard.writeText(text); setOk(true); setTimeout(() => setOk(false), 1500); }}
    >
      {ok ? 'Copied' : 'Copy'}
    </Button>
  );
}

export default function SdkPage() {
  const sdk = useQuery({ queryKey: ['dev-sdk'], queryFn: getSdkMeta, staleTime: 300_000 });
  const permRows = React.useMemo(
    () => Object.entries(sdk.data?.permissions ?? {}).map(([name, e]) => ({ name, ...e })),
    [sdk.data],
  );
  const permCols: Column<{ name: string; description: string; risk: string; requires_approval: boolean }>[] = [
    { key: 'n', header: 'Permission', render: (r) => <span className="oa-code">{r.name}</span> },
    { key: 'd', header: 'Description', render: (r) => <span className="text-muted-foreground">{r.description}</span> },
    { key: 'r', header: 'Risk', render: (r) => <Badge variant={r.risk === 'low' ? 'outline' : r.risk === 'medium' ? 'secondary' : 'destructive'}>{r.risk}</Badge> },
  ];
  const tsInstall = sdk.data?.install.typescript ?? 'npm install @openagent/sdk';
  const pyInstall = sdk.data?.install.python ?? 'pip install openagent';
  const tsExample = `import { OpenAgent } from '@openagent/sdk';\n\nconst client = new OpenAgent({ baseUrl: process.env.OPENAGENT_API, token: process.env.OPENAGENT_TOKEN });\nconst ext = await client.extensions.validate('<extension-id>', { files: {} });\nconsole.log(ext.ok);`;
  const pyExample = `import os\nfrom openagent import OpenAgent\n\nclient = OpenAgent(base_url=os.environ['OPENAGENT_API'], token=os.environ['OPENAGENT_TOKEN'])\nreport = client.extensions.validate('<extension-id>', files={})\nprint(report['ok'])`;

  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader title="SDK reference" description="Install, call the API, and declare manifests. Live version data from the public /developer/sdk endpoint."
            breadcrumbs={[{ label: 'Developer', href: '/developer' }, { label: 'SDK' }]} />
          {sdk.isLoading && <p className="text-sm text-muted-foreground">Loading SDK metadata…</p>}
          {sdk.error && <p className="text-sm text-destructive" role="alert">{toUserMessage(sdk.error)}</p>}
          {sdk.data && (
            <>
              <div className="flex flex-wrap gap-2">
                <Badge variant="outline">TS SDK {sdk.data.sdk.typescript}</Badge>
                <Badge variant="outline">Py SDK {sdk.data.sdk.python}</Badge>
                <Badge variant="outline">API {sdk.data.api_version}</Badge>
                <Badge variant="outline">ext-api {sdk.data.extension_api}</Badge>
              </div>
              <div className="grid gap-4 md:grid-cols-2">
                <Card>
                  <CardHeader><CardTitle className="text-base">Install</CardTitle></CardHeader>
                  <CardContent className="space-y-2">
                    {[{ l: 'TypeScript', t: tsInstall }, { l: 'Python', t: pyInstall }].map((c) => (
                      <div key={c.l} className="flex items-center justify-between gap-2 rounded border px-3 py-2 text-sm">
                        <span><strong>{c.l}:</strong> <span className="oa-code">{c.t}</span></span>
                        <Copy text={c.t} label={`${c.l} install command`} />
                      </div>
                    ))}
                  </CardContent>
                </Card>
                <Card>
                  <CardHeader><CardTitle className="text-base">Extension types</CardTitle>
                    <CardDescription>{sdk.data.extension_types.length} canonical types — no parallel plugin systems.</CardDescription></CardHeader>
                  <CardContent>
                    <ul className="grid gap-1 text-sm">
                      {sdk.data.extension_types.map((t) => (
                        <li key={t} className="flex gap-2"><span className="oa-code">{t}</span><span className="text-muted-foreground">{EXTENSION_TYPE_DESCRIPTIONS[t] ?? ''}</span></li>
                      ))}
                    </ul>
                  </CardContent>
                </Card>
              </div>
              <div className="grid gap-4 md:grid-cols-2">
                {[{ l: 'TypeScript example', t: tsExample }, { l: 'Python example', t: pyExample }].map((c) => (
                  <Card key={c.l}>
                    <CardHeader><CardTitle className="text-base">{c.l}</CardTitle></CardHeader>
                    <CardContent>
                      <pre className="overflow-auto rounded bg-muted p-3 text-xs">{c.t}</pre>
                      <div className="mt-2"><Copy text={c.t} label={c.l} /></div>
                    </CardContent>
                  </Card>
                ))}
              </div>
              <section aria-label="Permission catalog">
                <h2 className="mb-2 text-lg font-semibold">Permission catalog</h2>
                <DataTable columns={permCols} rows={permRows} keyOf={(r) => r.name}
                  emptyTitle="No permissions reported" emptyDescription="The backend SDK endpoint returned an empty catalog." />
              </section>
            </>
          )}
        </div>
      </Layout>
    </Protected>
  );
}
