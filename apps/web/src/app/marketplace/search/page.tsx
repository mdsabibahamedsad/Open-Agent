'use client';

import * as React from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { EmptyState, ErrorState } from '@/components/ui/states';
import { useSearchParamsState } from '@/lib/queries';
import { marketplaceApi, ListingCard } from '@/lib/marketplace';
import { ListingCardView } from '@/features/marketplace/ui';
import { Search } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';

const SORTS = [
  'RELEVANCE',
  'NEWEST',
  'UPDATED',
  'MOST_INSTALLED',
  'MOST_USED',
  'MOST_FAVORITED',
  'HIGHEST_RATED',
  'PRICE_LOW_TO_HIGH',
  'PRICE_HIGH_TO_LOW',
];

const TRUSTS = ['', 'CORE', 'VERIFIED', 'ORGANIZATION', 'COMMUNITY', 'UNTRUSTED'];
const PRICING = ['', 'FREE', 'ONE_TIME', 'SUBSCRIPTION', 'USAGE_BASED', 'TIERED', 'ENTERPRISE', 'CUSTOM'];

function readParams(sp: URLSearchParams) {
  return {
    q: sp.get('q') ?? '',
    category: sp.get('category') ?? '',
    trust: sp.get('trust') ?? '',
    pricing: sp.get('pricing') ?? '',
    min_rating: sp.get('min_rating') ?? '',
    sort: sp.get('sort') ?? 'RELEVANCE',
    page: Number(sp.get('page') ?? 1) || 1,
  };
}

export default function MarketplaceSearchPage() {
  return (
    <React.Suspense fallback={<p className="text-sm text-muted-foreground">Loading search…</p>}>
      <SearchBody />
    </React.Suspense>
  );
}

function SearchBody() {
  const router = useRouter();
  const sp = useSearchParams();
  const params = readParams(sp);
  const [q, setQ] = React.useState(params.q);
  const debounced = useSearchParamsState(q);
  const [trust, setTrust] = React.useState(params.trust);
  const [pricing, setPricing] = React.useState(params.pricing);
  const [minRating, setMinRating] = React.useState(params.min_rating);
  const [sort, setSort] = React.useState(params.sort);

  React.useEffect(() => {
    const next = new URLSearchParams();
    if (debounced) next.set('q', debounced);
    if (params.category) next.set('category', params.category);
    if (trust) next.set('trust', trust);
    if (pricing) next.set('pricing', pricing);
    if (minRating) next.set('min_rating', minRating);
    if (sort !== 'RELEVANCE') next.set('sort', sort);
    if (params.page > 1) next.set('page', String(params.page));
    const target = `/marketplace/search${next.toString() ? `?${next}` : ''}`;
    if (target !== `/marketplace/search${sp.toString() ? `?${sp}` : ''}`) {
      router.replace(target);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debounced, trust, pricing, minRating, sort]);

  const query = useQuery({
    queryKey: ['marketplace-search-page', debounced, params.category, trust, pricing, minRating, sort, params.page],
    queryFn: () =>
      marketplaceApi.search({
        q: debounced,
        category: params.category,
        trust,
        pricing,
        min_rating: minRating,
        sort,
        page: params.page,
        page_size: 24,
      }),
    staleTime: 30_000,
  });
  const items: ListingCard[] = query.data?.data ?? [];
  const total = query.data?.meta.total_items ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / 24));

  const gotoPage = (page: number) => {
    const next = new URLSearchParams(sp.toString());
    next.set('page', String(page));
    router.push(`/marketplace/search?${next}`);
  };

  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader
            title="Search marketplace"
            description={total ? `${total} listing${total === 1 ? '' : 's'} found.` : 'Search across all published listings.'}
            breadcrumbs={[
              { label: 'Home', href: '/' },
              { label: 'Marketplace', href: '/marketplace' },
              { label: 'Search' },
            ]}
          />
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative w-full max-w-sm">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
              <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Keywords, tags, publishers…" aria-label="Search text" className="pl-9" />
            </div>
            <select aria-label="Trust filter" className="rounded-md border border-input bg-background px-3 py-2 text-sm" value={trust} onChange={(e) => setTrust(e.target.value)}>
              {TRUSTS.map((t) => (
                <option key={t} value={t}>{t === '' ? 'Any trust' : t}</option>
              ))}
            </select>
            <select aria-label="Pricing filter" className="rounded-md border border-input bg-background px-3 py-2 text-sm" value={pricing} onChange={(e) => setPricing(e.target.value)}>
              {PRICING.map((t) => (
                <option key={t} value={t}>{t === '' ? 'Any price' : t}</option>
              ))}
            </select>
            <select aria-label="Minimum rating" className="rounded-md border border-input bg-background px-3 py-2 text-sm" value={minRating} onChange={(e) => setMinRating(e.target.value)}>
              {['', '3', '4', '4.5'].map((t) => (
                <option key={t} value={t}>{t === '' ? 'Any rating' : `${t}+ stars`}</option>
              ))}
            </select>
            <select aria-label="Sort order" className="rounded-md border border-input bg-background px-3 py-2 text-sm" value={sort} onChange={(e) => setSort(e.target.value)}>
              {SORTS.map((t) => (
                <option key={t} value={t}>{t.replaceAll('_', ' ').toLowerCase()}</option>
              ))}
            </select>
          </div>

          {query.isLoading && <p className="text-sm text-muted-foreground">Searching…</p>}
          {query.isError && (
            <ErrorState
              title="Search unavailable"
              description={query.error instanceof Error ? query.error.message : 'Could not search.'}
              onRetry={() => query.refetch()}
            />
          )}
          {!query.isLoading && !query.isError && items.length === 0 && (
            <Card>
              <CardContent>
                <EmptyState icon={Search} title="No listings match" description="Try different keywords or loosen the filters." />
              </CardContent>
            </Card>
          )}
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {items.map((pkg) => (
              <ListingCardView key={pkg.id} listing={pkg} />
            ))}
          </div>
          {totalPages > 1 && (
            <nav className="flex items-center gap-2" aria-label="Pagination">
              <Button variant="outline" size="sm" disabled={params.page <= 1} onClick={() => gotoPage(params.page - 1)}>
                Previous
              </Button>
              <span className="text-sm text-muted-foreground" aria-live="polite">
                Page {params.page} of {totalPages}
              </span>
              <Button variant="outline" size="sm" disabled={params.page >= totalPages} onClick={() => gotoPage(params.page + 1)}>
                Next
              </Button>
            </nav>
          )}
        </div>
      </Layout>
    </Protected>
  );
}
