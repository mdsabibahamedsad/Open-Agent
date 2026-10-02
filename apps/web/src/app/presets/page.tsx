'use client';

import * as React from 'react';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { EmptyState, ErrorState } from '@/components/ui/states';
import { useOrganization } from '@/context/OrganizationContext';
import { presetsApi, PresetSummary } from '@/lib/packages';
import { Cpu, SlidersHorizontal } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';

const KINDS = [
  { value: 'MODEL_PRESET', label: 'Model Presets', hint: 'Routing hints for the Model Router — never direct model handles.' },
  { value: 'AGENT_PRESET', label: 'Agent Presets', hint: 'Starter agent shapes: research, coding, sales, support, analyst.' },
  { value: 'WORKFLOW_PRESET', label: 'Workflow Presets', hint: 'Recipes like lead → research → score → CRM.' },
  { value: 'MEMORY_PRESET', label: 'Memory Presets', hint: 'Memory modes resolved through the Memory Engine and org policy.' },
];

export default function PresetsPage() {
  const { currentOrgId } = useOrganization();
  const [tab, setTab] = React.useState('MODEL_PRESET');

  const query = useQuery({
    queryKey: ['presets', currentOrgId, tab],
    queryFn: () => presetsApi.list(currentOrgId!, { kind: tab, page_size: 50 }),
    enabled: Boolean(currentOrgId),
    staleTime: 30_000,
  });
  const items: PresetSummary[] = (query.data?.data as PresetSummary[]) ?? [];

  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader
            title="Presets"
            description="Reusable model, agent, workflow and memory presets. Presets declare intent — the routers and engines enforce policy."
            breadcrumbs={[{ label: 'Home', href: '/' }, { label: 'Presets' }]}
          />
          <Tabs value={tab} onValueChange={setTab}>
            <TabsList>
              {KINDS.map((k) => (
                <TabsTrigger key={k.value} value={k.value}>
                  {k.label}
                </TabsTrigger>
              ))}
            </TabsList>
            {KINDS.map((k) => (
              <TabsContent key={k.value} value={k.value}>
                <p className="mb-3 flex items-center gap-2 text-sm text-muted-foreground">
                  <SlidersHorizontal className="h-4 w-4" aria-hidden /> {k.hint}
                </p>
                {query.isLoading && <p className="text-sm text-muted-foreground">Loading presets…</p>}
                {query.isError && (
                  <ErrorState
                    title="Presets unavailable"
                    description={query.error instanceof Error ? query.error.message : 'Could not load presets.'}
                    onRetry={() => query.refetch()}
                  />
                )}
                {!query.isLoading && !query.isError && items.length === 0 && (
                  <Card>
                    <CardContent>
                      <EmptyState
                        icon={Cpu}
                        title={`No ${k.label.toLowerCase()} yet`}
                        description="Create presets via the API or install a package that bundles them."
                      />
                    </CardContent>
                  </Card>
                )}
                <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                  {items.map((preset) => (
                    <Card key={preset.id}>
                      <CardHeader>
                        <div className="flex items-start justify-between gap-2">
                          <CardTitle className="text-base">{preset.name}</CardTitle>
                          {preset.official && <Badge variant="success">Official</Badge>}
                        </div>
                        <CardDescription className="line-clamp-2">{preset.description || 'No description.'}</CardDescription>
                      </CardHeader>
                      <CardContent className="flex flex-wrap gap-1.5">
                        <Badge variant="secondary">v{preset.latest_version || '—'}</Badge>
                        <Badge variant="outline">{preset.kind}</Badge>
                      </CardContent>
                    </Card>
                  ))}
                </div>
              </TabsContent>
            ))}
          </Tabs>
        </div>
      </Layout>
    </Protected>
  );
}
