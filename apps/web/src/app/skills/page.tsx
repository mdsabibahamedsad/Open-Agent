'use client';

import * as React from 'react';
import Link from 'next/link';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { Input } from '@/components/ui/input';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { EmptyState, ErrorState } from '@/components/ui/states';
import { useOrganization } from '@/context/OrganizationContext';
import { useSearchParamsState } from '@/lib/queries';
import { skillsApi, SkillSummary } from '@/lib/packages';
import { TrustBadge } from '@/features/packages/ui';
import { Search, Sparkles } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';

export default function SkillsPage() {
  const { currentOrgId } = useOrganization();
  const [q, setQ] = React.useState('');
  const debounced = useSearchParamsState(q);

  const query = useQuery({
    queryKey: ['skills', currentOrgId, debounced],
    queryFn: () => skillsApi.list(currentOrgId!, debounced ? { search: debounced } : undefined),
    enabled: Boolean(currentOrgId),
    staleTime: 30_000,
  });
  const items: SkillSummary[] = (query.data?.data as SkillSummary[]) ?? [];

  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader
            title="Skills"
            description="Reusable capabilities you can attach to agents, teams, workflows and workforces. Skills never bypass tool, approval or sandbox policy."
            breadcrumbs={[{ label: 'Home', href: '/' }, { label: 'Skills' }]}
          />
          <div className="relative w-full max-w-sm">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
            <Input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search skills…"
              aria-label="Search skills"
              className="pl-9"
            />
          </div>
          {query.isLoading && <p className="text-sm text-muted-foreground">Loading skills…</p>}
          {query.isError && (
            <ErrorState
              title="Skills unavailable"
              description={query.error instanceof Error ? query.error.message : 'Could not load skills.'}
              onRetry={() => query.refetch()}
            />
          )}
          {!query.isLoading && !query.isError && items.length === 0 && (
            <Card>
              <CardContent>
                <EmptyState
                  icon={Sparkles}
                  title="No skills yet"
                  description="Create skills via the API or install a workforce package that bundles them."
                />
              </CardContent>
            </Card>
          )}
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {items.map((skill) => (
              <Link key={skill.id} href={`/skills/${skill.id}`} className="block h-full" aria-label={`Open ${skill.name}`}>
                <Card className="flex h-full flex-col transition-colors hover:border-primary/50">
                  <CardHeader>
                    <div className="flex items-start justify-between gap-2">
                      <CardTitle className="text-base">{skill.name}</CardTitle>
                      <TrustBadge trust={skill.trust} official={skill.official} />
                    </div>
                    <CardDescription className="line-clamp-2">{skill.description || 'No description.'}</CardDescription>
                  </CardHeader>
                  <CardContent className="mt-auto flex flex-wrap gap-1.5">
                    <Badge variant="secondary">v{skill.latest_version || '—'}</Badge>
                    <Badge variant="outline">{skill.status}</Badge>
                  </CardContent>
                </Card>
              </Link>
            ))}
          </div>
        </div>
      </Layout>
    </Protected>
  );
}
