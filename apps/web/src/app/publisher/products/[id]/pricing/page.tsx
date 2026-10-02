'use client';

export const dynamic = 'force-dynamic';

import * as React from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { ErrorState } from '@/components/ui/states';
import { useToast } from '@/components/ui/toast';
import { toUserMessage } from '@/lib/api';
import { commerceApi, formatMinor } from '@/lib/commerce';
import { StudioShell } from '../../../shell';

const INTERVALS = ['ONE_TIME', 'DAILY', 'MONTHLY', 'YEARLY', 'CUSTOM'];
const MODELS = ['FREE', 'ONE_TIME', 'SUBSCRIPTION', 'USAGE_BASED', 'TIERED', 'VOLUME', 'CUSTOM'];

export default function ProductPricingPage({ params }: { params: { id: string } }) {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const pricesQuery = useQuery({
    queryKey: ['product-prices', params.id],
    queryFn: () => commerceApi.prices(params.id),
  });
  const [amount, setAmount] = React.useState('9.99');
  const [currency, setCurrency] = React.useState('USD');
  const [pricingModel, setPricingModel] = React.useState('ONE_TIME');
  const [interval, setInterval] = React.useState('ONE_TIME');

  const create = useMutation({
    mutationFn: () =>
      commerceApi.createPrice(params.id, {
        amount: amount.trim(),
        currency,
        pricing_model: pricingModel,
        billing_interval: interval,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['product-prices', params.id] });
      toast({ kind: 'success', title: 'Price created' });
    },
    onError: (e) => toast({ kind: 'error', title: 'Create failed', description: toUserMessage(e) }),
  });

  const rows = pricesQuery.data?.data ?? [];

  return (
    <StudioShell title="Pricing" description="Configure exactly what buyers pay. Amounts are stored as integer minor units.">
      {pricesQuery.isLoading && <p className="text-sm text-muted-foreground">Loading prices…</p>}
      {pricesQuery.isError && (
        <ErrorState title="Prices unavailable" description="Could not load." onRetry={() => pricesQuery.refetch()} />
      )}
      <ul className="space-y-2">
        {rows.map((p) => (
          <li key={p.id} className="rounded-md border px-3 py-2 text-sm">
            <strong>{formatMinor(p.amount_minor, p.currency)}</strong>
            <span className="ml-2 text-muted-foreground">
              {p.billing_interval} · {p.status}
            </span>
          </li>
        ))}
        {rows.length === 0 && !pricesQuery.isLoading && (
          <p className="text-sm text-muted-foreground">No prices yet.</p>
        )}
      </ul>
      <Card>
        <CardHeader>
          <CardTitle className="text-base">New price</CardTitle>
          <CardDescription>Free, one-time, subscription, usage-based, or tiered.</CardDescription>
        </CardHeader>
        <CardContent className="grid max-w-2xl gap-2">
          <div className="grid gap-2 sm:grid-cols-2">
            <Input value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="9.99" aria-label="Amount" />
            <Input value={currency} onChange={(e) => setCurrency(e.target.value.toUpperCase())} placeholder="USD" aria-label="Currency" />
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            <select value={pricingModel} onChange={(e) => setPricingModel(e.target.value)} className="rounded-md border border-input bg-background px-3 py-2 text-sm" aria-label="Pricing model">
              {MODELS.map((m) => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
            <select value={interval} onChange={(e) => setInterval(e.target.value)} className="rounded-md border border-input bg-background px-3 py-2 text-sm" aria-label="Billing interval">
              {INTERVALS.map((m) => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
          </div>
          <div>
            <Button onClick={() => create.mutate()} loading={create.isPending} disabled={!amount.trim()}>
              Create price
            </Button>
          </div>
        </CardContent>
      </Card>
    </StudioShell>
  );
}
