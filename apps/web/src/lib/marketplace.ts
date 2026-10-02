// MP23: typed client for marketplace discovery, publishers, listings,
// reviews, favorites, advisories, distribution, commerce and notifications.

import { api } from '@/lib/api';

export interface ListingCard {
  id: string;
  marketplace_id: string;
  marketplace_slug?: string;
  package_id: string;
  package_type?: string;
  publisher_id: string;
  publisher_slug: string;
  publisher_name: string;
  publisher_verification: string;
  slug: string;
  title: string;
  short_description: string;
  full_description: string;
  icon: string;
  banner: string;
  screenshots: string[];
  videos: string[];
  category: string;
  license: string;
  pricing_model: string;
  compatibility: Record<string, unknown>;
  requirements: Record<string, unknown>;
  trust_level: string;
  security_status: string;
  published_version_id: string | null;
  published_version: string;
  status: string;
  status_reason: string;
  badges: Record<string, unknown>;
  rating_average: number;
  rating_count: number;
  rating_distribution: Record<string, number>;
  verified_review_count: number;
  install_count: number;
  successful_install_count: number;
  active_install_count: number;
  favorite_count: number;
  view_count: number;
  installed: boolean;
  installed_version: string;
  installation_id?: string | null;
  favorite: boolean;
  relevance?: number;
  published_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ListingDetail extends ListingCard {
  tags: string[];
  versions: {
    version: string;
    version_id: string;
    is_current: boolean;
    changelog: Record<string, unknown>;
    created_at: string;
  }[];
  products: {
    id: string;
    product_type: string;
    pricing_model: string;
    currency: string;
    status: string;
    prices: {
      id: string;
      amount_minor: number;
      currency: string;
      interval: string;
      tiers: unknown[];
    }[];
  }[];
  advisories: {
    id: string;
    title: string;
    severity: string;
    status: string;
    affected_versions: string;
    recommended_version: string;
  }[];
}

export interface PublisherProfile {
  id: string;
  slug: string;
  display_name: string;
  publisher_type: string;
  avatar: string;
  banner: string;
  description: string;
  website: string;
  social_links: Record<string, string>;
  verification_status: string;
  verified: boolean;
  verified_at: string | null;
  trust_status: string;
  organization_id: string | null;
  member_count: number;
  follower_count: number;
  published_listings: number;
  my_role?: string;
  listings?: ListingCard[];
  following?: boolean;
  average_rating?: number;
}

export interface ReviewItem {
  id: string;
  listing_id: string;
  version_id: string;
  installation_id: string | null;
  reviewer_user_id: string;
  organization_id: string;
  rating: number;
  title: string;
  body: string;
  usage_context: string;
  status: string;
  status_reason: string;
  verified_use: boolean;
  helpful_count: number;
  response: { body: string; created_at: string } | null;
  created_at: string;
  updated_at: string;
}

export interface CategoryNode {
  id: string;
  slug: string;
  name: string;
  description: string;
  official: boolean;
  children: CategoryNode[];
}

function qs(params?: Record<string, string | number | boolean | undefined>): string {
  if (!params) return '';
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== '') q.set(k, String(v));
  }
  const s = q.toString();
  return s ? `?${s}` : '';
}

function org(orgId: string, suffix: string): string {
  return `/organizations/${orgId}${suffix}`;
}

export const marketplaceApi = {
  search(params?: Record<string, string | number | boolean | undefined>) {
    return api.get<{ data: ListingCard[]; featured: ListingCard[]; meta: { total_items: number } }>(
      `/marketplace/search${qs(params)}`,
    );
  },
  categories(marketplace?: string) {
    return api.get<{ data: CategoryNode[] }>(`/marketplace/categories${qs({ marketplace })}`);
  },
  featured() {
    return api.get<{
      sections: { key: string; label: string; editorial: boolean; items: ListingCard[] }[];
    }>('/marketplace/featured');
  },
  get(slug: string) {
    return api.get<ListingDetail>(`/marketplace/${encodeURIComponent(slug)}`);
  },
  related(slug: string, limit = 8) {
    return api.get<{ data: { listing: ListingCard; reasons: string[] }[] }>(
      `/marketplace/${encodeURIComponent(slug)}/related${qs({ limit })}`,
    );
  },
};

