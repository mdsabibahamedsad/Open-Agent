'use client';

import * as React from 'react';
import { useParams } from 'next/navigation';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { Button } from '@/components/ui/button';
import { StatusBadge } from '@/components/ui/status';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { PermissionGate } from '@/components/PermissionGate';
import {
  useOrchestration,
  useOrchestrationAgents,
  useOrchestrationEvents,
  useOrchestrationMessages,
  useOrchestrationMutations,
  useOrchestrationTasks,
  useTaskMutations,
} from '@/features/orchestrations/api';
import { TaskGraph } from '@/features/orchestrations/TaskGraph';
import { AgentTree } from '@/features/orchestrations/AgentTree';
import {
  DelegationPanel,
  HandoffPanel,
  ReviewPanel,
} from '@/features/management/RunManagement';
import { useRunStream } from '@/features/management/useRunStream';
import { useOrganization } from '@/context/OrganizationContext';
import { useManagementMutation } from '@/features/management/api';

export default function OrchestrationDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const { run, isLoading, error, refetch } = useOrchestration(id);
  const { tasks } = useOrchestrationTasks(id);
  const { groups } = useOrchestrationAgents(id);
  const { messages } = useOrchestrationMessages(id);
  const { events } = useOrchestrationEvents(id);
  const mutations = useOrchestrationMutations(id);
  const taskMutations = useTaskMutations(id);
  const { currentOrgId } = useOrganization();
  const { connected, error: streamError } = useRunStream(currentOrgId, id);
  const escalateTask = useManagementMutation('/escalations');
  const [selectedTask, setSelectedTask] = React.useState<string | null>(null);
  const [actionError, setActionError] = React.useState<string | null>(null);

  const selected = tasks.find((t) => t.id === selectedTask) ?? null;
  const failures = tasks.filter((t) => t.status === 'failed' || t.status === 'timed_out');
  const budget = (run?.budget ?? {}) as Record<string, number>;
  const usage = (run?.usage ?? {}) as Record<string, number>;

  const act = async (fn: () => Promise<unknown>) => {
    setActionError(null);
    try {
      await fn();
      void refetch();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Action failed.');
    }
  };

  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader
            title={run ? run.objective : 'Orchestration'}
            description={run ? `Status: ${run.status}` : 'Loading orchestration…'}
            breadcrumbs={[
              { label: 'Home', href: '/' },
              { label: 'Orchestrations', href: '/orchestrations' },
              { label: run ? run.objective.slice(0, 40) : id },
            ]}
            actions={
              run && (
                <div className="flex flex-wrap gap-2">
                  {run.status === 'ready' && (
                    <PermissionGate permission="agent:run">
                      <Button onClick={() => void act(() => mutations.start.mutateAsync())}>
                        Start
                      </Button>
                    </PermissionGate>
                  )}
                  {run.status === 'running' && (
                    <PermissionGate permission="agent:run">
                      <Button variant="outline" onClick={() => void act(() => mutations.pause.mutateAsync())}>
                        Pause
                      </Button>
                    </PermissionGate>
                  )}
                  {run.status === 'paused' && (
                    <PermissionGate permission="agent:run">
                      <Button onClick={() => void act(() => mutations.resume.mutateAsync())}>
                        Resume
                      </Button>
                    </PermissionGate>
                  )}
                  {!['succeeded', 'failed', 'cancelled', 'timed_out'].includes(run.status) && (
                    <PermissionGate permission="agent:run">
                      <Button
                        variant="destructive"
                        onClick={() => void act(() => mutations.cancel.mutateAsync())}
                      >
                        Cancel
                      </Button>
                    </PermissionGate>
                  )}
                </div>
              )
            }
          />
          {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
          {actionError && (
            <p role="alert" className="text-sm text-destructive">
              {actionError}
            </p>
          )}
          {run && (
            <>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <Card>
                  <CardContent className="pt-6">
                    <p className="text-xs uppercase text-muted-foreground">Status</p>
                    <StatusBadge status={run.status} />
                  </CardContent>
                </Card>
                <Card>
                  <CardContent className="pt-6">
                    <p className="text-xs uppercase text-muted-foreground">Progress</p>
                    <p className="text-lg font-semibold">
                      {tasks.filter((t) => t.status === 'succeeded').length}/{tasks.length} tasks
                    </p>
                  </CardContent>
                </Card>
                <Card>
                  <CardContent className="pt-6">
                    <p className="text-xs uppercase text-muted-foreground">Budget</p>
                    <p className="text-sm">
                      tokens {(usage.tokens ?? 0) as number}/{(budget.max_total_tokens ?? '—') as number}
                    </p>
                    <p className="text-sm">
                      cost {(usage.cost ?? 0) as number}/{(budget.max_total_cost ?? '—') as number}
                    </p>
                  </CardContent>
                </Card>
                <Card>
                  <CardContent className="pt-6">
                    <p className="text-xs uppercase text-muted-foreground">Elapsed</p>
                    <p className="text-sm">
                      {run.started_at ? new Date(run.started_at).toLocaleString() : '—'}
                      {run.completed_at ? ` → ${new Date(run.completed_at).toLocaleString()}` : ''}
                    </p>
                  </CardContent>
                </Card>
              </div>
              <Tabs defaultValue="graph">
                <TabsList>
                  <TabsTrigger value="graph">Task Graph</TabsTrigger>
                  <TabsTrigger value="agents">Agent Tree</TabsTrigger>
                  <TabsTrigger value="delegations">Delegations</TabsTrigger>
                  <TabsTrigger value="handoffs">Handoffs</TabsTrigger>
                  <TabsTrigger value="timeline">Messages</TabsTrigger>
                  <TabsTrigger value="events">Events</TabsTrigger>
                  <TabsTrigger value="failures">Failures ({failures.length})</TabsTrigger>
                  <TabsTrigger value="result">Final Result</TabsTrigger>
                </TabsList>
                <TabsContent value="graph">
                  <TaskGraph tasks={tasks} selectedId={selectedTask} onSelect={setSelectedTask} />
                </TabsContent>
                <TabsContent value="agents">
                  <AgentTree tasks={tasks} groups={groups} />
                </TabsContent>
                <TabsContent value="delegations">
                  <DelegationPanel runId={id} onChanged={() => refetch()} />
                </TabsContent>
                <TabsContent value="handoffs">
                  <HandoffPanel runId={id} onChanged={() => refetch()} />
                </TabsContent>
                <TabsContent value="timeline">
                  <ul className="space-y-2">
                    {messages.length === 0 && (
                      <li className="text-sm text-muted-foreground">No messages yet.</li>
                    )}
                    {messages.map((m) => (
                      <li key={m.id} className="rounded border p-2 text-sm">
                        <span className="font-medium">{m.message_type}</span>{' '}
                        <span className="text-muted-foreground">
                          {new Date(m.created_at).toLocaleTimeString()}
                        </span>
                        <pre className="mt-1 overflow-auto text-xs">
                          {JSON.stringify(m.payload, null, 2).slice(0, 2000)}
                        </pre>
                      </li>
                    ))}
                  </ul>
                </TabsContent>
                <TabsContent value="events">
                  <ul className="space-y-1">
                    {events.length === 0 && (
                      <li className="text-sm text-muted-foreground">No events yet.</li>
                    )}
                    {events.map((e) => (
                      <li key={e.id} className="rounded border p-2 text-sm">
                        <span className="font-medium">{e.event_type}</span>{' '}
                        <span className="text-muted-foreground">
                          {new Date(e.created_at).toLocaleTimeString()}
                        </span>
                      </li>
                    ))}
                  </ul>
                </TabsContent>
                <TabsContent value="failures">
                  <ul className="space-y-2">
                    {failures.length === 0 && (
                      <li className="text-sm text-muted-foreground">No failures.</li>
                    )}
                    {failures.map((t) => (
                      <li key={t.id} className="rounded border p-3 text-sm">
                        <p className="font-medium">{t.title}</p>
                        <p className="text-muted-foreground">{t.error ?? 'Failed'}</p>
                        <div className="mt-2 flex gap-2">
                          <PermissionGate permission="agent:run">
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => void act(() => taskMutations.retry.mutateAsync(t.id))}
                            >
                              Retry
                            </Button>
                          </PermissionGate>
                        </div>
                      </li>
                    ))}
                  </ul>
                </TabsContent>
                <TabsContent value="result">
                  <pre className="overflow-auto rounded border p-3 text-xs">
                    {JSON.stringify(run.final_result ?? { status: run.status }, null, 2)}
                  </pre>
                </TabsContent>
              </Tabs>
              {selected && (
                <Card>
                  <CardHeader>
                    <CardTitle>Selected task</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <p className="text-sm font-medium">{selected.title}</p>
                    <p className="text-xs text-muted-foreground">
                      {selected.external_task_id} · {selected.status} · depth {selected.depth} ·
                      retries {selected.retry_count}
                    </p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      live: {connected ? 'connected' : 'polling'}
                      {streamError ? ` (${streamError})` : ''}
                    </p>
                    {selected.output && (
                      <pre className="mt-2 overflow-auto text-xs">
                        {JSON.stringify(selected.output, null, 2).slice(0, 4000)}
                      </pre>
                    )}
                    <div className="mt-2">
                      <h3 className="text-sm font-semibold">Reviews</h3>
                      <ReviewPanel runId={id} taskId={selected.id} onChanged={() => refetch()} />
                    </div>
                    <div className="mt-2">
                      <PermissionGate permission="agent:create">
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() =>
                            void act(() =>
                              escalateTask.mutateAsync({
                                run_id: id,
                                task_id: selected.id,
                                trigger: 'blocked',
                                reason: `Manual escalation from workspace: ${selected.title}`,
                              }),
                            )
                          }
                        >
                          Escalate task
                        </Button>
                      </PermissionGate>
                    </div>
                  </CardContent>
                </Card>
              )}
            </>
          )}
        </div>
      </Layout>
    </Protected>
  );
}
