'use client';

// MP23: shared marketplace building blocks. All values come from backend
// data; install state always reflects the latest fetched listing detail.

import * as React from 'react';
import Link from 'next/link';
import { BadgeCheck, Download, Heart, Star } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { TrustBadge } from '@/features/packages/ui';
import { formatPrice, ListingCard as Listing } from '@/lib/marketplace';
import { cn } from '@/lib/utils';

export function VerificationBadge({ status }: { status: string }) {
  const s = (status || 'UNVERIFIED').toUpperCase();
  if (s === 'VERIFIED' || s === 'OFFICIAL') {
    return (
      <Badge variant="success" className="gap-1">
        <BadgeCheck className="h-3 w-3" aria-hidden />
        {s === 'OFFICIAL' ? 'Official publisher' : 'Verified publisher'}
      </Badge>
    );
  }
  if (s === 'PENDING') return <Badge variant="warning">Verification pending</Badge>;
  if (s === 'SUSPENDED' || s === 'REVOKED')
    return <Badge variant="destructive">Publisher {s.toLowerCase()}</Badge>;
  return <Badge variant="secondary">Unverified publisher</Badge>;
}

export function RatingStars({ average, count }: { average: number; count: number }) {
  const full = Math.round(average || 0);
  return (
    <span className="inline-flex items-center gap-1" aria-label={`Rated ${average} out of 5 from ${count} reviews`}>
      {[1, 2, 3, 4, 5].map((i) => (
        <Star
          key={i}
          className={cn('h-3.5 w-3.5', i <= full ? 'fill-yellow-400 text-yellow-400' : 'text-muted-foreground')}
          aria-hidden
        />
      ))}
      <span className="text-xs text-muted-foreground">
        {average.toFixed(1)} ({count})
      </span>
    </span>
  );
}

export function PricingBadge({ pricingModel, products }: { pricingModel: string; products?: { prices: { amount_minor: number; currency: string }[] }[] }) {
  const model = (pricingModel || 'FREE').toUpperCase();
  if (model === 'FREE') return <Badge variant="success">Free</Badge>;
  const amounts = (products ?? []).flatMap((p) => (p.prices ?? []).map((pr) => ({ amount: pr.amount_minor, currency: pr.currency })));
  const cheapest = amounts.length ? amounts.reduce((a, b) => (a.amount <= b.amount ? a : b)) : null;
  return (
    <Badge variant="warning" title={cheapest ? undefined : 'Paid — price set by publisher'}>
      {cheapest ? `From ${formatPrice(cheapest.amount, cheapest.currency)}` : model}
    </Badge>
  );
}

export function HealthBadge({ status }: { status: string }) {
  const s = (status || 'UNKNOWN').toUpperCase();
  const variant = s === 'HEALTHY' ? 'success' : s === 'WARNING' ? 'warning' : s === 'UNKNOWN' ? 'secondary' : 'destructive';
  return <Badge variant={variant}>{s}</Badge>;
}

export function ListingCardView({ listing }: { listing: Listing }) {
  const badges = listing.badges ?? {};
  const editorial = ['featured', 'editorial'].filter(
    (k) => String(badges[k] ?? '').toLowerCase() === 'true',
  );
  return (
    <Link href={`/marketplace/${listing.slug}`} className="block h-full" aria-label={`Open ${listing.title}`}>
      <Card className="flex h-full flex-col transition-colors hover:border-primary/50">
        <CardHeader>
          <div className="flex items-start justify-between gap-2">
            <CardTitle className="text-base">{listing.title}</CardTitle>
            <TrustBadge trust={listing.trust_level} official={!!badges.official} />
          </div>
          <CardDescription className="line-clamp-2">{listing.short_description || 'No description.'}</CardDescription>
          <p className="text-xs text-muted-foreground">
            by {listing.publisher_name || 'Unknown publisher'}
          </p>
        </CardHeader>
        <CardContent className="mt-auto space-y-3">
          <div className="flex flex-wrap items-center gap-1.5">
            <RatingStars average={listing.rating_average} count={listing.rating_count} />
            <span className="text-xs text-muted-foreground">· {listing.install_count} installs</span>
          </div>
          <div className="flex flex-wrap gap-1.5">
            <PricingBadge pricingModel={listing.pricing_model} />
            {editorial.map((k) => (
              <Badge key={k} variant="outline">
                {k === 'featured' ? 'Featured' : 'Editorial pick'}
              </Badge>
            ))}
            {listing.installed && <Badge variant="success">Installed</Badge>}
          </div>
        </CardContent>
      </Card>
    </Link>
  );
}

export type InstallState =
  | 'install'
  | 'installing'
  | 'installed'
  | 'update-available'
  | 'blocked'
  | 'requires-configuration'
  | 'revoked'
  | 'incompatible'
  | 'needs-entitlement';

