'use client';

import Link from 'next/link';
import { useQuery } from '@tanstack/react-query';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { StatusBadge } from '@/components/ui/status';
import { useOrganization } from '@/context/OrganizationContext';
import { listExtensions } from '@/lib/developer';
import { toUserMessage } from '@/lib/api';

const FLOW = [
  { key: 'VALIDATED', label: '1. Validate — manifest + sources, no execution' },
  { key: 'PACKAGED', label: '2. Package — deterministic .oaext build' },
  { key: 'SIGNED', label: '3. Sign — offline Ed25519 over the digest' },
  { key: 'PUBLISHED', label: '4. Publish — secret scan gate must pass' },
];

export default function DeveloperMarketplacePage() {
  const { currentOrgId } = useOrganization();
  const extensions = useQuery({
    queryKey: ['dev-extensions', currentOrgId],
    queryFn: () => listExtensions(currentOrgId ?? ''),
    enabled: !!currentOrgId,
  });
  const byLifecycle = new Map<string, number>();
  for (const e of extensions.data ?? []) byLifecycle.set(e.lifecycle, (byLifecycle.get(e.lifecycle) ?? 0) + 1);

  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader title="Marketplace publishing" description="How developers ship to the Marketplace. Flow status below is live extension data."
            breadcrumbs={[{ label: 'Developer', href: '/developer' }, { label: 'Marketplace' }]}
            actions={<Link href="/marketplace"><Button>Open Marketplace</Button></Link>} />
          <Card>
            <CardHeader><CardTitle className="text-base">Publishing checklist</CardTitle>
              <CardDescription>Counts are live per-lifecycle totals for this organization.</CardDescription></CardHeader>
            <CardContent>
              {extensions.error && <p className="text-sm text-destructive" role="alert">{toUserMessage(extensions.error)}</p>}
              <ul className="space-y-2">
                {FLOW.map((f) => (
                  <li key={f.key} className="flex items-center justify-between gap-2 rounded border px-3 py-2 text-sm">
                    <span>{f.label}</span>
                    <span className="flex items-center gap-2">
                      <StatusBadge status={f.key} />
                      <span className="text-muted-foreground" aria-label={`${byLifecycle.get(f.key) ?? 0} extensions ${f.key}`}>
                        {extensions.isLoading ? '…' : `${byLifecycle.get(f.key) ?? 0}`}
                      </span>
                    </span>
                  </li>
                ))}
              </ul>
              <div className="mt-4 flex flex-wrap gap-2">
                <Link href="/developer/extensions"><Button variant="outline" size="sm">Review extensions</Button></Link>
                <Link href="/developer/docs"><Button variant="outline" size="sm">Security notes</Button></Link>
              </div>
            </CardContent>
          </Card>
        </div>
      </Layout>
    </Protected>
  );
}
