'use client';

import * as React from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { ErrorState } from '@/components/ui/states';
import { useToast } from '@/components/ui/toast';
import { toUserMessage } from '@/lib/api';
import { commerceApi } from '@/lib/commerce';
import { StudioShell } from '../shell';

export default function PublisherProductsPage() {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: ['publisher-products'], queryFn: () => commerceApi.products() });
  const [listingId, setListingId] = React.useState('');
  const [productType, setProductType] = React.useState('PACKAGE');
  const [pricingModel, setPricingModel] = React.useState('ONE_TIME');

  const create = useMutation({
    mutationFn: () =>
      commerceApi.createProduct({
        listing_id: listingId.trim(),
        product_type: productType,
        pricing_model: pricingModel,
        currency: 'USD',
        access: pricingModel === 'FREE' ? 'FREE' : 'ENTITLEMENT_REQUIRED',
      }),
    onSuccess: () => {
      setListingId('');
      queryClient.invalidateQueries({ queryKey: ['publisher-products'] });
      toast({ kind: 'success', title: 'Product created' });
    },
    onError: (e) => toast({ kind: 'error', title: 'Create failed', description: toUserMessage(e) }),
  });

  const activate = useMutation({
    mutationFn: (id: string) => commerceApi.activateProduct(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['publisher-products'] });
      toast({ kind: 'success', title: 'Product activated' });
    },
    onError: (e) => toast({ kind: 'error', title: 'Activate failed', description: toUserMessage(e) }),
  });

  const rows = query.data?.data ?? [];

  return (
    <StudioShell title="Products" description="Attach commercial products to listings, then configure pricing and access.">
      {query.isLoading && <p className="text-sm text-muted-foreground">Loading products…</p>}
      {query.isError && (
        <ErrorState title="Products unavailable" description="Could not load." onRetry={() => query.refetch()} />
      )}
      <div className="grid gap-3 md:grid-cols-2">
        {rows.map((p) => (
          <Card key={p.id}>
            <CardHeader>
              <CardTitle className="text-base font-mono">{p.id.slice(0, 8)}…</CardTitle>
              <CardDescription>
                {p.product_type} · {p.pricing_model} · {p.currency} · {p.status} · access {p.access}
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-wrap gap-2 text-sm">
              <a className="text-primary hover:underline" href={`/publisher/products/${p.id}/pricing`}>
                Pricing →
              </a>
              <a className="text-primary hover:underline" href={`/publisher/products/${p.id}/access`}>
                Access →
              </a>
              <span className="flex-1" />
              {p.status === 'DRAFT' && (
                <Button size="sm" variant="outline" onClick={() => activate.mutate(p.id)} loading={activate.isPending}>
                  Activate
                </Button>
              )}
            </CardContent>
          </Card>
        ))}
        {rows.length === 0 && !query.isLoading && (
          <p className="text-sm text-muted-foreground">No products yet. Create one from a published listing.</p>
        )}
      </div>
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Create product</CardTitle>
          <CardDescription>Shows exactly what buyers will pay once a price is attached.</CardDescription>
        </CardHeader>
        <CardContent className="grid max-w-2xl gap-2">
          <Input value={listingId} onChange={(e) => setListingId(e.target.value)} placeholder="Listing ID" aria-label="Listing ID" />
          <div className="grid gap-2 sm:grid-cols-2">
            <select value={productType} onChange={(e) => setProductType(e.target.value)} className="rounded-md border border-input bg-background px-3 py-2 text-sm" aria-label="Product type">
              {['PACKAGE', 'SUBSCRIPTION', 'BUNDLE', 'LICENSE', 'CREDITS', 'SERVICE', 'ENTERPRISE'].map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
            <select value={pricingModel} onChange={(e) => setPricingModel(e.target.value)} className="rounded-md border border-input bg-background px-3 py-2 text-sm" aria-label="Pricing model">
              {['FREE', 'ONE_TIME', 'SUBSCRIPTION', 'USAGE_BASED', 'TIERED', 'VOLUME', 'CUSTOM'].map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
          </div>
          <div>
            <Button onClick={() => create.mutate()} loading={create.isPending} disabled={!listingId.trim()}>
              Create product
            </Button>
          </div>
        </CardContent>
      </Card>
    </StudioShell>
  );
}
