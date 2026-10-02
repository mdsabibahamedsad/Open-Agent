'use client';

import * as React from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { EmptyState, ErrorState } from '@/components/ui/states';
import { StatusBadge } from '@/components/ui/status';
import { Dialog } from '@/components/ui/dialog';
import { useOrganization } from '@/context/OrganizationContext';
import { useAuth } from '@/context/AuthContext';
import { toUserMessage } from '@/lib/api';
import {
  marketplaceApi,
  listingsApi,
  reviewsApi,
  favoritesApi,
  reportsApi,
  ListingDetail,
  ReviewItem,
} from '@/lib/marketplace';
import { packagesApi, PackageVersionInfo } from '@/lib/packages';
import { TrustBadge, RiskBadge, SecurityReport, ResourceGraph } from '@/features/packages/ui';
import type { SecurityFinding } from '@/lib/packages';
import {
  ChangelogView,
  FavoriteButton,
  InstallStateButton,
  PricingBadge,
  RatingDistribution,
  RatingStars,
  VerificationBadge,
  ListingCardView,
} from '@/features/marketplace/ui';
import { AlertTriangle, Flag, Share2 } from 'lucide-react';
import { useQuery, useQueryClient } from '@tanstack/react-query';

export default function MarketplaceDetailPage() {
  const params = useParams<{ slug: string }>();
  const slug = params.slug;
  const queryClient = useQueryClient();
  const { currentOrgId } = useOrganization();
  const { user } = useAuth();

  const [selectedVersion, setSelectedVersion] = React.useState('');
  const [installing, setInstalling] = React.useState(false);
  const [installMsg, setInstallMsg] = React.useState<string | null>(null);
  const [favPending, setFavPending] = React.useState(false);
  const [reportOpen, setReportOpen] = React.useState(false);
  const [reportReason, setReportReason] = React.useState('SPAM');
  const [reportDetails, setReportDetails] = React.useState('');
  const [reportMsg, setReportMsg] = React.useState<string | null>(null);
  const [reviewRating, setReviewRating] = React.useState(5);
  const [reviewTitle, setReviewTitle] = React.useState('');
  const [reviewBody, setReviewBody] = React.useState('');
  const [reviewMsg, setReviewMsg] = React.useState<string | null>(null);
  const [shareMsg, setShareMsg] = React.useState<string | null>(null);

  const detailQuery = useQuery({
    queryKey: ['marketplace-detail', slug],
    queryFn: () => marketplaceApi.get(slug),
    staleTime: 15_000,
  });
  const detail: ListingDetail | undefined = detailQuery.data;

  React.useEffect(() => {
    if (detail && !selectedVersion) setSelectedVersion(detail.published_version || '');
  }, [detail, selectedVersion]);

  const manifestQuery = useQuery({
    queryKey: ['listing-manifest', detail?.package_id, selectedVersion],
    queryFn: () => packagesApi.versionDetail(currentOrgId!, detail!.package_id, selectedVersion),
    enabled: Boolean(currentOrgId && detail?.package_id && selectedVersion),
    staleTime: 60_000,
    retry: false,
  });
  const manifest: PackageVersionInfo | undefined = manifestQuery.data as PackageVersionInfo | undefined;

  const relatedQuery = useQuery({
    queryKey: ['marketplace-related', slug],
    queryFn: () => marketplaceApi.related(slug, 6),
    enabled: Boolean(slug),
    staleTime: 60_000,
  });

  const reviewsQuery = useQuery({
    queryKey: ['listing-reviews', detail?.id],
    queryFn: () => reviewsApi.list({ listing_id: detail!.id, page_size: 10 }),
    enabled: Boolean(detail?.id),
    staleTime: 15_000,
  });

  const refresh = () => {
    void detailQuery.refetch();
    void reviewsQuery.refetch();
  };

  const doInstall = async () => {
    if (!currentOrgId || !detail) return;
    setInstalling(true);
    setInstallMsg(null);
    try {
      const res = await listingsApi.install(currentOrgId, detail.id, {
        version: selectedVersion || undefined,
        idempotency_key: `mkt-${detail.id}-${Date.now()}`,
      });
      if (res.status === 'INSTALLED') {
        setInstallMsg(`Installed v${res.version}. Signature: ${res.signature}.`);
        queryClient.invalidateQueries({ queryKey: ['marketplace-detail', slug] });
      } else {
        setInstallMsg(`Install finished with status ${res.status}: ${res.error || 'see installations'}`);
      }
    } catch (e: unknown) {
      const err = e as { status?: number; message?: string };
      if (err?.status === 402) {
        setInstallMsg(`Purchase required: ${(e as Error).message}. This listing is paid and no entitlement was found.`);
      } else {
        setInstallMsg(toUserMessage(e));
      }
    } finally {
      setInstalling(false);
    }
  };

  const toggleFavorite = async () => {
    if (!detail) return;
    setFavPending(true);
    try {
      if (detail.favorite) {
        await favoritesApi.remove(detail.id);
      } else {
        await favoritesApi.add(detail.id);
      }
      void detailQuery.refetch();
    } catch (e: unknown) {
      setInstallMsg(toUserMessage(e));
    } finally {
      setFavPending(false);
    }
  };

  const submitReport = async () => {
    if (!detail) return;
    setReportMsg(null);
    try {
      await reportsApi.create({
        target_type: 'listing',
        target_id: detail.id,
        target_slug: detail.slug,
        reason: reportReason,
        details: reportDetails,
      });
      setReportMsg('Report submitted. Moderators review every report with an audit trail.');
      setReportDetails('');
    } catch (e: unknown) {
      setReportMsg(toUserMessage(e));
    }
  };

  const submitReview = async () => {
    if (!detail) return;
    setReviewMsg(null);
    try {
      await reviewsApi.create({
        listing_id: detail.id,
        rating: reviewRating,
        title: reviewTitle,
        body: reviewBody,
      });
      setReviewTitle('');
      setReviewBody('');
      setReviewRating(5);
      setReviewMsg('Review submitted. Thank you.');
      refresh();
    } catch (e: unknown) {
      setReviewMsg(toUserMessage(e));
    }
  };

  const share = async () => {
    const url = window.location.href;
    try {
      await navigator.clipboard.writeText(url);
      setShareMsg('Link copied to clipboard.');
    } catch {
      setShareMsg(url);
    }
  };

  const manifestResources = ((manifest?.manifest as Record<string, unknown> | undefined)?.resources as { kind: string; slug: string; name: string }[] | undefined) ?? [];
  const manifestDeps = ((manifest?.manifest as Record<string, unknown> | undefined)?.dependencies as { type: string; package: string; version: string }[] | undefined) ?? [];

  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          {detailQuery.isLoading && <p className="text-sm text-muted-foreground">Loading listing…</p>}
          {detailQuery.isError && (
            <ErrorState
              title="Listing unavailable"
              description={detailQuery.error instanceof Error ? detailQuery.error.message : 'Could not load this listing.'}
              onRetry={() => detailQuery.refetch()}
            />
          )}
          {detail && (
            <>
              <PageHeader
                title={detail.title}
                description={detail.short_description || 'No description.'}
                breadcrumbs={[
                  { label: 'Home', href: '/' },
                  { label: 'Marketplace', href: '/marketplace' },
                  { label: detail.title },
                ]}
              />
              <div className="flex flex-wrap items-center gap-2">
                <TrustBadge trust={detail.trust_level} official={!!detail.badges?.official} />
                <VerificationBadge status={detail.publisher_verification} />
                <Badge variant="outline">{detail.category || 'Uncategorized'}</Badge>
                <PricingBadge pricingModel={detail.pricing_model} products={detail.products} />
                <RiskBadge risk={detail.security_status} />
                <span className="ml-auto flex flex-wrap items-center gap-2">
                  <FavoriteButton favorite={detail.favorite} count={detail.favorite_count} pending={favPending} onToggle={toggleFavorite} />
                  <Button variant="outline" size="sm" onClick={share} aria-label="Share listing">
                    <Share2 className="mr-1.5 h-3.5 w-3.5" aria-hidden /> Share
                  </Button>
                  <Button variant="outline" size="sm" onClick={() => setReportOpen(true)} aria-label="Report listing">
                    <Flag className="mr-1.5 h-3.5 w-3.5" aria-hidden /> Report
                  </Button>
                  <InstallStateButton
                    listing={{
                      status: detail.status,
                      installed: detail.installed,
                      installed_version: detail.installed_version,
                      published_version: detail.published_version,
                    }}
                    pending={installing}
                    onInstall={doInstall}
                  />
                </span>
              </div>
              {shareMsg && <p className="break-all text-xs text-muted-foreground">{shareMsg}</p>}
              {installMsg && (
                <p role="status" className="rounded-md border p-3 text-sm">{installMsg}</p>
              )}

              <div className="flex flex-wrap items-center gap-3 text-sm">
                <RatingStars average={detail.rating_average} count={detail.rating_count} />
                <span className="text-muted-foreground">· {detail.install_count} installs</span>
                <span className="text-muted-foreground">· {detail.view_count} views</span>
                <span className="text-muted-foreground">
                  · by{' '}
                  <Link href={`/marketplace/publisher/${detail.publisher_slug}`} className="text-primary underline">
                    {detail.publisher_name}
                  </Link>
                </span>
                <span className="text-muted-foreground">· License: {detail.license || '—'}</span>
                <div className="flex items-center gap-2">
                  <label htmlFor="version-select" className="font-medium">Version</label>
                  <select
                    id="version-select"
                    className="rounded-md border border-input bg-background px-3 py-1.5"
                    value={selectedVersion}
                    onChange={(e) => setSelectedVersion(e.target.value)}
                  >
                    {detail.versions.map((v) => (
                      <option key={v.version_id} value={v.version}>
                        v{v.version}{v.is_current ? ' (current)' : ''}
                      </option>
                    ))}
                    {detail.versions.length === 0 && detail.published_version && (
                      <option value={detail.published_version}>v{detail.published_version}</option>
                    )}
                  </select>
                  <StatusBadge status={detail.status} />
                </div>
              </div>

              <Tabs defaultValue="overview">
                <TabsList>
                  <TabsTrigger value="overview">Overview</TabsTrigger>
                  <TabsTrigger value="resources">Included resources</TabsTrigger>
                  <TabsTrigger value="security">Security</TabsTrigger>
                  <TabsTrigger value="versions">Versions</TabsTrigger>
                  <TabsTrigger value="reviews">Reviews ({detail.rating_count})</TabsTrigger>
                </TabsList>

                <TabsContent value="overview">
                  <div className="grid gap-4 md:grid-cols-2">
                    <Card>
                      <CardHeader><CardTitle className="text-base">About</CardTitle></CardHeader>
                      <CardContent className="space-y-2 text-sm">
                        <p className="whitespace-pre-wrap">{detail.full_description || detail.short_description || 'No description.'}</p>
                        {detail.tags.length > 0 && (
                          <div className="flex flex-wrap gap-1.5 pt-2">
                            {detail.tags.map((t) => (
                              <Badge key={t} variant="secondary">{t}</Badge>
                            ))}
                          </div>
                        )}
                      </CardContent>
                    </Card>
                    <Card>
                      <CardHeader><CardTitle className="text-base">Requirements & compatibility</CardTitle></CardHeader>
                      <CardContent className="space-y-1 text-sm">
                        <p>Compatibility: <code className="text-xs">{JSON.stringify(detail.compatibility)}</code></p>
                        <p>Requirements: <code className="text-xs">{JSON.stringify(detail.requirements)}</code></p>
                        <p>Trust: {detail.trust_level} · Security: {detail.security_status}</p>
                        {detail.advisories.length > 0 && (
                          <div className="rounded-md border border-destructive/40 p-2">
                            <p className="flex items-center gap-1 font-medium text-destructive">
                              <AlertTriangle className="h-4 w-4" aria-hidden /> Security advisories ({detail.advisories.length})
                            </p>
                            {detail.advisories.map((a) => (
                              <p key={a.id} className="text-muted-foreground">
                                [{a.severity}] {a.title} — affected: {a.affected_versions || 'see advisory'}
                                {a.recommended_version ? ` → update to v${a.recommended_version}` : ''}
                              </p>
                            ))}
                          </div>
                        )}
                      </CardContent>
                    </Card>
                  </div>
                </TabsContent>

                <TabsContent value="resources">
                  <Card>
                    <CardContent className="space-y-4">
                      {!manifest && (
                        <p className="text-sm text-muted-foreground">
                          Resource manifest unavailable (private package or not yet synced).
                        </p>
                      )}
                      {manifestResources.length > 0 && (
                        <div>
                          <p className="mb-1 text-sm font-medium">Included resources ({manifestResources.length})</p>
                          <ul className="space-y-1 text-sm">
                            {manifestResources.slice(0, 30).map((r) => (
                              <li key={`${r.kind}-${r.slug}`} className="flex items-center gap-2">
                                <Badge variant="outline">{r.kind}</Badge>
                                <span className="font-medium">{r.name}</span>
                                <span className="text-muted-foreground">{r.slug}</span>
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                      {manifest?.graph && (
                        <div>
                          <p className="mb-1 text-sm font-medium">Dependency graph</p>
                          <ResourceGraph nodes={manifest.graph.nodes} edges={manifest.graph.edges} />
                        </div>
                      )}
                      {manifestDeps.length > 0 && (
                        <div>
                          <p className="mb-1 text-sm font-medium">Dependencies</p>
                          <ul className="space-y-1 text-sm text-muted-foreground">
                            {manifestDeps.map((d, i) => (
                              <li key={i}><code className="text-xs">{d.type}:{d.package} {d.version}</code></li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </CardContent>
                  </Card>
                </TabsContent>

                <TabsContent value="security">
                  <Card>
                    <CardContent>
                      <SecurityTabContent listingId={detail.id} />
                    </CardContent>
                  </Card>
                </TabsContent>

                <TabsContent value="versions">
                  <Card>
                    <CardContent className="space-y-4">
                      {detail.versions.length === 0 && (
                        <p className="text-sm text-muted-foreground">No version history published.</p>
                      )}
                      {detail.versions.map((v) => (
                        <div key={v.version_id} className="rounded-md border p-3">
                          <p className="text-sm font-medium">
                            v{v.version} {v.is_current && <Badge variant="secondary">current</Badge>}
                          </p>
                          <ChangelogView changelog={v.changelog ?? {}} />
                        </div>
                      ))}
                    </CardContent>
                  </Card>
                </TabsContent>

                <TabsContent value="reviews">
                  <div className="grid gap-4 md:grid-cols-3">
                    <Card>
                      <CardHeader><CardTitle className="text-base">Rating summary</CardTitle></CardHeader>
                      <CardContent className="space-y-3">
                        <RatingStars average={detail.rating_average} count={detail.rating_count} />
                        <RatingDistribution distribution={detail.rating_distribution ?? {}} />
                        <p className="text-xs text-muted-foreground">
                          {detail.verified_review_count} verified-use review(s). Aggregates are computed
                          from published reviews only and cannot be edited by publishers.
                        </p>
                      </CardContent>
                    </Card>
                    <div className="space-y-4 md:col-span-2">
                      <ReviewsList listingId={detail.id} />
                      <Card>
                        <CardHeader><CardTitle className="text-base">Write a review</CardTitle></CardHeader>
                        <CardContent className="space-y-3 text-sm">
                          <p className="text-muted-foreground">
                            Reviews pin the installed version. Verified-use reviews require an
                            installation of this package in your organization.
                          </p>
                          <div className="flex items-center gap-2">
                            <label htmlFor="review-rating">Rating</label>
                            <select id="review-rating" className="rounded-md border border-input bg-background px-2 py-1" value={reviewRating} onChange={(e) => setReviewRating(Number(e.target.value))}>
                              {[5, 4, 3, 2, 1].map((n) => (
                                <option key={n} value={n}>{n} star{n > 1 ? 's' : ''}</option>
                              ))}
                            </select>
                          </div>
                          <Input placeholder="Title (optional)" aria-label="Review title" value={reviewTitle} onChange={(e) => setReviewTitle(e.target.value)} />
                          <textarea
                            className="min-h-24 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                            placeholder="What worked, what didn't, which version did you run?"
                            aria-label="Review body"
                            value={reviewBody}
                            onChange={(e) => setReviewBody(e.target.value)}
                          />
                          <Button size="sm" onClick={submitReview} disabled={!reviewBody.trim()}>
                            Submit review
                          </Button>
                          {reviewMsg && <p role="status" className="text-muted-foreground">{reviewMsg}</p>}
                        </CardContent>
                      </Card>
                    </div>
                  </div>
                </TabsContent>
              </Tabs>

              {relatedQuery.data && relatedQuery.data.data.length > 0 && (
                <section aria-label="Related packages">
                  <h2 className="mb-2 text-lg font-semibold">Related packages</h2>
                  <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                    {relatedQuery.data.data.map((r) => (
                      <div key={r.listing.id}>
                        <ListingCardView listing={r.listing} />
                        <p className="mt-1 text-xs text-muted-foreground">{r.reasons.join(' · ')}</p>
                      </div>
                    ))}
                  </div>
                </section>
              )}

              <Dialog open={reportOpen} onClose={() => setReportOpen(false)} title="Report this listing" description="Reports go to the moderation queue with an audit trail.">
                <div className="space-y-3 text-sm">
                  <select aria-label="Report reason" className="w-full rounded-md border border-input bg-background px-3 py-2" value={reportReason} onChange={(e) => setReportReason(e.target.value)}>
                    {['SPAM', 'FRAUD', 'MALICIOUS', 'IMPERSONATION', 'COPYRIGHT', 'TRADEMARK', 'POLICY_VIOLATION', 'ABUSE', 'OTHER'].map((r) => (
                      <option key={r} value={r}>{r}</option>
                    ))}
                  </select>
                  <textarea className="min-h-20 w-full rounded-md border border-input bg-background px-3 py-2" placeholder="Details (optional)" aria-label="Report details" value={reportDetails} onChange={(e) => setReportDetails(e.target.value)} />
                  {reportMsg && <p role="status" className="text-muted-foreground">{reportMsg}</p>}
                  <div className="flex justify-end gap-2">
                    <Button variant="outline" onClick={() => setReportOpen(false)}>Cancel</Button>
                    <Button onClick={submitReport}>Submit report</Button>
                  </div>
                </div>
              </Dialog>
            </>
          )}
        </div>
      </Layout>
    </Protected>
  );
}

function SecurityTabContent({ listingId }: { listingId: string }) {
  const { currentOrgId } = useOrganization();
  const query = useQuery({
    queryKey: ['listing-security', listingId],
    queryFn: () => listingsApi.security(currentOrgId!, listingId),
    enabled: Boolean(currentOrgId && listingId),
    staleTime: 60_000,
  });
  if (query.isLoading) return <p className="text-sm text-muted-foreground">Loading security report…</p>;
  if (query.isError || !query.data) return <p className="text-sm text-muted-foreground">Security report unavailable.</p>;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2 text-sm">
        <RiskBadge risk={query.data.risk} />
        <Badge variant="outline">Signature: {query.data.signature}</Badge>
      </div>
      <SecurityReport
        findings={(query.data.findings ?? []).map((f) => ({
          ...f,
          severity: (['INFO', 'WARNING', 'ERROR', 'BLOCKER'] as const).includes(
            f.severity as 'INFO',
          )
            ? (f.severity as SecurityFinding['severity'])
            : 'INFO',
        }))}
        risk={query.data.risk}
      />
    </div>
  );
}

function ReviewsList({ listingId }: { listingId: string }) {
  const [page, setPage] = React.useState(1);
  const query = useQuery({
    queryKey: ['listing-reviews-page', listingId, page],
    queryFn: () => reviewsApi.list({ listing_id: listingId, page, page_size: 10 }),
    staleTime: 15_000,
  });
  const reviews: ReviewItem[] = query.data?.data ?? [];
  const total = query.data?.meta.total_items ?? 0;
  const { user } = useAuth();
  const [msg, setMsg] = React.useState<string | null>(null);
  const [responding, setResponding] = React.useState<string | null>(null);
  const [responseBody, setResponseBody] = React.useState('');

  const report = async (id: string) => {
    setMsg(null);
    try {
      await reviewsApi.report(id, { reason: 'SPAM', details: 'Reported from listing page.' });
      setMsg('Review reported for moderation.');
      void query.refetch();
    } catch (e: unknown) {
      setMsg(toUserMessage(e));
    }
  };

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

  if (query.isLoading) return <p className="text-sm text-muted-foreground">Loading reviews…</p>;
  if (reviews.length === 0) return <p className="text-sm text-muted-foreground">No reviews yet — be the first.</p>;
  return (
    <div className="space-y-3">
      {msg && <p role="status" className="text-sm text-muted-foreground">{msg}</p>}
      {reviews.map((r) => (
        <Card key={r.id}>
          <CardContent className="space-y-2 py-4 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <RatingStars average={r.rating} count={1} />
              {r.verified_use && <Badge variant="success">Verified use</Badge>}
              {r.status !== 'PUBLISHED' && <StatusBadge status={r.status} />}
              <span className="ml-auto text-xs text-muted-foreground">
                v{r.version_id.slice(0, 8)}… · {new Date(r.created_at).toLocaleDateString()}
              </span>
            </div>
            {r.title && <p className="font-medium">{r.title}</p>}
            <p className="whitespace-pre-wrap text-muted-foreground">{r.body}</p>
            {r.response && (
              <div className="rounded-md bg-muted p-2">
                <p className="text-xs font-medium">Publisher response</p>
                <p className="whitespace-pre-wrap text-muted-foreground">{r.response.body}</p>
              </div>
            )}
            <div className="flex gap-2">
              <Button variant="ghost" size="sm" onClick={() => report(r.id)}>Report</Button>
              {user && (
                <Button variant="ghost" size="sm" onClick={() => setResponding(responding === r.id ? null : r.id)}>
                  Respond as publisher
                </Button>
              )}
            </div>
            {responding === r.id && (
              <div className="space-y-2">
                <textarea
                  className="min-h-16 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                  placeholder="Publisher response…"
                  aria-label="Publisher response"
                  value={responseBody}
                  onChange={(e) => setResponseBody(e.target.value)}
                />
                <Button size="sm" onClick={() => respond(r.id)} disabled={!responseBody.trim()}>
                  Publish response
                </Button>
              </div>
            )}
          </CardContent>
        </Card>
      ))}
      <div className="flex items-center gap-2 text-sm">
        <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>Previous</Button>
        <span className="text-muted-foreground">Page {page} · {total} review(s)</span>
        <Button variant="outline" size="sm" disabled={page * 10 >= total} onClick={() => setPage((p) => p + 1)}>Next</Button>
      </div>
    </div>
  );
}
