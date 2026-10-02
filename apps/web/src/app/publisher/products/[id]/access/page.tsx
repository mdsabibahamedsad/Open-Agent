'use client';

export const dynamic = 'force-dynamic';

import { useQuery } from '@tanstack/react-query';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { ErrorState } from '@/components/ui/states';
import { commerceApi } from '@/lib/commerce';
import { StudioShell } from '../../../shell';

export default function ProductAccessPage({ params }: { params: { id: string } }) {
  const query = useQuery({
    queryKey: ['product-entitlements', params.id],
    queryFn: () => commerceApi.entitlements(params.id),
  });
  const rows = query.data?.data ?? [];

  return (
    <StudioShell title="Access" description="Features, plans, limits, quotas, and access duration granted by this product.">
      {query.isLoading && <p className="text-sm text-muted-foreground">Loading entitlements…</p>}
      {query.isError && (
        <ErrorState title="Entitlements unavailable" description="Could not load." onRetry={() => query.refetch()} />
      )}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Granted entitlements</CardTitle>
          <CardDescription>Commercial access only — entitlements never grant security permissions.</CardDescription>
        </CardHeader>
        <CardContent>
          {rows.length === 0 && !query.isLoading && (
            <p className="text-sm text-muted-foreground">No entitlements granted yet. They appear after verified purchases.</p>
          )}
          <ul className="space-y-2">
            {rows.map((e) => (
              <li key={e.id} className="rounded-md border px-3 py-2 text-sm">
                <strong>{(e.features ?? []).join(', ') || e.feature}</strong>
                <span className="ml-2 text-muted-foreground">
                  {e.source} · {e.status}
                  {e.valid_until ? ` · until ${new Date(e.valid_until).toLocaleDateString()}` : ' · no expiry'}
                  {e.quantity != null ? ` · ${e.used}/${e.quantity} used` : ''}
                </span>
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>
    </StudioShell>
  );
}
