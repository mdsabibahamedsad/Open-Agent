'use client';

import * as React from 'react';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { StatusBadge } from '@/components/ui/status';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { DataTable, Column } from '@/components/ui/table';
import { EmptyState } from '@/components/ui/states';
import { PageLoading } from '@/components/ui/loading';
import { ConfirmDialog } from '@/components/ui/dialog';
import { PermissionGate } from '@/components/PermissionGate';
import { useAuth } from '@/context/AuthContext';
import { useOrganization } from '@/context/OrganizationContext';
import { useToast } from '@/components/ui/toast';
import { useExecution } from '@/hooks/useExecution';
import { useWorkflowVersions } from '@/features/workflows/workflows-api';
import { toUserMessage } from '@/lib/api';
import { cn } from '@/lib/utils';
import { Play, PauseCircle, RotateCcw, Trash2, Download, ExternalLink, RefreshCw } from 'lucide-react';

export default function ExecutionDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const { toast } = useToast();
  const { currentOrgId } = useOrganization();
  const executionId = params.id;

  const { execution, isLoading, error, refetch } = useExecution(executionId, currentOrgId);

  const [confirmDelete, setConfirmDelete] = React.useState(false);
  const [previewVersion, setPreviewVersion] = React.useState<string | null>(null);

  if (isLoading) {
    return (
      <Protected>
        <Layout>
          <PageLoading label="Loading execution…" />
        </Layout>
      </Protected>
    );
  }

  if (error || !execution) {
    return (
      <Protected>
        <Layout>
          <div className="oa-page">
            <div className="rounded-lg border p-8 text-center" role="alert">
              <h2 className="font-semibold">Execution not found</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                This execution does not exist or you lack access.
              </p>
              <Button variant="outline" onClick={() => router.push('/runs')} className="mt-4">
                Back to Runs
              </Button>
            </div>
          </div>
        </Layout>
      </Protected>
    );
  }

  const canUpdate = execution.status !== 'completed' && execution.status !== 'failed' && execution.status !== 'cancelled' && execution.status !== 'timed_out';

  const handleRetry = async () => {
    try {
      await fetch(`/api/organizations/${execution.organization_id}/workflows/${execution.workflow_id}/executions/${execution.id}/retry`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode: 'full' }),
      });
      toast({ kind: 'success', title: 'Retry queued' });
      router.refresh();
    } catch (e) {
      toast({ kind: 'error', title: 'Retry failed', description: toUserMessage(e) });
    }
  };

  const handleCancel = async () => {
    try {
      await fetch(`/api/organizations/${execution.organization_id}/workflows/${execution.workflow_id}/executions/${execution.id}/cancel`, {
        method: 'POST',
      });
      toast({ kind: 'success', title: 'Execution cancelled' });
      router.refresh();
    } catch (e) {
      toast({ kind: 'error', title: 'Cancel failed', description: toUserMessage(e) });
    }
  };

  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader
            title={`Execution ${execution.id.slice(0, 8)}`}
            description={`Workflow: ${execution.workflow_name ?? 'Unknown'} • ${execution.trigger_type}`}
            breadcrumbs={[{ label: 'Home', href: '/' }, { label: 'Runs', href: '/runs' }, { label: execution.id.slice(0, 8) }]}
            actions={
              <>
                <PermissionGate permission="workflow:execute">
                  <Button
                    variant={execution.status === 'running' ? 'outline' : 'default'}
                    onClick={() => router.push(`/runs/${execution.id}`)}
                    disabled={execution.status === 'running'}
                  >
                    <RotateCcw className="mr-1.5 h-3.5 w-3.5" /> Retry
                  </Button>
                </PermissionGate>
                <PermissionGate permission="execution:cancel">
                  <Button
                    variant="outline"
                    onClick={() => setConfirmDelete(true)}
                    disabled={!['queued', 'running', 'waiting', 'paused'].includes(execution.status)}
                  >
                    <Trash2 className="mr-1.5 h-3.5 w-3.5" /> Cancel
                  </Button>
                </PermissionGate>
                <Button
                  variant="outline"
                  onClick={() => window.open(`/api/organizations/${execution.organization_id}/workflows/${execution.workflow_id}/executions/${execution.id}/export`, '_blank')}
                >
                  <Download className="mr-1.5 h-3.5 w-3.5" /> Export
                </Button>
              </>
            }
          />

          <div className="flex items-center gap-2 mb-4">
            <StatusBadge status={execution.status} />
            <span className="text-xs text-muted-foreground">
              {execution.trigger_type} • {execution.started_at ? new Date(execution.started_at).toLocaleString() : 'Not started'}
            </span>
            {execution.completed_at && (
              <span className="text-xs text-muted-foreground">
                Completed {new Date(execution.completed_at).toLocaleString()}
              </span>
            )}
            {execution.error_message && (
              <span className="text-xs text-destructive" role="alert">
                {execution.error_code}: {execution.error_message}
              </span>
            )}
          </div>

          <Tabs defaultValue="overview" className="mt-4">
            <TabsList aria-label="Execution sections">
              <TabsTrigger value="overview">Overview</TabsTrigger>
              <TabsTrigger value="nodes">Node Runs</TabsTrigger>
              <TabsTrigger value="events">Events</TabsTrigger>
              <TabsTrigger value="logs">Logs</TabsTrigger>
            </TabsList>

            <TabsContent value="overview">
              <div className="grid gap-4 mt-4">
                <Card>
                  <CardHeader>
                    <CardTitle>Execution Info</CardTitle>
                    <CardDescription>Core execution metadata</CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    <dl className="grid gap-2 sm:grid-cols-2 text-sm">
                      <div><dt className="text-muted-foreground">Execution ID</dt><dd className="oa-code">{execution.id}</dd></div>
                      <div><dt className="text-muted-foreground">Workflow</dt><dd>{execution.workflow_name ?? '—'}</dd></div>
                      <div><dt className="text-muted-foreground">Status</dt><dd><StatusBadge status={execution.status} /></dd></div>
                      <div><dt className="text-muted-foreground">Trigger</dt><dd className="capitalize">{execution.trigger_type}</dd></div>
                      <div><dt className="text-muted-foreground">Started</dt><dd>{execution.started_at ? new Date(execution.started_at).toLocaleString() : '—'}</dd></div>
                      <div><dt className="text-muted-foreground">Completed</dt><dd>{execution.completed_at ? new Date(execution.completed_at).toLocaleString() : '—'}</dd></div>
                      <div><dt className="text-muted-foreground">Duration</dt><dd>{execution.started_at && execution.completed_at ? `${Math.round((new Date(execution.completed_at).getTime() - new Date(execution.started_at).getTime()) / 1000)}s` : '—'}</dd></div>
                      {execution.error_message && (
                        <>
                          <dt className="text-muted-foreground">Error</dt>
                          <dd className="text-destructive">{execution.error_code}: {execution.error_message}</dd>
                        </>
                      )}
                    </dl>
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader>
                    <CardTitle>Node Summary</CardTitle>
                    <CardDescription>Execution status by node</CardDescription>
                  </CardHeader>
                  <CardContent>
                    {/* Node runs would be displayed here */}
                    <p className="text-sm text-muted-foreground">Node run details available in the Node Runs tab</p>
                  </CardContent>
                </Card>
              </div>
            </TabsContent>

            <TabsContent value="nodes">
              <ExecutionNodeRuns executionId={execution.id} />
            </TabsContent>

            <TabsContent value="events">
              <ExecutionEvents executionId={execution.id} />
            </TabsContent>

            <TabsContent value="logs">
              <div className="rounded-lg border bg-muted/40 p-4 font-mono text-xs text-muted-foreground">
                <p>Log streaming will be available when the execution engine ships.</p>
                <p className="mt-2">For now, execution events are shown in the Events tab.</p>
              </div>
            </TabsContent>
          </Tabs>
        </div>
      </Layout>
    </Protected>
  );
}

function ExecutionNodeRuns({ executionId }: { executionId: string }) {
  // Would fetch node runs from API
  return (
    <div className="rounded-lg border bg-card p-4 text-center text-sm text-muted-foreground">
      Node run details will be displayed here once the execution engine is running.
    </div>
  );
}

function ExecutionEvents({ executionId }: { executionId: string }) {
  // Would fetch events from API
  return (
    <div className="rounded-lg border bg-card p-4 text-center text-sm text-muted-foreground">
      Execution events will be displayed here once the execution engine is running.
    </div>
  );
}

