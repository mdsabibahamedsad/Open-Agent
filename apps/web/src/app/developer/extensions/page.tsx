'use client';

import * as React from 'react';
import Link from 'next/link';
import { useQuery } from '@tanstack/react-query';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { DataTable, Column } from '@/components/ui/table';
import { StatusBadge } from '@/components/ui/status';
import { Select, SelectTrigger, SelectContent, SelectItem } from '@/components/ui/select';
import { useOrganization } from '@/context/OrganizationContext';
import { getSdkMeta, listExtensions, DevExtension } from '@/lib/developer';
import { toUserMessage } from '@/lib/api';

export default function DeveloperExtensionsPage() {
  const { currentOrgId } = useOrganization();
  const [q, setQ] = React.useState('');
  const [type, setType] = React.useState('all');
  const [lifecycle, setLifecycle] = React.useState('all');

  const sdk = useQuery({ queryKey: ['dev-sdk'], queryFn: getSdkMeta, staleTime: 300_000 });
  const query = useQuery({
    queryKey: ['dev-extensions', currentOrgId, type, lifecycle],
    queryFn: () => listExtensions(currentOrgId ?? '', {
      extension_type: type === 'all' ? undefined : type,
      lifecycle: lifecycle === 'all' ? undefined : lifecycle,
    }),
    enabled: !!currentOrgId,
    staleTime: 30_000,
  });
  const items = (query.data ?? []).filter(
    (e) => !q || e.slug.toLowerCase().includes(q.toLowerCase()),
  );
  const types: string[] = sdk.data?.extension_types ?? [];
  const columns: Column<DevExtension>[] = [
    {
      key: 'slug', header: 'Extension', sortable: true, accessor: (r) => r.slug,
      render: (r) => <Link href={`/developer/extensions/${r.id}`} className="font-medium text-primary underline">{r.slug}</Link>,
    },
    { key: 'type', header: 'Type', render: (r) => <span className="text-muted-foreground">{r.type}</span> },
    { key: 'lifecycle', header: 'Lifecycle', render: (r) => <StatusBadge status={r.lifecycle} /> },
    { key: 'trust', header: 'Trust', render: (r) => <span className="text-sm">{r.trust ?? '—'}</span> },
  ];

  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader
            title="Extensions"
            description="One canonical extension registry — tools, agents, connectors, MCP, skills and more."
            breadcrumbs={[{ label: 'Developer', href: '/developer' }, { label: 'Extensions' }]}
            actions={<Link href="/developer/extensions/new"><Button>New extension</Button></Link>}
          />
          <div className="flex flex-wrap gap-2">
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter by slug…" aria-label="Filter extensions" className="max-w-xs" />
            <Select value={type} onValueChange={setType} placeholder="All types">
              <SelectTrigger className="w-48" />
              <SelectContent>
                <SelectItem value="all">All types</SelectItem>
                {types.map((t) => <SelectItem key={t} value={t}>{t}</SelectItem>)}
              </SelectContent>
            </Select>
            <Select value={lifecycle} onValueChange={setLifecycle} placeholder="All lifecycles">
              <SelectTrigger className="w-48" />
              <SelectContent>
                <SelectItem value="all">All lifecycles</SelectItem>
                {['DRAFT', 'VALIDATED', 'PACKAGED', 'SIGNED', 'PUBLISHED', 'DISABLED', 'QUARANTINED'].map((l) => (
                  <SelectItem key={l} value={l}>{l}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <DataTable
            columns={columns} rows={items} keyOf={(r) => r.id}
            loading={query.isLoading}
            error={query.error ? toUserMessage(query.error) : null}
            onRetry={() => query.refetch()}
            emptyTitle="No extensions yet"
            emptyDescription="Scaffold your first extension — least-privilege permissions by default."
            emptyAction={<Link href="/developer/extensions/new"><Button>Build an extension</Button></Link>}
          />
        </div>
      </Layout>
    </Protected>
  );
}
