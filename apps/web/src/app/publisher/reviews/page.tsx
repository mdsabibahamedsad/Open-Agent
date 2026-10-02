'use client';

import * as React from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { EmptyState, ErrorState } from '@/components/ui/states';
import { StatusBadge } from '@/components/ui/status';
import { useOrganization } from '@/context/OrganizationContext';
import { toUserMessage } from '@/lib/api';
import { studioApi, reviewsApi, ReviewItem } from '@/lib/marketplace';
import { RatingStars } from '@/features/marketplace/ui';
import { StudioShell } from '../shell';
import { useQuery } from '@tanstack/react-query';

export default function StudioReviewsPage() {
  const { currentOrgId } = useOrganization();
  const [page, setPage] = React.useState(1);
  const [msg, setMsg] = React.useState<string | null>(null);
  const [responding, setResponding] = React.useState<string | null>(null);
  const [responseBody, setResponseBody] = React.useState('');

  const query = useQuery({
    queryKey: ['studio-reviews', currentOrgId, page],
    queryFn: () => studioApi.reviews(currentOrgId!, { page, page_size: 20 }),
    enabled: Boolean(currentOrgId),
    staleTime: 15_000,
  });
  const reviews: ReviewItem[] = query.data?.data ?? [];
  const total = query.data?.meta.total_items ?? 0;

  const respond = async (id: string) => {
    setMsg(null);
    try {
      await reviewsApi.respond(id, responseBody);
      setResponseBody('');
      setResponding(null);
      setMsg('Response published.');
      void query.refetch();
    } catch (e: unknown) {
      setMsg(toUserMessage(e));
    }
  };

  return (
    <StudioShell title="Reviews" description="Reviews received across your listings. Respond as publisher; moderation stays with moderators.">
      {msg && <p role="status" className="text-sm text-muted-foreground">{msg}</p>}
      {query.isLoading && <p className="text-sm text-muted-foreground">Loading reviews…</p>}
      {query.isError && (
        <ErrorState title="Reviews unavailable" description={query.error instanceof Error ? query.error.message : 'Could not load.'} onRetry={() => query.refetch()} />
      )}
      {!query.isLoading && !query.isError && reviews.length === 0 && (
        <Card><CardContent><EmptyState title="No reviews yet" description="Reviews for your listings will appear here." /></CardContent></Card>
      )}
      <div className="space-y-3">
        {reviews.map((r) => (
          <Card key={r.id}>
            <CardContent className="space-y-2 py-4 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <RatingStars average={r.rating} count={1} />
                {r.verified_use && <Badge variant="success">Verified use</Badge>}
                {r.status !== 'PUBLISHED' && <StatusBadge status={r.status} />}
                <span className="ml-auto text-xs text-muted-foreground">{new Date(r.created_at).toLocaleString()}</span>
              </div>
              {r.title && <p className="font-medium">{r.title}</p>}
              <p className="whitespace-pre-wrap text-muted-foreground">{r.body}</p>
              {r.response && (
                <div className="rounded-md bg-muted p-2">
                  <p className="text-xs font-medium">Your response</p>
                  <p className="whitespace-pre-wrap text-muted-foreground">{r.response.body}</p>
                </div>
              )}
              {!r.response && (
                responding === r.id ? (
                  <div className="space-y-2">
                    <textarea className="min-h-16 w-full rounded-md border border-input bg-background px-3 py-2 text-sm" placeholder="Publisher response…" aria-label="Publisher response" value={responseBody} onChange={(e) => setResponseBody(e.target.value)} />
                    <Button size="sm" onClick={() => respond(r.id)} disabled={!responseBody.trim()}>Publish response</Button>
                  </div>
                ) : (
                  <Button variant="ghost" size="sm" onClick={() => setResponding(r.id)}>Respond</Button>
                )
              )}
            </CardContent>
          </Card>
        ))}
      </div>
      <div className="flex items-center gap-2 text-sm">
        <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>Previous</Button>
        <span className="text-muted-foreground">Page {page} · {total} review(s)</span>
        <Button variant="outline" size="sm" disabled={page * 20 >= total} onClick={() => setPage((p) => p + 1)}>Next</Button>
      </div>
    </StudioShell>
  );
}