export function resolveInstallState(listing: {
  status: string;
  installed: boolean;
  installed_version: string;
  published_version: string;
}): { state: InstallState; label: string } {
  if (listing.status === 'REVOKED') return { state: 'revoked', label: 'Revoked' };
  if (listing.status !== 'PUBLISHED') return { state: 'blocked', label: `Unavailable (${listing.status})` };
  if (listing.installed) {
    if (listing.installed_version && listing.published_version && listing.installed_version !== listing.published_version) {
      return { state: 'update-available', label: `Update to v${listing.published_version}` };
    }
    return { state: 'installed', label: 'Installed' };
  }
  return { state: 'install', label: 'Install' };
}

export function InstallStateButton({
  listing,
  pending,
  disabled,
  onInstall,
}: {
  listing: { status: string; installed: boolean; installed_version: string; published_version: string };
  pending?: boolean;
  disabled?: boolean;
  onInstall: () => void;
}) {
  const { state, label } = resolveInstallState(listing);
  if (state === 'installed') {
    return (
      <Button variant="outline" disabled aria-live="polite">
        {label}
      </Button>
    );
  }
  if (state === 'revoked' || state === 'blocked') {
    return (
      <Button variant="destructive" disabled aria-live="polite" title={label}>
        {label}
      </Button>
    );
  }
  return (
    <Button onClick={onInstall} loading={pending} disabled={disabled} aria-live="polite">
      <Download className="mr-2 h-4 w-4" aria-hidden /> {pending ? 'Installing…' : label}
    </Button>
  );
}

export function FavoriteButton({
  favorite,
  count,
  pending,
  onToggle,
}: {
  favorite: boolean;
  count: number;
  pending?: boolean;
  onToggle: () => void;
}) {
  return (
    <Button
      variant="outline"
      size="sm"
      onClick={onToggle}
      disabled={pending}
      aria-pressed={favorite}
      aria-label={favorite ? 'Remove from favorites' : 'Save to favorites'}
    >
      <Heart className={cn('mr-1.5 h-3.5 w-3.5', favorite && 'fill-red-500 text-red-500')} aria-hidden />
      {count}
    </Button>
  );
}

export function RatingDistribution({ distribution }: { distribution: Record<string, number> }) {
  const total = [1, 2, 3, 4, 5].reduce((n, s) => n + (distribution[String(s)] ?? 0), 0);
  return (
    <div className="space-y-1" aria-label="Rating distribution">
      {[5, 4, 3, 2, 1].map((star) => {
        const n = distribution[String(star)] ?? 0;
        const pct = total ? Math.round((n / total) * 100) : 0;
        return (
          <div key={star} className="flex items-center gap-2 text-xs">
            <span className="w-6 shrink-0">{star}★</span>
            <div className="h-2 flex-1 overflow-hidden rounded bg-muted" role="img" aria-label={`${pct}% rated ${star}`}>
              <div className="h-full bg-yellow-400" style={{ width: `${pct}%` }} />
            </div>
            <span className="w-8 shrink-0 text-right text-muted-foreground">{n}</span>
          </div>
        );
      })}
    </div>
  );
}

export function ChangelogView({ changelog }: { changelog: Record<string, unknown> }) {
  const sections: [string, string][] = [
    ['breaking', 'Breaking changes'],
    ['security', 'Security'],
    ['added', 'Added'],
    ['changed', 'Changed'],
    ['fixed', 'Fixed'],
    ['dependencies', 'Dependencies'],
    ['permissions', 'Permissions'],
  ];
  const hasAny = sections.some(([k]) => {
    const v = changelog[k];
    return Array.isArray(v) ? v.length > 0 : !!v;
  });
  if (!hasAny) {
    const notes = typeof changelog.notes === 'string' ? changelog.notes : '';
    return <p className="text-sm text-muted-foreground">{notes || 'No changelog provided.'}</p>;
  }
  return (
    <div className="space-y-3 text-sm">
      {sections.map(([key, label]) => {
        const v = changelog[key];
        const items = Array.isArray(v) ? v : v ? [v] : [];
        if (!items.length) return null;
        const highlight = key === 'breaking' || key === 'security' || key === 'permissions';
        return (
          <div key={key} className={highlight ? 'rounded-md border border-yellow-500/40 bg-yellow-500/5 p-3' : undefined}>
            <p className="font-medium">{label}</p>
            <ul className="mt-1 list-disc space-y-0.5 pl-5 text-muted-foreground">
              {items.slice(0, 15).map((item, i) => (
                <li key={i} className="break-words">
                  {typeof item === 'string' ? item : JSON.stringify(item).slice(0, 200)}
                </li>
              ))}
            </ul>
          </div>
        );
      })}
      {typeof changelog.notes === 'string' && changelog.notes && (
        <p className="text-muted-foreground">{changelog.notes}</p>
      )}
    </div>
  );
}