export interface MarketplaceInfo {
  id: string;
  slug: string;
  name: string;
  type: string;
  owner_organization_id: string | null;
  visibility: string;
  status: string;
}

export const marketplacesApi = {
  list(orgId: string) {
    return api.get<{ data: MarketplaceInfo[] }>(org(orgId, '/marketplaces'));
  },
  policy(orgId: string, id: string) {
    return api.get<{ rules: Record<string, unknown>; is_active: boolean }>(
      org(orgId, `/marketplaces/${id}/policy`),
    );
  },
};

export const listingsApi = {  list(orgId: string, params?: Record<string, string | number | boolean | undefined>) {
    return api.get<{ data: ListingCard[]; meta: { total_items: number } }>(
      org(orgId, `/listings${qs(params)}`),
    );
  },
  get(orgId: string, id: string) {
    return api.get<ListingDetail>(org(orgId, `/listings/${id}`));
  },
  create(orgId: string, input: unknown) {
    return api.post<ListingCard>(org(orgId, '/listings'), input);
  },
  update(orgId: string, id: string, input: unknown) {
    return api.patch<ListingCard>(org(orgId, `/listings/${id}`), input);
  },
  addVersion(orgId: string, id: string, input: { version_id: string; changelog?: Record<string, unknown> }) {
    return api.post(org(orgId, `/listings/${id}/versions`), input);
  },
  submit(orgId: string, id: string) {
    return api.post(org(orgId, `/listings/${id}/submit`), {});
  },
  action(orgId: string, id: string, verb: string, reason = '') {
    return api.post<ListingDetail>(org(orgId, `/listings/${id}/${verb}`), { reason });
  },
  revoke(orgId: string, id: string, input: { reason: string; revoke_package_version?: boolean; recommended_version?: string }) {
    return api.post<ListingDetail>(org(orgId, `/listings/${id}/revoke`), input);
  },
  versions(orgId: string, id: string) {
    return api.get<{ data: ListingDetail['versions'] }>(org(orgId, `/listings/${id}/versions`));
  },
  security(orgId: string, id: string) {
    return api.get<{
      risk: string;
      trust_level: string;
      security_status: string;
      findings: { code: string; path: string; severity: string; message: string }[];
      signature: string;
      advisories: ListingDetail['advisories'];
    }>(org(orgId, `/listings/${id}/security`));
  },
  health(orgId: string, id: string) {
    return api.get<{ status: string; reasons: string[] }>(org(orgId, `/listings/${id}/health`));
  },
  timeline(orgId: string, id: string) {
    return api.get<{ data: { kind: string; type: string; at: string }[] }>(
      org(orgId, `/listings/${id}/timeline`),
    );
  },
  analytics(orgId: string, id: string, days = 30) {
    return api.get<{ totals: Record<string, number>; series: Record<string, unknown>[] }>(
      org(orgId, `/listings/${id}/analytics${qs({ days })}`),
    );
  },
  install(orgId: string, id: string, input: { version?: string; values?: Record<string, unknown>; idempotency_key?: string }) {
    return api.post<{ id: string; status: string; version: string; signature: string; error: string }>(
      org(orgId, `/listings/${id}/install`),
      input,
    );
  },
};

export const publishersApi = {
  list(params?: Record<string, string | number | boolean | undefined>) {
    return api.get<{ data: PublisherProfile[]; meta: { total_items: number } }>(
      `/publishers${qs(params)}`,
    );
  },
  get(slug: string) {
    return api.get<PublisherProfile & { listings: ListingCard[] }>(
      `/publishers/${encodeURIComponent(slug)}`,
    );
  },
  create(input: unknown) {
    return api.post<PublisherProfile>('/publishers', input);
  },
  update(slug: string, input: unknown) {
    return api.patch<PublisherProfile>(`/publishers/${encodeURIComponent(slug)}`, input);
  },
  requestVerification(slug: string) {
    return api.post(`/publishers/${encodeURIComponent(slug)}/verification/request`, {});
  },
  decideVerification(slug: string, input: { target: string; reason: string }) {
    return api.post(`/publishers/${encodeURIComponent(slug)}/verification/decide`, input);
  },
  follow(slug: string) {
    return api.post(`/publishers/${encodeURIComponent(slug)}/follow`, {});
  },
  unfollow(slug: string) {
    return api.delete(`/publishers/${encodeURIComponent(slug)}/follow`);
  },
  analytics(slug: string, days = 30) {
    return api.get<{ totals: Record<string, number>; series: Record<string, unknown>[]; per_listing: unknown[] }>(
      `/publishers/${encodeURIComponent(slug)}/analytics${qs({ days })}`,
    );
  },
  reviews(slug: string, params?: Record<string, string | number | undefined>) {
    return api.get<{ data: ReviewItem[]; meta: { total_items: number } }>(
      `/publishers/${encodeURIComponent(slug)}/reviews${qs(params)}`,
    );
  },
};

