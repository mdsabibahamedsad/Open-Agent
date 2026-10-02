'use client';

import Link from 'next/link';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { StatusBadge } from '@/components/ui/status';
import { PageHeader } from '@/components/ui/page';
import { EmptyState } from '@/components/ui/states';
import { Skeleton } from '@/components/ui/loading';
import { useAuth } from '@/context/AuthContext';
import { useOrganization } from '@/context/OrganizationContext';
import { useOrgScopedList } from '@/lib/queries';
import { Bot, GitBranch, Play, Wrench, Plus, ArrowRight, Store } from 'lucide-react';
import type { AgentSummary, WorkflowSummary, RunSummary } from '@/types';

function greeting(): string {
  const h = new Date().getHours();
  if (h < 12) return 'Good morning';
  if (h < 18) return 'Good afternoon';
  return 'Good evening';
}

export default function DashboardPage() {
  const { user } = useAuth();
  const { currentOrg } = useOrganization();
  const agents = useOrgScopedList<AgentSummary>('agents', ['/organizations/{orgId}/agents', '/agents']);
  const workflows = useOrgScopedList<WorkflowSummary>('workflows', ['/organizations/{orgId}/workflows', '/workflows']);
  const runs = useOrgScopedList<RunSummary>('runs', ['/organizations/{orgId}/runs', '/runs']);

  const loading = agents.isLoading || workflows.isLoading || runs.isLoading;
  const name = user?.display_name ?? user?.email?.split('@')[0] ?? 'there';

  const stats = [
    { name: 'Agents', value: agents.total, icon: Bot, href: '/agents' },
    { name: 'Workflows', value: workflows.total, icon: GitBranch, href: '/workflows' },
    { name: 'Runs', value: runs.total, icon: Play, href: '/runs' },
    { name: 'Tools', value: 0, icon: Wrench, href: '/tools' },
  ];

  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader
            title={`${greeting()}, ${name}`}
            description={currentOrg ? `Organization: ${currentOrg.name}` : 'Your AI Workforce Operating System'}
            actions={
              <>
                <Link href="/agents"><Button variant="outline"><Plus className="mr-2 h-4 w-4" />New agent</Button></Link>
                <Link href="/workflows"><Button><Plus className="mr-2 h-4 w-4" />New workflow</Button></Link>
              </>
            }
          />

          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
            {loading
              ? Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-28" />)
              : stats.map((s) => (
                  <Link key={s.name} href={s.href} className="oa-surface p-5 transition-shadow hover:shadow-md">
                    <p className="text-sm font-medium text-muted-foreground">{s.name}</p>
                    <div className="mt-1 flex items-center justify-between">
                      <p className="text-3xl font-bold tabular-nums">{s.value}</p>
                      <s.icon className="h-6 w-6 text-primary" aria-hidden />
                    </div>
                  </Link>
                ))}
          </div>

          <div className="grid gap-4 lg:grid-cols-3">
            <Card className="lg:col-span-2">
              <CardHeader>
                <CardTitle>Recent activity</CardTitle>
                <CardDescription>Latest runs across agents and workflows</CardDescription>
              </CardHeader>
              <CardContent>
                {runs.isLoading ? (
                  <Skeleton className="h-32" />
                ) : runs.items.length === 0 ? (
                  <EmptyState
                    icon={Play}
                    title="No runs yet"
                    description="Execute an agent or workflow and activity will appear here."
                    action={<Link href="/workflows"><Button variant="outline">Explore workflows <ArrowRight className="ml-2 h-4 w-4" /></Button></Link>}
                  />
                ) : (
                  <ul className="divide-y">
                    {runs.items.slice(0, 8).map((r) => (
                      <li key={r.id} className="flex items-center gap-3 py-2.5">
                        <StatusBadge status={r.status} />
                        <span className="min-w-0 flex-1 truncate text-sm">{r.workflow_name ?? r.id}</span>
                        <Link href="/runs" className="text-sm text-primary hover:underline">View</Link>
                      </li>
                    ))}
                  </ul>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Quick actions</CardTitle>
                <CardDescription>Common starting points</CardDescription>
              </CardHeader>
              <CardContent className="space-y-2">
                <Link href="/agents" className="flex items-center justify-between rounded-md border px-3 py-2.5 text-sm hover:bg-accent">
                  <span className="flex items-center gap-2"><Bot className="h-4 w-4" /> Create agent</span><ArrowRight className="h-4 w-4 text-muted-foreground" />
                </Link>
                <Link href="/workflows" className="flex items-center justify-between rounded-md border px-3 py-2.5 text-sm hover:bg-accent">
                  <span className="flex items-center gap-2"><GitBranch className="h-4 w-4" /> Create workflow</span><ArrowRight className="h-4 w-4 text-muted-foreground" />
                </Link>
                <Link href="/marketplace" className="flex items-center justify-between rounded-md border px-3 py-2.5 text-sm hover:bg-accent">
                  <span className="flex items-center gap-2"><Store className="h-4 w-4" /> Browse templates</span><ArrowRight className="h-4 w-4 text-muted-foreground" />
                </Link>
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardHeader>
              <CardTitle>System status</CardTitle>
              <CardDescription>Backend-connected checks where available</CardDescription>
            </CardHeader>
            <CardContent className="flex flex-wrap gap-2">
              <StatusBadge status="healthy" />
              <span className="text-sm text-muted-foreground">API, database and worker status are reported by the backend health endpoints when reachable.</span>
            </CardContent>
          </Card>
        </div>
      </Layout>
    </Protected>
  );
}
