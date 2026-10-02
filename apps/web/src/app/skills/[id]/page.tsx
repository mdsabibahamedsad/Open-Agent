'use client';

import * as React from 'react';
import { useParams } from 'next/navigation';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { EmptyState, ErrorState } from '@/components/ui/states';
import { useOrganization } from '@/context/OrganizationContext';
import { skillsApi } from '@/lib/packages';
import { TrustBadge } from '@/features/packages/ui';
import { toUserMessage } from '@/lib/api';
import { useQuery } from '@tanstack/react-query';

export default function SkillDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const { currentOrgId } = useOrganization();
  const [targetType, setTargetType] = React.useState<'agent' | 'workflow'>('agent');
  const [targetId, setTargetId] = React.useState('');
  const [message, setMessage] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  const query = useQuery({
    queryKey: ['skill', currentOrgId, id],
    queryFn: () => skillsApi.get(currentOrgId!, id),
    enabled: Boolean(currentOrgId && id),
  });
  const skill = query.data;

  const attach = async () => {
    if (!currentOrgId || !targetId) return;
    setBusy(true);
    setMessage(null);
    try {
      await skillsApi.attach(currentOrgId, id, targetType, targetId);
      setMessage(`Attached. A new draft ${targetType} version was created — the original was not mutated.`);
    } catch (e: unknown) {
      setMessage(toUserMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          {query.isLoading && <p className="text-sm text-muted-foreground">Loading skill…</p>}
          {query.isError && (
            <ErrorState title="Skill unavailable" description="Could not load this skill." onRetry={() => query.refetch()} />
          )}
          {!query.isLoading && !query.isError && !skill && (
            <Card>
              <CardContent>
                <EmptyState title="Skill not found" description="This skill is not visible to your organization." />
              </CardContent>
            </Card>
          )}
          {skill && (
            <>
              <PageHeader
                title={skill.name}
                description={skill.description || 'No description.'}
                breadcrumbs={[{ label: 'Home', href: '/' }, { label: 'Skills', href: '/skills' }, { label: skill.name }]}
              />
              <div className="flex flex-wrap items-center gap-2">
                <TrustBadge trust={skill.trust} official={skill.official} />
                <Badge variant="secondary">v{skill.latest_version || '—'}</Badge>
                <Badge variant="outline">{skill.status}</Badge>
                <Badge variant="outline">{skill.visibility}</Badge>
              </div>
              <div className="grid gap-4 md:grid-cols-2">
                <Card>
                  <CardHeader>
                    <CardTitle className="text-base">Attach to agent or workflow</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-3 text-sm">
                    <p className="text-muted-foreground">
                      Attaching creates a new draft version of the target with this skill appended. Tool and
                      policy conflicts fail closed.
                    </p>
                    <div className="flex gap-2">
                      <select
                        aria-label="Target type"
                        className="rounded-md border border-input bg-background px-3 py-2"
                        value={targetType}
                        onChange={(e) => setTargetType(e.target.value as 'agent' | 'workflow')}
                      >
                        <option value="agent">Agent</option>
                        <option value="workflow">Workflow</option>
                      </select>
                      <Input
                        placeholder={`Target ${targetType} ID`}
                        aria-label="Target ID"
                        value={targetId}
                        onChange={(e) => setTargetId(e.target.value)}
                      />
                    </div>
                    <Button size="sm" onClick={attach} disabled={busy || !targetId}>
                      Attach skill
                    </Button>
                    {message && <p className="text-muted-foreground">{message}</p>}
                  </CardContent>
                </Card>
                <Card>
                  <CardHeader>
                    <CardTitle className="text-base">How skills work</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-1 text-sm text-muted-foreground">
                    <p>Skills compose: research + SEO + writing + fact-checking form review-safe pipelines.</p>
                    <p>Required tools and connectors are resolved through the existing Tool Runtime and connector policies.</p>
                    <p>Conflicting permissions or runtime requirements are detected before anything is attached.</p>
                  </CardContent>
                </Card>
              </div>
            </>
          )}
        </div>
      </Layout>
    </Protected>
  );
}