export const reviewsApi = {
  list(params: { listing_id: string; status?: string; page?: number; page_size?: number }) {
    return api.get<{
      data: ReviewItem[];
      meta: { total_items: number };
      summary: {
        rating_average: number;
        rating_count: number;
        rating_distribution: Record<string, number>;
        verified_review_count: number;
      };
    }>(`/reviews${qs(params)}`);
  },
  create(input: unknown) {
    return api.post<ReviewItem>('/reviews', input);
  },
  update(id: string, input: unknown) {
    return api.patch<ReviewItem>(`/reviews/${id}`, input);
  },
  remove(id: string) {
    return api.delete(`/reviews/${id}`);
  },
  respond(id: string, body: string) {
    return api.post(`/reviews/${id}/respond`, { body });
  },
  report(id: string, input: { reason: string; details?: string }) {
    return api.post(`/reviews/${id}/report`, input);
  },
  moderate(id: string, input: { action: string; reason: string }) {
    return api.post(`/reviews/${id}/moderate`, input);
  },
};

export const favoritesApi = {
  list(params?: Record<string, string | number | undefined>) {
    return api.get<{ data: ListingCard[]; meta: { total_items: number } }>(
      `/favorites${qs(params)}`,
    );
  },
  add(listing_id: string) {
    return api.post('/favorites', { listing_id });
  },
  remove(listing_id: string) {
    return api.delete(`/favorites/${listing_id}`);
  },
};

export const advisoriesApi = {
  list(params?: Record<string, string | number | undefined>) {
    return api.get<{ data: Advisory[] }>(
      `/security-advisories${qs(params)}`,
    );
  },
  get(id: string) {
    return api.get(`/security-advisories/${id}`);
  },
  affected(id: string) {
    return api.get<{ data: { installation_id: string; version: string; status: string }[] }>(
      `/security-advisories/${id}/affected`,
    );
  },
};

export interface Advisory {
  id: string;
  package_id: string | null;
  listing_id: string | null;
  title: string;
  description: string;
  affected_versions: string;
  severity: string;
  status: string;
  recommended_action: string;
  recommended_version: string;
  published_at: string | null;
  created_at: string;
}

export const commerceApi = {
  products(orgId: string) {
    return api.get<{ data: unknown[] }>(org(orgId, '/commerce/products'));
  },
  createProduct(orgId: string, input: unknown) {
    return api.post(org(orgId, '/commerce/products'), input);
  },
  createPrice(orgId: string, productId: string, input: unknown) {
    return api.post(org(orgId, `/commerce/products/${productId}/prices`), input);
  },
  activateProduct(orgId: string, productId: string) {
    return api.post(org(orgId, `/commerce/products/${productId}/activate`), {});
  },
  entitlements(orgId: string, mine = true) {
    return api.get<{ data: unknown[] }>(org(orgId, `/commerce/entitlements${qs({ mine })}`));
  },
  grantEntitlement(orgId: string, input: unknown) {
    return api.post(org(orgId, '/commerce/entitlements'), input);
  },
  revenue(orgId: string, publisherId: string) {
    return api.get<{ data: unknown[]; totals: Record<string, number>; note: string }>(
      org(orgId, `/commerce/revenue${qs({ publisher_id: publisherId })}`),
    );
  },
  payouts(orgId: string, publisherId: string) {
    return api.get<{ data: unknown[]; note: string }>(
      org(orgId, `/commerce/payouts${qs({ publisher_id: publisherId })}`),
    );
  },
};

