'use client';

import * as React from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { Card, CardContent } from '@/components/ui/card';
import { EmptyState, ErrorState } from '@/components/ui/states';
import { marketplaceApi, ListingCard } from '@/lib/marketplace';
import { ListingCardView } from '@/features/marketplace/ui';
import { useQuery } from '@tanstack/react-query';

export default function MarketplaceCategoryPage() {
  const params = useParams<{ slug: string }>();
  const slug = params.slug;

  const query = useQuery({
    queryKey: ['marketplace-category', slug],
    queryFn: () => marketplaceApi.search({ category: slug, page_size: 48 }),
    staleTime: 30_000,
  });
  const items: ListingCard[] = query.data?.data ?? [];

  const name = slug.replaceAll('-', ' ').replace(/\b\w/g, (c) => c.toUpperCase());

  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader
            title={name}
            description={query.data ? `${query.data.meta.total_items} listing(s) in this category.` : 'Category-specific discovery.'}
            breadcrumbs={[
              { label: 'Home', href: '/' },
              { label: 'Marketplace', href: '/marketplace' },
              { label: name },
            ]}
          />
          {query.isLoading && <p className="text-sm text-muted-foreground">Loading category…</p>}
          {query.isError && (
            <ErrorState
              title="Category unavailable"
              description={query.error instanceof Error ? query.error.message : 'Could not load this category.'}
              onRetry={() => query.refetch()}
            />
          )}
          {!query.isLoading && !query.isError && items.length === 0 && (
            <Card>
              <CardContent>
                <EmptyState
                  title="No listings in this category"
                  description="Try another category or the full search."
                  action={<Link href="/marketplace/search" className="text-sm text-primary underline">Search all listings</Link>}
                />
              </CardContent>
            </Card>
          )}
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {items.map((pkg) => (
              <ListingCardView key={pkg.id} listing={pkg} />
            ))}
          </div>
        </div>
      </Layout>
    </Protected>
  );
}
