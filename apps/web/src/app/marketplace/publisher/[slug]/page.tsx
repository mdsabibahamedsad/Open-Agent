'use client';

import * as React from 'react';
import { useParams } from 'next/navigation';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { EmptyState, ErrorState } from '@/components/ui/states';
import { toUserMessage } from '@/lib/api';
import { publishersApi } from '@/lib/marketplace';
import type { ListingCard } from '@/lib/marketplace';
import { ListingCardView, VerificationBadge } from '@/features/marketplace/ui';
import { useQuery } from '@tanstack/react-query';

export default function PublisherPage() {
  const params = useParams<{ slug: string }>();
  const slug = params.slug;
  const [followMsg, setFollowMsg] = React.useState<string | null>(null);
  const [followPending, setFollowPending] = React.useState(false);

  const query = useQuery({
    queryKey: ['publisher', slug],
    queryFn: () => publishersApi.get(slug),
    staleTime: 30_000,
  });
  const full = query.data;
  const listings: ListingCard[] = full?.listings ?? [];

  const toggleFollow = async () => {
    if (!full) return;
    setFollowPending(true);
    setFollowMsg(null);
    try {
      if (full.following) {
        await publishersApi.unfollow(slug);
      } else {
        await publishersApi.follow(slug);
      }
      void query.refetch();
    } catch (e: unknown) {
      setFollowMsg(toUserMessage(e));
    } finally {
      setFollowPending(false);
    }
  };

  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          {query.isLoading && <p className="text-sm text-muted-foreground">Loading publisher…</p>}
          {query.isError && (
            <ErrorState
              title="Publisher unavailable"
              description={query.error instanceof Error ? query.error.message : 'Could not load this publisher.'}
              onRetry={() => query.refetch()}
            />
          )}
          {full && (
            <>
              <PageHeader
                title={full.display_name}
                description={full.description || 'No description.'}
                breadcrumbs={[
                  { label: 'Home', href: '/' },
                  { label: 'Marketplace', href: '/marketplace' },
                  { label: full.display_name },
                ]}
              />
              <div className="flex flex-wrap items-center gap-2">
                <VerificationBadge status={full.verification_status} />
                <Badge variant="outline">{full.publisher_type}</Badge>
                {full.website && (
                  <a href={full.website} target="_blank" rel="noopener noreferrer nofollow" className="text-sm text-primary underline">
                    {full.website.replace(/^https?:\/\//, '')}
                  </a>
                )}
                <span className="ml-auto flex items-center gap-2">
                  <Button variant="outline" size="sm" onClick={toggleFollow} disabled={followPending}>
                    {full.following ? 'Unfollow' : 'Follow'}
                  </Button>
                  {followMsg && <span className="text-xs text-muted-foreground">{followMsg}</span>}
                </span>
              </div>
              <div className="grid gap-4 md:grid-cols-4">
                <Card><CardContent className="py-4"><p className="text-2xl font-bold">{full.published_listings}</p><p className="text-sm text-muted-foreground">Published packages</p></CardContent></Card>
                <Card><CardContent className="py-4"><p className="text-2xl font-bold">{full.follower_count}</p><p className="text-sm text-muted-foreground">Followers</p></CardContent></Card>
                <Card><CardContent className="py-4"><p className="text-2xl font-bold">{(full.average_rating ?? 0).toFixed(1)}</p><p className="text-sm text-muted-foreground">Average rating</p></CardContent></Card>
                <Card><CardContent className="py-4"><p className="text-2xl font-bold">{full.trust_status}</p><p className="text-sm text-muted-foreground">Trust status</p></CardContent></Card>
              </div>
              <section aria-label="Publisher packages">
                <h2 className="mb-2 text-lg font-semibold">Packages</h2>
                {listings.length === 0 ? (
                  <Card>
                    <CardContent>
                      <EmptyState title="No published packages" description="This publisher has nothing published yet." />
                    </CardContent>
                  </Card>
                ) : (
                  <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                    {listings.map((pkg) => (
                      <ListingCardView key={pkg.id} listing={pkg} />
                    ))}
                  </div>
                )}
              </section>
              <Card>
                <CardHeader><CardTitle className="text-base">Security status</CardTitle></CardHeader>
                <CardContent className="text-sm text-muted-foreground">
                  Verification never bypasses runtime security: every package from this
                  publisher is still validated, scanned and policy-checked before it can
                  be installed.
                </CardContent>
              </Card>
            </>
          )}
        </div>
      </Layout>
    </Protected>
  );
}
