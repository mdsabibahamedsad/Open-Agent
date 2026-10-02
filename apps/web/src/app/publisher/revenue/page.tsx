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
import { StudioShell } from '../shell';

export default function CreatorRevenuePage() {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  // Revenue is keyed by publisher_id (membership-gated server-side).
  const [publisherId, setPublisherId] = React.useState('');
  const revenueQuery = useQuery({
    queryKey: ['creator-revenue', publisherId],
    queryFn: () => commerceApi.revenue(publisherId),
    enabled: Boolean(publisherId),
  });
  const ledgerQuery = useQuery({
    queryKey: ['creator-ledger', publisherId],
    queryFn: () => commerceApi.ledger(publisherId),
    enabled: Boolean(publisherId),
  });
  const payoutsQuery = useQuery({
    queryKey: ['creator-payouts', publisherId],
    queryFn: () => commerceApi.payouts(publisherId),
    enabled: Boolean(publisherId),
  });
  const [amount, setAmount] = React.useState('25.00');
  const [destination, setDestination] = React.useState('');

  const requestPayout = useMutation({
    mutationFn: () =>
      commerceApi.requestPayout({
        publisher_id: publisherId,
        amount: amount.trim(),
        currency: 'USD',
        destination_reference: destination.trim(),
      }),
    onSuccess: () => {
      setDestination('');
      queryClient.invalidateQueries({ queryKey: ['creator-payouts', publisherId] });
      toast({ kind: 'success', title: 'Payout requested' });
    },
    onError: (e) => toast({ kind: 'error', title: 'Payout failed', description: toUserMessage(e) }),
  });

  const transition = useMutation({
    mutationFn: ({ id, target }: { id: string; target: string }) =>
      commerceApi.transitionPayout(id, target),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['creator-payouts', publisherId] });
      toast({ kind: 'success', title: 'Payout updated' });
    },
    onError: (e) => toast({ kind: 'error', title: 'Update failed', description: toUserMessage(e) }),
  });

  const revenue = revenueQuery.data?.data ?? [];
  const balances = revenueQuery.data?.balances ?? {};
  const ledger = ledgerQuery.data?.data ?? [];
  const payouts = payoutsQuery.data?.data ?? [];

  return (
    <StudioShell title="Revenue" description="Sales, fees, refunds, ledger balance, and payouts — from real ledger data.">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Publisher</CardTitle>
          <CardDescription>Enter your publisher ID (membership-gated server-side).</CardDescription>
        </CardHeader>
        <CardContent className="max-w-xl">
          <Input value={publisherId} onChange={(e) => setPublisherId(e.target.value)} placeholder="Publisher ID" aria-label="Publisher ID" />
        </CardContent>
      </Card>

      {!publisherId && <p className="text-sm text-muted-foreground">Enter a publisher ID to load revenue.</p>}

      {publisherId && (
        <>
          <div className="grid gap-3 md:grid-cols-3">
            {Object.entries(balances).map(([currency, balance]) => (
              <Card key={currency}>
                <CardContent className="py-4">
                  <p className="text-2xl font-bold">{formatMinor(balance, currency)}</p>
                  <p className="text-xs text-muted-foreground">available balance · {currency}</p>
                </CardContent>
              </Card>
            ))}
            {Object.keys(balances).length === 0 && !revenueQuery.isLoading && (
              <p className="text-sm text-muted-foreground">No balance yet.</p>
            )}
          </div>

          <Card>
            <CardHeader><CardTitle className="text-base">Transactions</CardTitle></CardHeader>
            <CardContent>
              {revenueQuery.isError && (
                <ErrorState title="Revenue unavailable" description="Could not load." onRetry={() => revenueQuery.refetch()} />
              )}
              <ul className="space-y-2">
                {revenue.map((r) => (
                  <li key={r.id} className="rounded-md border px-3 py-2 text-sm">
                    <strong>{formatMinor(r.gross_minor, r.currency)}</strong>
                    <span className="ml-2 text-muted-foreground">
                      fee {formatMinor(r.fee_minor, r.currency)} · net {formatMinor(r.net_minor, r.currency)} · {r.status}
                    </span>
                  </li>
                ))}
                {revenue.length === 0 && !revenueQuery.isLoading && (
                  <p className="text-sm text-muted-foreground">No transactions yet.</p>
                )}
              </ul>
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle className="text-base">Ledger</CardTitle></CardHeader>
            <CardContent>
              <ul className="space-y-2">
                {ledger.slice(0, 20).map((e) => (
                  <li key={e.id} className="rounded-md border px-3 py-2 font-mono text-xs">
                    {e.type} {e.account} {formatMinor(e.amount_minor, e.currency)} · {e.reference_type}:{e.reference.slice(0, 8)}…
                  </li>
                ))}
                {ledger.length === 0 && !ledgerQuery.isLoading && (
                  <p className="text-sm text-muted-foreground">No ledger entries yet.</p>
                )}
              </ul>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Payouts</CardTitle>
              <CardDescription>Destination is a provider handle — raw bank credentials are never stored.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <ul className="space-y-2">
                {payouts.map((p) => (
                  <li key={p.id} className="flex flex-wrap items-center justify-between gap-2 rounded-md border px-3 py-2 text-sm">
                    <span>
                      <strong>{formatMinor(p.amount_minor, p.currency)}</strong>
                      <span className="ml-2 text-muted-foreground">
                        {p.status}{p.hold_reason ? ` · ${p.hold_reason}` : ''}
                      </span>
                    </span>
                    <span className="flex gap-2">
                      {(p.status === 'PENDING' || p.status === 'ELIGIBLE') && (
                        <Button size="sm" variant="outline" onClick={() => transition.mutate({ id: p.id, target: 'PROCESSING' })}>
                          Process
                        </Button>
                      )}
                    </span>
                  </li>
                ))}
                {payouts.length === 0 && !payoutsQuery.isLoading && (
                  <p className="text-sm text-muted-foreground">No payouts yet.</p>
                )}
              </ul>
              <div className="grid max-w-xl gap-2 sm:grid-cols-3">
                <Input value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="25.00" aria-label="Payout amount" />
                <Input value={destination} onChange={(e) => setDestination(e.target.value)} placeholder="Destination handle" aria-label="Destination reference" />
                <Button onClick={() => requestPayout.mutate()} loading={requestPayout.isPending} disabled={!destination.trim()}>
                  Request payout
                </Button>
              </div>
            </CardContent>
          </Card>
        </>
      )}
    </StudioShell>
  );
}
