// MP24: typed client for registries, billing, entitlements, usage,
// invoices, revenue, payouts and promotions. All values render from real
// backend data; nothing is fabricated client-side.

import { api } from '@/lib/api';

export interface RegistryRow {
  id: string;
  slug: string;
  name: string;
  kind: string;
  registry_type: string;
  endpoint: string;
  visibility: string;
  trust_level: string;
  auth_type: string;
  is_public: boolean;
  enabled: boolean;
  mirror_of: string;
  status: string;
}

export interface ProductRow {
  id: string;
  listing_id: string;
  product_type: string;
  pricing_model: string;
  currency: string;
  status: string;
  access: string;
}

export interface PriceRow {
  id: string;
  product_id: string;
  amount_minor: number;
  currency: string;
  interval: string;
  billing_interval: string;
  status: string;
}

export interface SubscriptionRow {
  id: string;
  status: string;
  product_id: string | null;
  price_id: string | null;
  current_period_start: string | null;
  current_period_end: string | null;
  quantity: number;
}

export interface EntitlementRow {
  id: string;
  organization_id: string | null;
  user_id: string | null;
  product_id: string | null;
  listing_id: string | null;
  feature: string;
  features: string[];
  source: string;
  status: string;
  valid_from: string | null;
  valid_until: string | null;
  quantity: number | null;
  used: number;
}

export interface InvoiceRow {
  id: string;
  currency: string;
  subtotal_minor: number;
  tax_minor: number;
  discount_minor: number;
  total_minor: number;
  status: string;
}

export interface RevenueRow {
  id: string;
  gross_minor: number;
  fee_minor: number;
  net_minor: number;
  currency: string;
  status: string;
  transaction_reference: string;
}

export interface PayoutRow {
  id: string;
  publisher_id: string;
  amount_minor: number;
  currency: string;
  status: string;
  hold_reason: string;
  provider_reference: string;
}

export function formatMinor(amountMinor: number, currency: string): string {
  const exponents: Record<string, number> = { JPY: 0 };
  const exp = exponents[currency] ?? 2;
  const major = amountMinor / 10 ** exp;
  try {
    return new Intl.NumberFormat(undefined, {
      style: 'currency',
      currency,
      minimumFractionDigits: exp,
      maximumFractionDigits: exp,
    }).format(major);
  } catch {
    return `${major.toFixed(exp)} ${currency}`;
  }
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

export const commerceApi = {
  registries() {
    return api.get<{ data: RegistryRow[] }>('/registries');
  },
  createRegistry(input: Record<string, unknown>) {
    return api.post<{ id: string }>('/registries', input);
  },
  testRegistry(id: string) {
    return api.post<{ usable: boolean; reason: string; trust_level: string }>(
      `/registries/${id}/test`, {},
    );
  },
  syncRegistry(id: string) {
    return api.post<{ id: string; status: string }>(`/registries/${id}/sync`, {});
  },
  deleteRegistry(id: string) {
    return api.delete<{ deleted: string }>(`/registries/${id}`);
  },
  billingStatus() {
    return api.get<{
      mode: string;
      provider: string;
      configured: boolean;
      test_mode: boolean;
      self_hosted_ok: boolean;
    }>('/billing/status');
  },
  billingPortal() {
    return api.post<{ portal_url: string; test_mode: boolean }>('/billing/portal', {});
  },
  products(params?: { product_type?: string }) {
    return api.get<{ data: ProductRow[] }>('/products', params);
  },
  createProduct(input: Record<string, unknown>) {
    return api.post<{ id: string }>('/products', input);
  },
  activateProduct(id: string) {
    return api.post<{ id: string; status: string }>(`/products/${id}/activate`, {});
  },
  prices(productId?: string) {
    return api.get<{ data: PriceRow[] }>('/prices', productId ? { product_id: productId } : undefined);
  },
  createPrice(productId: string, input: Record<string, unknown>) {
    return api.post<{ id: string }>(`/products/${productId}/prices`, input);
  },
  checkout(input: { product_id: string; price_id: string; idempotency_key?: string; promo_code?: string }) {
    return api.post<{
      id: string;
      provider_session_id: string;
      checkout_url: string;
      status: string;
      discount_minor: number;
      test_mode: boolean;
    }>('/checkout', input);
  },
  subscriptions(params?: { status?: string }) {
    return api.get<{ data: SubscriptionRow[] }>('/subscriptions', params);
  },
  cancelSubscription(id: string, atPeriodEnd = true) {
    return api.post<{ id: string; status: string }>(
      `/subscriptions/${id}/cancel${qs({ at_period_end: atPeriodEnd })}`, {},
    );
  },
  entitlements(productId?: string) {
    return api.get<{ data: EntitlementRow[] }>(
      '/entitlements', productId ? { product_id: productId } : undefined,
    );
  },
  checkEntitlement(feature = 'package.install') {
    return api.get<{ feature: string; allowed: boolean; reason: string }>(
      `/entitlements/check${qs({ feature })}`,
    );
  },
  revokeEntitlement(id: string, reason = '') {
    return api.post<{ id: string; status: string }>(
      `/entitlements/${id}/revoke${qs(reason ? { reason } : undefined)}`, {},
    );
  },
  meters() {
    return api.get<{
      data: { slug: string; name: string; unit: string; aggregation: string; reset_period: string }[];
    }>('/usage/meters');
  },
  usageSummary(meter: string, periodStart: string, periodEnd: string) {
    return api.get<{ meter: string; total: number; events: number; aggregation: string }>(
      `/usage/summary${qs({ meter, period_start: periodStart, period_end: periodEnd })}`,
    );
  },
  quotas() {
    return api.get<{ data: { id: string; meter_id: string; limit_value: number | null; period: string }[] }>(
      '/quotas',
    );
  },
  invoices() {
    return api.get<{ data: InvoiceRow[] }>('/invoices');
  },
  invoice(id: string) {
    return api.get<InvoiceRow & { lines: { description: string; quantity: number; unit_price_minor: number; amount_minor: number }[] }>(
      `/invoices/${id}`,
    );
  },
  revenue(publisherId: string) {
    return api.get<{ data: RevenueRow[]; balances: Record<string, number> }>(
      `/revenue${qs({ publisher_id: publisherId })}`,
    );
  },
  ledger(publisherId: string) {
    return api.get<{
      data: {
        id: string;
        account: string;
        type: string;
        amount_minor: number;
        currency: string;
        reference: string;
        reference_type: string;
        status: string;
      }[];
    }>(`/revenue/ledger${qs({ publisher_id: publisherId })}`);
  },
  payouts(publisherId?: string) {
    return api.get<{ data: PayoutRow[] }>(
      '/payouts', publisherId ? { publisher_id: publisherId } : undefined,
    );
  },
  requestPayout(input: {
    publisher_id: string;
    amount: string;
    currency?: string;
    destination_reference: string;
    idempotency_key?: string;
  }) {
    return api.post<{ id: string; status: string }>('/payouts', input);
  },
  transitionPayout(id: string, target: string, reason = '') {
    return api.post<{ id: string; status: string }>(
      `/payouts/${id}/transition${qs({ target, ...(reason ? { reason } : {}) })}`, {},
    );
  },
};
