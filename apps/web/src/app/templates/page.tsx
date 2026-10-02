'use client';

import * as React from 'react';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { EmptyState, ErrorState } from '@/components/ui/states';
import { useOrganization } from '@/context/OrganizationContext';
import { useSearchParamsState } from '@/lib/queries';
import { catalogApi, installationsApi, CatalogEntry } from '@/lib/packages';
import { catalogEntryToCard, PackageCard } from '@/features/packages/ui';
import { LayoutGrid, List, Search, Store } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';

const TYPE_FILTERS = ['', 'WORKFORCE', 'AGENT', 'WORKFLOW', 'SKILL', 'AUTOMATION_RECIPE', 'TEMPLATE_PACKAGE'];
const TRUST_FILTERS = ['', 'CORE', 'VERIFIED', 'ORGANIZATION', 'COMMUNITY', 'UNTRUSTED'];

export default function TemplatesPage() {
  const { currentOrgId } = useOrganization();
  const [q, setQ] = React.useState('');
  const debounced = useSearchParamsState(q);
  const [typeFilter, setTypeFilter] = React.useState('');
  const [trustFilter, setTrustFilter] = React.useState('');
  const [officialOnly, setOfficialOnly] = React.useState(false);
  const [view, setView] = React.useState<'grid' | 'list'>('grid');

  const params = React.useMemo(
    () => ({
      ...(debounced ? { q: debounced } : {}),
      ...(typeFilter ? { types: typeFilter } : {}),
      ...(trustFilter ? { trust: trustFilter } : {}),
      ...(officialOnly ? { official_only: true } : {}),
      page_size: 48,
    }),
    [debounced, typeFilter, trustFilter, officialOnly],
  );

  const catalog = useQuery({
    queryKey: ['catalog', currentOrgId, params],
    queryFn: () => catalogApi.search(currentOrgId!, params),
    enabled: Boolean(currentOrgId),
    staleTime: 30_000,
  });

  const installed = useQuery({
    queryKey: ['installed-ids', currentOrgId],
    queryFn: () => installationsApi.list(currentOrgId!, { page_size: 100 }),
    enabled: Boolean(currentOrgId),
    staleTime: 30_000,
  });

  const installedIds = React.useMemo(
    () => new Set((installed.data?.data ?? []).map((i) => i.package_id)),
    [installed.data],
  );

  const items: CatalogEntry[] = catalog.data?.data ?? [];

  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader
            title="Template Center"
            description="Reusable agents, workforces, workflows, skills and presets. Install, configure, run — then fork and share."
            breadcrumbs={[{ label: 'Home', href: '/' }, { label: 'Templates' }]}
          />
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative w-full max-w-sm">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
              <Input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Search agents, workforces, skills…"
                aria-label="Search templates"
                className="pl-9"
              />
            </div>
            <select
              aria-label="Filter by type"
              className="rounded-md border border-input bg-background px-3 py-2 text-sm"
              value={typeFilter}
              onChange={(e) => setTypeFilter(e.target.value)}
            >
              {TYPE_FILTERS.map((t) => (
                <option key={t} value={t}>
                  {t === '' ? 'All types' : t}
                </option>
              ))}
            </select>
            <select
              aria-label="Filter by trust"
              className="rounded-md border border-input bg-background px-3 py-2 text-sm"
              value={trustFilter}
              onChange={(e) => setTrustFilter(e.target.value)}
            >
              {TRUST_FILTERS.map((t) => (
                <option key={t} value={t}>
                  {t === '' ? 'Any trust' : t}
                </option>
              ))}
            </select>
            <label className="flex items-center gap-1.5 text-sm">
              <input type="checkbox" checked={officialOnly} onChange={(e) => setOfficialOnly(e.target.checked)} />
              Official only
            </label>
            <div className="ml-auto flex gap-1">
              <Button variant={view === 'grid' ? 'default' : 'outline'} size="icon" onClick={() => setView('grid')} aria-label="Grid view">
                <LayoutGrid className="h-4 w-4" aria-hidden />
              </Button>
              <Button variant={view === 'list' ? 'default' : 'outline'} size="icon" onClick={() => setView('list')} aria-label="List view">
                <List className="h-4 w-4" aria-hidden />
              </Button>
            </div>
          </div>

          {catalog.isLoading && <p className="text-sm text-muted-foreground">Loading catalog…</p>}
          {catalog.isError && (
            <ErrorState
              title="Catalog unavailable"
              description={catalog.error instanceof Error ? catalog.error.message : 'Could not load the catalog.'}
              onRetry={() => catalog.refetch()}
            />
          )}
          {!catalog.isLoading && !catalog.isError && items.length === 0 && (
            <Card>
              <CardContent>
                <EmptyState
                  icon={Store}
                  title="No templates found"
                  description="Try a different search, or publish your own reusable package to seed this catalog."
                />
              </CardContent>
            </Card>
          )}
          {items.length > 0 && (
            <div className={view === 'grid' ? 'grid gap-4 md:grid-cols-2 xl:grid-cols-3' : 'flex flex-col gap-3'}>
              {items.map((pkg) => (
                <PackageCard key={pkg.package_id} pkg={catalogEntryToCard(pkg)} installed={installedIds.has(pkg.package_id)} href={`/templates/${pkg.slug}`} />
              ))}
            </div>
          )}
        </div>
      </Layout>
    </Protected>
  );
}
