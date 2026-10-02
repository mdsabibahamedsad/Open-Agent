'use client';

import * as React from 'react';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { StatusBadge } from '@/components/ui/status';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useOrgScopedList } from '@/lib/queries';
import { useOrgChart } from '@/features/management/api';
import { OrgChartView } from '@/features/management/OrgChart';
import type { AgentSummary } from '@/types';

export default function AgentOrganizationPage() {
  const { items, isLoading, error, refetch } = useOrgScopedList<AgentSummary>(
    'agents',
    ['/organizations/{orgId}/agents', '/agents'],
  );
  const { chart, isLoading: chartLoading } = useOrgChart();

  const managers = new Set((chart?.managers ?? []).map((m) => m.agent_id));

  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader
            title="Agent Organization"
            description="Hierarchy, managers, teams, departments, capabilities, and workload."
            breadcrumbs={[
              { label: 'Home', href: '/' },
              { label: 'Agents', href: '/agents' },
              { label: 'Organization' },
            ]}
          />
          {isLoading && <p className="text-sm text-muted-foreground">Loading agents…</p>}
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}{' '}
              <button type="button" className="underline" onClick={() => refetch()}>
                Retry
              </button>
            </p>
          )}
          <Tabs defaultValue="chart">
            <TabsList>
              <TabsTrigger value="chart">Organization chart</TabsTrigger>
              <TabsTrigger value="agents">Agents ({items.length})</TabsTrigger>
            </TabsList>
            <TabsContent value="chart">
              {chartLoading && <p className="text-sm text-muted-foreground">Loading chart…</p>}
              {chart && <OrgChartView chart={chart} />}
            </TabsContent>
            <TabsContent value="agents">
              <Card>
                <CardHeader>
                  <CardTitle>Agents ({items.length})</CardTitle>
                </CardHeader>
                <CardContent>
                  <ul className="space-y-2">
                    {items.map((a) => (
                      <li
                        key={a.id}
                        className="flex items-center gap-3 rounded border p-2 text-sm"
                      >
                        <span className="font-medium">{a.name}</span>
                        <StatusBadge status={a.status || 'draft'} />
                        {managers.has(a.id) && (
                          <span className="rounded bg-primary/10 px-1.5 py-0.5 text-xs text-primary">
                            manager
                          </span>
                        )}
                        <span className="text-muted-foreground">{a.model ?? '—'}</span>
                      </li>
                    ))}
                    {items.length === 0 && !isLoading && (
                      <li className="text-sm text-muted-foreground">No agents yet.</li>
                    )}
                  </ul>
                </CardContent>
              </Card>
            </TabsContent>
          </Tabs>
        </div>
      </Layout>
    </Protected>
  );
}
