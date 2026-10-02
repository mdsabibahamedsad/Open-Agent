'use client';

import * as React from 'react';
import { useQuery } from '@tanstack/react-query';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { getSdkMeta } from '@/lib/developer';

function Copy({ text, label }: { text: string; label: string }) {
  const [ok, setOk] = React.useState(false);
  return (
    <Button size="sm" variant="outline" aria-label={`Copy ${label}`}
      onClick={async () => { await navigator.clipboard.writeText(text); setOk(true); setTimeout(() => setOk(false), 1500); }}>
      {ok ? 'Copied' : 'Copy'}
    </Button>
  );
}

function Group({ title, desc, cmds }: { title: string; desc: string; cmds: string[] }) {
  return (
    <Card>
      <CardHeader><CardTitle className="text-base">{title}</CardTitle><CardDescription>{desc}</CardDescription></CardHeader>
      <CardContent className="space-y-2">
        {cmds.map((c) => (
          <div key={c} className="flex items-center justify-between gap-2 rounded bg-muted px-3 py-2 text-xs">
            <code className="overflow-auto">{c}</code>
            <Copy text={c} label={c} />
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

export default function CliPage() {
  const sdk = useQuery({ queryKey: ['dev-sdk'], queryFn: getSdkMeta, staleTime: 300_000 });
  const install = sdk.data?.install.cli ?? 'npm install -g @openagent/cli';
  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader title="CLI reference" description="Scaffold, validate and ship extensions from your terminal."
            breadcrumbs={[{ label: 'Developer', href: '/developer' }, { label: 'CLI' }]} />
          <Card>
            <CardHeader><CardTitle className="text-base">Install</CardTitle></CardHeader>
            <CardContent>
              <div className="flex items-center justify-between gap-2 rounded bg-muted px-3 py-2 text-sm">
                <code>{install}</code><Copy text={install} label="CLI install command" />
              </div>
            </CardContent>
          </Card>
          <div className="grid gap-4 md:grid-cols-2">
            <Group title="Auth" desc="Tokens are per-organization. Never commit them." cmds={['oa auth login', 'oa auth whoami', 'oa org switch <org-slug>']} />
            <Group title="Projects" desc="Projects own environments." cmds={['oa projects list', 'oa projects create --slug my-project --name "My Project"', 'oa env set --project <id> --env staging --endpoint https://api.example.com']} />
            <Group title="Extensions" desc="Mirror of the portal lifecycle actions." cmds={['oa ext create --slug my-ext --type tool', 'oa ext validate <id>', 'oa ext test <id> --suite contract', 'oa ext package <id>', 'oa ext publish <id>', 'oa ext sign <id> --pubkey <key>', 'oa ext deploy <id> --version 1.0.0 --env staging']} />
            <Group title="Registry & webhooks" desc="Offline packages and event delivery." cmds={['oa registry list-local', 'oa webhooks list', 'oa webhooks create --url https://example.com/hook --event deployment.completed.v1']} />
          </div>
        </div>
      </Layout>
    </Protected>
  );
}
