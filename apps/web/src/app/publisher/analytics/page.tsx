'use client';

import * as React from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { ErrorState } from '@/components/ui/states';
import { useOrganization } from '@/context/OrganizationContext';
import { studioApi } from '@/lib/marketplace';
import { StudioShell } from '../shell';
import { useQuery } from '@tanstack/react-query';

export default function StudioAnalyticsPage() {
  const { currentOrgId } = useOrganization();
  const [days, setDays] = React.useState(30);
  const query = useQuery({
    queryKey: ['studio-analytics', currentOrgId, days],
    queryFn: () => studioApi.analytics(currentOrgId!, days),
    enabled: Boolean(currentOrgId),
    staleTime: 60_000,
  });
  const totals = (query.data?.totals ?? {}) as Record<string, number>;
  const series = (query.data?.series ?? []) as { day: string; [k: string]: unknown }[];
  const maxViews = Math.max(1, ...series.map((s) => Number(s.views ?? 0)));

  return (
    <StudioShell title="Analytics" description="Aggregated performance across your listings. Individual user activity is never exposed.">
      <div className="flex items-center gap-2 text-sm">
        <label htmlFor="days">Range</label>
        <select id="days" className="rounded-md border border-input bg-background px-3 py-1.5" value={days} onChange={(e) => setDays(Number(e.target.value))}>
          {[7, 30, 90].map((d) => (
            <option key={d} value={d}>{d} days</option>
          ))}
        </select>
      </div>
      {query.isLoading && <p className="text-sm text-muted-foreground">Loading analytics…</p>}
      {query.isError && (
        <ErrorState title="Analytics unavailable" description={query.error instanceof Error ? query.error.message : 'Could not load.'} onRetry={() => query.refetch()} />
      )}
      {query.data && (
        <>
          <div className="grid gap-3 md:grid-cols-4">
            {Object.entries(totals).map(([k, v]) => (
              <Card key={k}>
                <CardContent className="py-4">
                  <p className="text-2xl font-bold">{v}</p>
                  <p className="text-xs text-muted-foreground">{k.replaceAll('_', ' ')}</p>
                </CardContent>
              </Card>
            ))}
          </div>
          <Card>
            <CardHeader><CardTitle className="text-base">Daily views</CardTitle></CardHeader>
            <CardContent>
              {series.length === 0 ? (
                <p className="text-sm text-muted-foreground">No activity in range.</p>
              ) : (
                <div className="flex h-32 items-end gap-1" role="img" aria-label="Daily views chart">
                  {series.map((s) => (
                    <div
                      key={String(s.day)}
                      className="min-w-2 flex-1 rounded-sm bg-primary/70"
                      style={{ height: `${Math.max(2, (Number(s.views ?? 0) / maxViews) * 100)}%` }}
                      title={`${s.day}: ${s.views} views`}
                    />
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </>
      )}
    </StudioShell>
  );
}
