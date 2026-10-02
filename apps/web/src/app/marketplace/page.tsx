'use client';

import * as React from 'react';
import Link from 'next/link';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { EmptyState, ErrorState } from '@/components/ui/states';
import { useSearchParamsState } from '@/lib/queries';
import { marketplaceApi, CategoryNode, ListingCard } from '@/lib/marketplace';
import { ListingCardView } from '@/features/marketplace/ui';
import { Search, Store } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';

// MP23: real discovery over marketplace listings (ratings, installs,
// publishers all live backend data). Paid/commerce rows render from real
// product data; nothing here is hard-coded.
export default function MarketplacePage() {
  const [q, setQ] = React.useState('');
  const debounced = useSearchParamsState(q);

  const sectionsQuery = useQuery({
    queryKey: ['marketplace-featured'],
    queryFn: () => marketplaceApi.featured(),
    staleTime: 60_000,
  });

  const categoriesQuery = useQuery({
    queryKey: ['marketplace-categories'],
    queryFn: () => marketplaceApi.categories(),
    staleTime: 300_000,
  });

  const searchQuery = useQuery({
    queryKey: ['marketplace-search', debounced],
    queryFn: () => marketplaceApi.search({ q: debounced, page_size: 12 }),
    enabled: debounced.length > 0,
    staleTime: 30_000,
  });

  const categories: CategoryNode[] = categoriesQuery.data?.data ?? [];
  const sections = sectionsQuery.data?.sections ?? [];
  const results: ListingCard[] = searchQuery.data?.data ?? [];

  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader
            title="Marketplace"
            description="Discover reusable AI workforce packages — agents, workforces, workflows, skills and presets. Every metric below is live."
            breadcrumbs={[{ label: 'Home', href: '/' }, { label: 'Marketplace' }]}
          />
          <form
            role="search"
            onSubmit={(e) => {
              e.preventDefault();
              window.location.href = `/marketplace/search?q=${encodeURIComponent(debounced)}`;
            }}
            className="flex w-full max-w-xl gap-2"
          >
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
              <Input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Search agents, workforces, skills…"
                aria-label="Search marketplace"
                className="pl-9"
              />
            </div>
            <Button type="submit">Search</Button>
          </form>

          {debounced.length > 0 && (
            <section aria-label="Quick results">
              <div className="mb-2 flex items-center justify-between">
                <h2 className="text-lg font-semibold">Top matches</h2>
                <Link href={`/marketplace/search?q=${encodeURIComponent(debounced)}`} className="text-sm text-primary underline">
                  View all results
                </Link>
              </div>
              {searchQuery.isLoading && <p className="text-sm text-muted-foreground">Searching…</p>}
              {!searchQuery.isLoading && results.length === 0 && (
                <p className="text-sm text-muted-foreground">No matches — try the full search page.</p>
              )}
              <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                {results.slice(0, 6).map((pkg) => (
                  <ListingCardView key={pkg.id} listing={pkg} />
                ))}
              </div>
            </section>
          )}

          <section aria-label="Categories">
            <div className="mb-2 flex items-center justify-between">
              <h2 className="text-lg font-semibold">Browse categories</h2>
              <Link href="/marketplace/search" className="text-sm text-primary underline">
                All listings
              </Link>
            </div>
            {categoriesQuery.isLoading && <p className="text-sm text-muted-foreground">Loading categories…</p>}
            <div className="flex flex-wrap gap-2">
              {categories.slice(0, 24).map((c) => (
                <Link key={c.slug} href={`/marketplace/category/${c.slug}`}>
                  <Badge variant="outline" className="cursor-pointer px-3 py-1.5 text-sm hover:border-primary">
                    {c.name}
                    {c.children.length > 0 && (
                      <span className="ml-1 text-muted-foreground">· {c.children.length}</span>
                    )}
                  </Badge>
                </Link>
              ))}
              {categories.length === 0 && !categoriesQuery.isLoading && (
                <p className="text-sm text-muted-foreground">No categories yet.</p>
              )}
            </div>
          </section>

          {sectionsQuery.isError && (
            <ErrorState
              title="Marketplace unavailable"
              description={sectionsQuery.error instanceof Error ? sectionsQuery.error.message : 'Could not load listings.'}
              onRetry={() => sectionsQuery.refetch()}
            />
          )}
          {sections.map((section) => (
            <section key={section.key} aria-label={section.label}>
              <div className="mb-2 flex items-center gap-2">
                <h2 className="text-lg font-semibold">{section.label}</h2>
                {section.editorial && <Badge variant="outline">Curated by OpenAgent</Badge>}
              </div>
              {section.items.length === 0 ? (
                <Card>
                  <CardContent>
                    <EmptyState
                      icon={Store}
                      title={`No ${section.label.toLowerCase()} yet`}
                      description="Publish a reusable package to seed this marketplace."
                    />
                  </CardContent>
                </Card>
              ) : (
                <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                  {section.items.map((pkg) => (
                    <ListingCardView key={pkg.id} listing={pkg} />
                  ))}
                </div>
              )}
            </section>
          ))}

          <Card>
            <CardHeader>
              <CardTitle className="text-base">For publishers</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-wrap gap-2">
              <Link href="/publisher/packages">
                <Button variant="outline">Open Publisher Studio</Button>
              </Link>
              <Link href="/templates">
                <Button variant="ghost">Browse Template Center</Button>
              </Link>
            </CardContent>
          </Card>
        </div>
      </Layout>
    </Protected>
  );
}