export const studioApi = {
  profile(orgId: string) {
    return api.get<{ data: (PublisherProfile & { my_role: string })[] }>(
      org(orgId, '/publisher/profile'),
    );
  },
  listings(orgId: string, params?: Record<string, string | number | undefined>) {
    return api.get<{ data: ListingCard[]; meta: { total_items: number } }>(
      org(orgId, `/publisher/listings${qs(params)}`),
    );
  },
  packages(orgId: string) {
    return api.get<{ data: unknown[] }>(org(orgId, '/publisher/packages'));
  },
  analytics(orgId: string, days = 30) {
    return api.get<{ totals: Record<string, number>; series: Record<string, unknown>[]; listings: number }>(
      org(orgId, `/publisher/analytics${qs({ days })}`),
    );
  },
  reviews(orgId: string, params?: Record<string, string | number | undefined>) {
    return api.get<{ data: ReviewItem[]; meta: { total_items: number } }>(
      org(orgId, `/publisher/reviews${qs(params)}`),
    );
  },
  security(orgId: string) {
    return api.get<{ data: unknown[]; advisories: Advisory[] }>(org(orgId, '/publisher/security'));
  },
};

export const notificationsApi = {
  list(orgId: string, params?: Record<string, string | number | boolean | undefined>) {
    return api.get<{
      data: {
        id: string;
        type: string;
        title: string;
        body: string;
        listing_id: string | null;
        publisher_id: string | null;
        read: boolean;
        created_at: string;
      }[];
      meta: { total_items: number };
      unread_count: number;
    }>(org(orgId, `/notifications${qs(params)}`));
  },
  markRead(orgId: string, id: string) {
    return api.post(org(orgId, `/notifications/${id}/read`), {});
  },
  prefs(orgId: string) {
    return api.get<{ prefs: Record<string, boolean> }>(org(orgId, '/notifications/prefs'));
  },
  savePrefs(orgId: string, prefs: Record<string, boolean>) {
    return api.put(org(orgId, '/notifications/prefs'), { prefs });
  },
};

export const masterApi = {
  overview() {
    return api.get<Record<string, number>>('/master/marketplace/overview');
  },
  queue(kind: string, params?: Record<string, string | number | undefined>) {
    return api.get<{ data: unknown[]; meta: { total_items: number } }>(
      `/master/marketplace/queue${qs({ kind, ...(params ?? {}) })}`,
    );
  },
  action(input: { target_type: string; target_id: string; action: string; reason: string }) {
    return api.post('/master/marketplace/action', input);
  },
  events(params?: Record<string, string | number | undefined>) {
    return api.get<{ data: unknown[]; meta: { total_items: number } }>(
      `/master/marketplace/events${qs(params)}`,
    );
  },
  createCategory(input: unknown) {
    return api.post('/master/marketplace/categories', input);
  },
};

export const reportsApi = {
  create(input: { target_type: string; target_id?: string; target_slug?: string; reason: string; details?: string }) {
    return api.post<{ id: string; status: string }>('/marketplace-reports', input);
  },
  list(params?: Record<string, string | number | undefined>) {
    return api.get<{ data: unknown[]; meta: { total_items: number } }>(
      `/marketplace-reports${qs(params)}`,
    );
  },
  triage(id: string, input: { status: string; resolution?: Record<string, unknown> }) {
    return api.post(`/marketplace-reports/${id}/triage`, input);
  },
};

export const distributionApi = {  artifacts(orgId: string, versionId: string) {
    return api.get<{ data: unknown[] }>(
      org(orgId, `/distribution/artifacts${qs({ version_id: versionId })}`),
    );
  },
};

export function formatPrice(amountMinor: number, currency: string): string {
  if (!amountMinor) return 'Free';
  try {
    return new Intl.NumberFormat(undefined, {
      style: 'currency',
      currency: currency || 'USD',
    }).format(amountMinor / 100);
  } catch {
    return `${(amountMinor / 100).toFixed(2)} ${currency}`;
  }
}
