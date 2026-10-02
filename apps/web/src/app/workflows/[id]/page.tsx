'use client';

import * as React from 'react';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { Button } from '@/components/ui/button';
import { StatusBadge } from '@/components/ui/status';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { ConfirmDialog } from '@/components/ui/dialog';
import { Drawer } from '@/components/ui/drawer';
import { PermissionGate } from '@/components/PermissionGate';
import { usePermission } from '@/lib/permissions';
import { useToast } from '@/components/ui/toast';
import { toUserMessage, ApiError } from '@/lib/api';
import { PageLoading } from '@/components/ui/loading';
import { ErrorState } from '@/components/ui/states';
import { useWorkflow, useWorkflowMutations } from '@/features/workflows/workflows-api';
import { VersionHistory, RunHistory } from '@/components/workflows/History';
import { WorkflowCanvas } from '@/components/workflows/WorkflowCanvas';
import { useWorkflowEditor } from '@/features/workflows/use-workflow-editor';
import { downloadEnvelope } from '@/features/workflows/serialize';
import { emptyDefinition, type WorkflowVersionRecord } from '@/features/workflows/types';
import { Pencil, Play, Copy, Trash2, Download, Rocket, PauseCircle } from 'lucide-react';

export default function WorkflowDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const { workflow, isLoading, error, refetch } = useWorkflow(id);
  const mutations = useWorkflowMutations();
  const { toast } = useToast();
  const router = useRouter();
  const [confirmDelete, setConfirmDelete] = React.useState(false);
  const [preview, setPreview] = React.useState<WorkflowVersionRecord | null>(null);
  const [restoreTarget, setRestoreTarget] = React.useState<WorkflowVersionRecord | null>(null);
  const canUpdate = usePermission('workflow:update');

  const previewEditor = useWorkflowEditor({
    initial: preview?.definition ?? emptyDefinition(),
  });
  React.useEffect(() => {
    if (preview) previewEditor.load(preview.definition);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [preview?.id]);

  if (isLoading) {
    return (
      <Protected>
        <Layout><PageLoading label="Loading workflow…" /></Layout>
      </Protected>
    );
  }

  if (error || !workflow) {
    return (
      <Protected>
        <Layout>
          <ErrorState title="Workflow not found" description={error ?? 'This workflow does not exist or you lack access.'} onRetry={() => refetch()} />
        </Layout>
      </Protected>
    );
  }

  const run = async (fn: Promise<unknown>, ok: string, opts?: { honest501?: boolean }) => {
    try {
      await fn;
      toast({ kind: 'success', title: ok });
    } catch (e) {
      if (opts?.honest501 && e instanceof ApiError && e.status === 501) {
        toast({ kind: 'info', title: 'Execution engine not yet available', description: 'Authoring is complete; runs ship in a later phase. Nothing was faked.' });
      } else {
        toast({ kind: 'error', title: 'Action failed', description: toUserMessage(e) });
      }
    }
  };

  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader
            title={workflow.name}
            description={workflow.description || 'No description.'}
            breadcrumbs={[{ label: 'Home', href: '/' }, { label: 'Workflows', href: '/workflows' }, { label: workflow.name }]}
            actions={
              <>
                <StatusBadge status={workflow.status} />
                <PermissionGate permission="workflow:update">
                  <Link href={`/workflows/${workflow.id}/edit`}>
                    <Button variant="outline"><Pencil className="mr-2 h-4 w-4" />Open builder</Button>
                  </Link>
                </PermissionGate>
                <PermissionGate permission="workflow:execute">
                  <Button
                    onClick={() => run(mutations.execute.mutateAsync(workflow.id), 'Run started', { honest501: true })}
                    disabled={workflow.status !== 'active'}
                    title={workflow.status !== 'active' ? 'Publish the workflow before running' : 'Start a run'}
                  >
                    <Play className="mr-2 h-4 w-4" />Run
                  </Button>
                </PermissionGate>
              </>
            }
          />

          <Card>
            <CardHeader>
              <CardTitle>Overview</CardTitle>
              <CardDescription>
                Latest version {workflow.latest_version?.version ?? '—'} · {workflow.version_count} version{workflow.version_count === 1 ? '' : 's'} ·
                slug <span className="oa-code">{workflow.slug}</span>
                {(workflow.tags ?? []).length > 0 && (
                  <span className="ml-2 inline-flex flex-wrap gap-1">
                    {(workflow.tags ?? []).map((t) => (
                      <span key={t} className="rounded-full bg-muted px-2 py-0.5 text-[11px]">{t}</span>
                    ))}
                  </span>
                )}
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-wrap gap-2">
              <PermissionGate permission="workflow:update">
                {workflow.status !== 'active' ? (
                  <Button
                    variant="outline"
                    loading={mutations.publish.isPending}
                    onClick={() => run(mutations.publish.mutateAsync(workflow.id), `Published ${workflow.latest_version?.version ?? ''}`)}
                  >
                    <Rocket className="mr-2 h-4 w-4" />Publish
                  </Button>
                ) : (
                  <Button variant="outline" onClick={() => run(mutations.unpublish.mutateAsync(workflow.id), 'Returned to draft')}>
                    <PauseCircle className="mr-2 h-4 w-4" />Unpublish
                  </Button>
                )}
              </PermissionGate>
              <PermissionGate permission="workflow:create">
                <Button
                  variant="outline"
                  onClick={() => run(
                    mutations.duplicate.mutateAsync(workflow.id).then((copy) => router.push(`/workflows/${copy.id}`)),
                    'Duplicated',
                  )}
                >
                  <Copy className="mr-2 h-4 w-4" />Duplicate
                </Button>
              </PermissionGate>
              <Button
                variant="outline"
                onClick={() => workflow.latest_version && downloadEnvelope(
                  { name: workflow.name, slug: workflow.slug, description: workflow.description, tags: workflow.tags },
                  workflow.latest_version.definition,
                )}
                disabled={!workflow.latest_version}
              >
                <Download className="mr-2 h-4 w-4" />Export JSON
              </Button>
              <PermissionGate permission="workflow:delete">
                <Button variant="destructive" onClick={() => setConfirmDelete(true)}>
                  <Trash2 className="mr-2 h-4 w-4" />Delete
                </Button>
              </PermissionGate>
            </CardContent>
          </Card>

          <Tabs defaultValue="versions">
            <TabsList aria-label="Workflow sections">
              <TabsTrigger value="versions">Versions</TabsTrigger>
              <TabsTrigger value="runs">Runs</TabsTrigger>
              <TabsTrigger value="graph">Graph preview</TabsTrigger>
            </TabsList>
            <TabsContent value="versions">
              <VersionHistory
                workflowId={workflow.id}
                currentVersion={workflow.latest_version?.version}
                onPreview={setPreview}
                onRestore={canUpdate ? setRestoreTarget : undefined}
                restoring={mutations.restore.isPending}
              />
            </TabsContent>
            <TabsContent value="runs">
              <RunHistory workflowId={workflow.id} />
            </TabsContent>
            <TabsContent value="graph">
              {workflow.latest_version ? (
                <WorkflowCanvas editor={previewEditor} readOnly />
              ) : (
                <p className="oa-caption">No versions yet.</p>
              )}
            </TabsContent>
          </Tabs>
        </div>
      </Layout>

      <Drawer open={!!preview} onClose={() => setPreview(null)} title={`Version ${preview?.version ?? ''}`} description="Immutable snapshot — open the builder to make changes.">
        {preview && (
          <div className="space-y-3">
            <p className="text-sm text-muted-foreground">
              Status <StatusBadge status={preview.status === 'published' ? 'published' : 'draft'} /> ·{' '}
              {preview.definition.triggers.length} triggers · {preview.definition.nodes.length} nodes ·{' '}
              {preview.definition.edges.length} edges
            </p>
            <pre className="max-h-[60vh] overflow-auto rounded-md border bg-muted/40 p-3 text-xs" aria-label="Version definition JSON">
              {JSON.stringify(preview.definition, null, 2)}
            </pre>
            <PermissionGate permission="workflow:update">
              <Link href={`/workflows/${workflow.id}/edit`}>
                <Button variant="outline"><Pencil className="mr-2 h-4 w-4" />Open in builder</Button>
              </Link>
            </PermissionGate>
          </div>
        )}
      </Drawer>

      <ConfirmDialog
        open={confirmDelete}
        onClose={() => setConfirmDelete(false)}
        onConfirm={async () => {
          await run(mutations.remove.mutateAsync(workflow.id), 'Workflow deleted');
          router.push('/workflows');
        }}
        title={`Delete “${workflow.name}”?`}
        description="Versions will be archived from this list. Past executions are preserved."
        confirmLabel="Delete"
        danger
      />

      <ConfirmDialog
        open={!!restoreTarget}
        onClose={() => setRestoreTarget(null)}
        onConfirm={async () => {
          if (!restoreTarget) return;
          await run(
            mutations.restore.mutateAsync({ id: workflow.id, version: restoreTarget.version }),
            `Restored ${restoreTarget.version} as a new draft`,
          );
          setRestoreTarget(null);
        }}
        title={`Restore ${restoreTarget?.version ?? ''} as a new draft?`}
        description="History is never rewritten — the snapshot is copied into a fresh version."
        confirmLabel="Restore as draft"
      />
    </Protected>
  );
}
