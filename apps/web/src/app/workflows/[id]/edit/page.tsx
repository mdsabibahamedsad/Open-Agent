'use client';

import * as React from 'react';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { StatusBadge } from '@/components/ui/status';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { PermissionGate } from '@/components/PermissionGate';
import { useToast } from '@/components/ui/toast';
import { toUserMessage, ApiError } from '@/lib/api';
import { PageLoading } from '@/components/ui/loading';
import { ErrorState } from '@/components/ui/states';
import { useWorkflow, useWorkflowMutations } from '@/features/workflows/workflows-api';
import { useWorkflowEditor } from '@/features/workflows/use-workflow-editor';
import { WorkflowCanvas } from '@/components/workflows/WorkflowCanvas';
import { NodePalette } from '@/components/workflows/NodePalette';
import { Inspector } from '@/components/workflows/Inspector';
import { ValidationPanel } from '@/components/workflows/ValidationPanel';
import { downloadEnvelope, importDefinition } from '@/features/workflows/serialize';
import { emptyDefinition } from '@/features/workflows/types';
import { Dialog } from '@/components/ui/dialog';
import {
  ArrowLeft, Save, Rocket, Play, Undo2, Redo2, Download, Upload, CheckCircle2, XCircle,
} from 'lucide-react';
import { cn } from '@/lib/utils';

export default function WorkflowBuilderPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const { workflow, isLoading, error, refetch } = useWorkflow(id);
  const mutations = useWorkflowMutations();
  const { toast } = useToast();
  const router = useRouter();
  const fileRef = React.useRef<HTMLInputElement>(null);

  const baseline = workflow?.latest_version?.definition ?? null;
  const editor = useWorkflowEditor({
    initial: baseline ?? emptyDefinition(),
    draftKey: `oa:wf-draft:${id}`,
    baseline,
  });
  const [name, setName] = React.useState(workflow?.name ?? '');
  const [draftNotice, setDraftNotice] = React.useState(false);

  // Load saved definition when it arrives (once per version).
  const loadedVersion = React.useRef<string | null>(null);
  React.useEffect(() => {
    const v = workflow?.latest_version;
    if (!v || loadedVersion.current === `${workflow!.id}@${v.id}`) return;
    loadedVersion.current = `${workflow!.id}@${v.id}`;
    setName(workflow!.name);
    try {
      const raw = window.localStorage.getItem(`oa:wf-draft:${id}`);
      if (raw) {
        const draft = JSON.parse(raw);
        if (draft && draft.schema_version === '1.0' && JSON.stringify(draft) !== JSON.stringify(v.definition)) {
          setDraftNotice(true);
          return; // keep autosaved draft; user chooses below
        }
      }
    } catch {
      /* fall through to saved version */
    }
    editor.load(v.definition);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workflow?.latest_version?.id]);

  // Unsaved-changes guard.
  React.useEffect(() => {
    if (!editor.dirty) return;
    const onBefore = (e: BeforeUnloadEvent) => {
      e.preventDefault();
    };
    window.addEventListener('beforeunload', onBefore);
    return () => window.removeEventListener('beforeunload', onBefore);
  }, [editor.dirty]);

  if (isLoading) {
    return (
      <Protected>
        <Layout><PageLoading label="Loading builder…" /></Layout>
      </Protected>
    );
  }
  if (error || !workflow) {
    return (
      <Protected>
        <Layout>
          <ErrorState title="Workflow not found" description={error ?? 'No access.'} onRetry={() => refetch()} />
        </Layout>
      </Protected>
    );
  }

  const canEdit = workflow.status !== 'archived';
  const saving = mutations.update.isPending;
  const [saveState, setSaveState] = React.useState<'saved' | 'saving' | 'failed' | 'offline'>('saved');
  const [online, setOnline] = React.useState(true);
  const [conflict, setConflict] = React.useState(false);
  const [tags, setTags] = React.useState<string[]>(workflow.tags ?? []);
  const knownUpdatedAt = React.useRef<string | null>(workflow.updated_at ?? null);

  React.useEffect(() => {
    setTags(workflow.tags ?? []);
    knownUpdatedAt.current = workflow.updated_at ?? null;
  }, [workflow.id, workflow.updated_at]); // eslint-disable-line react-hooks/exhaustive-deps

  // Online / offline indicator (offline edits stay local + autosaved).
  React.useEffect(() => {
    const update = () => setOnline(navigator.onLine);
    update();
    window.addEventListener('online', update);
    window.addEventListener('offline', update);
    return () => {
      window.removeEventListener('online', update);
      window.removeEventListener('offline', update);
    };
  }, []);

  // Ctrl/Cmd+S saves from anywhere on the builder page.
  const saveRef = React.useRef<() => Promise<boolean>>(async () => false);
  const canEditRef = React.useRef(canEdit);
  canEditRef.current = canEdit;
  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
        e.preventDefault();
        if (canEditRef.current) void saveRef.current();
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, []);

  const doSave = async (definition = editor.definition, nextName = name): Promise<boolean> => {
    if (!navigator.onLine) {
      setSaveState('offline');
      toast({ kind: 'warning', title: 'Offline', description: 'Your changes are kept locally and autosaved. Save again when reconnected.' });
      return false;
    }
    setSaveState('saving');
    try {
      const saved = await mutations.update.mutateAsync({
        id: workflow.id,
        name: nextName.trim() !== workflow.name ? nextName.trim() : undefined,
        tags: JSON.stringify([...tags].sort()) !== JSON.stringify([...(workflow.tags ?? [])].sort()) ? tags : undefined,
        definition,
        expected_updated_at: knownUpdatedAt.current ?? undefined,
      });
      knownUpdatedAt.current = saved.updated_at ?? knownUpdatedAt.current;
      editor.markSaved(definition);
      setDraftNotice(false);
      setSaveState('saved');
      toast({ kind: 'success', title: 'Saved — new draft version created' });
      return true;
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        setConflict(true);
        setSaveState('saved');
      } else {
        setSaveState('failed');
        toast({ kind: 'error', title: 'Save failed', description: `${toUserMessage(e)} Your changes are still present locally.` });
      }
      return false;
    }
  };
  saveRef.current = doSave;

  const doPublish = async () => {
    if (editor.dirty) {
      const ok = await doSave();
      if (!ok) return;
    }
    if (!editor.validation.valid) {
      toast({ kind: 'error', title: 'Cannot publish', description: 'Fix validation errors first. Drafts may stay invalid; published versions may not.' });
      return;
    }
    try {
      await mutations.publish.mutateAsync(workflow.id);
      toast({ kind: 'success', title: 'Published' });
    } catch (e) {
      toast({ kind: 'error', title: 'Publish failed', description: toUserMessage(e) });
    }
  };

  const doRun = async () => {
    try {
      await mutations.execute.mutateAsync(workflow.id);
      toast({ kind: 'success', title: 'Run started' });
    } catch (e) {
      if (e instanceof ApiError && e.status === 501) {
        toast({ kind: 'info', title: 'Execution engine not yet available', description: 'Your graph is saved and validated. Runs ship in a later phase — nothing was faked.' });
      } else {
        toast({ kind: 'error', title: 'Run failed', description: toUserMessage(e) });
      }
    }
  };

  const onImportFile = async (file: File) => {
    const text = await file.text();
    const res = importDefinition(text);
    if (!res.ok || !res.definition) {
      toast({ kind: 'error', title: 'Import failed', description: res.error });
      return;
    }
    editor.load(res.definition);
    toast({
      kind: 'success',
      title: res.meta?.name ? `Imported “${res.meta.name}” — review, then save` : 'Imported — review, then save',
      description: res.migrated ? 'Migrated to the current schema version on import.' : undefined,
    });
  };

  return (
    <Protected>
      <Layout>
        <div className="oa-page max-w-none">
          {/* toolbar */}
          <div className="flex flex-wrap items-center gap-2 rounded-lg border bg-card p-3">
            <Link href={`/workflows/${workflow.id}`} aria-label="Back to workflow detail" className="rounded-md p-2 hover:bg-accent">
              <ArrowLeft className="h-4 w-4" />
            </Link>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={!canEdit}
              aria-label="Workflow name"
              className="h-9 w-56 font-semibold"
            />
            <StatusBadge status={workflow.status} />
            <SaveStatus
              online={online}
              saving={saving || saveState === 'saving'}
              failed={saveState === 'failed'}
              dirty={editor.dirty}
              onRetry={() => doSave()}
            />
            <TagEditor tags={tags} onChange={setTags} disabled={!canEdit} />
            <span className="flex items-center gap-1 text-xs" aria-live="polite">
              {editor.validation.valid ? (
                <><CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" /> Valid</>
              ) : (
                <><XCircle className="h-3.5 w-3.5 text-destructive" /> {editor.validation.errors.length} error{editor.validation.errors.length === 1 ? '' : 's'}</>
              )}
            </span>
            <span className="ml-auto flex flex-wrap items-center gap-1.5">
              <button onClick={editor.undo} disabled={!editor.canUndo || !canEdit} aria-label="Undo (Ctrl+Z)" className="rounded-md p-2 hover:bg-accent disabled:opacity-40">
                <Undo2 className="h-4 w-4" />
              </button>
              <button onClick={editor.redo} disabled={!editor.canRedo || !canEdit} aria-label="Redo (Ctrl+Y)" className="rounded-md p-2 hover:bg-accent disabled:opacity-40">
                <Redo2 className="h-4 w-4" />
              </button>
              <button
                onClick={() => downloadEnvelope(
                  { name: workflow.name, slug: workflow.slug, description: workflow.description, tags },
                  editor.definition,
                )}
                aria-label="Export workflow as portable envelope JSON"
                className="rounded-md p-2 hover:bg-accent"
              >
                <Download className="h-4 w-4" />
              </button>
              <PermissionGate permission="workflow:update">
                <button
                  onClick={() => fileRef.current?.click()}
                  aria-label="Import definition from JSON"
                  className="rounded-md p-2 hover:bg-accent"
                >
                  <Upload className="h-4 w-4" />
                </button>
                <input
                  ref={fileRef}
                  type="file"
                  accept="application/json,.json"
                  className="hidden"
                  aria-hidden
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) onImportFile(f);
                    e.target.value = '';
                  }}
                />
              </PermissionGate>
              <PermissionGate permission="workflow:update">
                <Button size="sm" variant="outline" onClick={() => doSave()} loading={saving} disabled={!canEdit}>
                  <Save className="mr-1.5 h-3.5 w-3.5" />Save
                </Button>
                <Button size="sm" variant="outline" onClick={doPublish} loading={mutations.publish.isPending} disabled={!canEdit}>
                  <Rocket className="mr-1.5 h-3.5 w-3.5" />Publish
                </Button>
              </PermissionGate>
              <PermissionGate permission="workflow:execute">
                <Button size="sm" onClick={doRun} disabled={workflow.status !== 'active'}>
                  <Play className="mr-1.5 h-3.5 w-3.5" />Run
                </Button>
              </PermissionGate>
            </span>
          </div>

          {draftNotice && (
            <div className="flex flex-wrap items-center gap-3 rounded-lg border border-amber-500/40 bg-amber-500/5 p-3 text-sm" role="alert">
              <p className="flex-1">An autosaved draft from your last session differs from the saved version.</p>
              <Button size="sm" variant="outline" onClick={() => { editor.clearDraft(); if (baseline) editor.load(baseline); setDraftNotice(false); }}>
                Discard draft
              </Button>
              <Button size="sm" onClick={() => setDraftNotice(false)}>Keep editing draft</Button>
            </div>
          )}

          {!canEdit && (
            <p className="rounded-lg border p-3 text-sm text-muted-foreground" role="note">
              This workflow is archived — read-only. Duplicate it to keep iterating.
            </p>
          )}

          {/* editor grid */}
          <div className="grid gap-3 xl:grid-cols-[240px_minmax(0,1fr)_320px] lg:grid-cols-[220px_minmax(0,1fr)]">
            <div className="hidden h-[560px] lg:block">
              <NodePalette editor={editor} disabled={!canEdit} />
            </div>
            <WorkflowCanvas editor={editor} readOnly={!canEdit} />
            <div className="grid gap-3 lg:col-span-2 xl:col-span-1 xl:grid-cols-1">
              <div className="h-[300px] xl:h-[280px]">
                <Inspector editor={editor} disabled={!canEdit} />
              </div>
              <div className="h-[260px]">
                <ValidationPanel editor={editor} />
              </div>
            </div>
          </div>

          <p className="oa-caption">
            Shortcuts: Del removes · Ctrl+Z / Ctrl+Y undo/redo · Ctrl+C/V/D copy/paste/duplicate ·
            Ctrl+S save · arrows nudge · Shift+drag box-select · F fit · Esc cancels.
            Version {workflow.latest_version?.version ?? '—'} · every save snapshots a new immutable version.
          </p>
        </div>
      </Layout>

      <Dialog
        open={conflict}
        onClose={() => setConflict(false)}
        title="Workflow changed elsewhere"
        description="Another client saved this workflow after you opened it. Your local draft is intact."
        footer={
          <>
            <Button variant="outline" onClick={() => { setConflict(false); editor.clearDraft(); refetch(); }}>
              Reload server version
            </Button>
            <Button onClick={() => setConflict(false)}>Keep local draft</Button>
          </>
        }
      >
        <p className="text-sm text-muted-foreground">
          Saving again will overwrite the newer server state. Reload to compare, or keep editing —
          your autosaved draft is preserved either way.
        </p>
      </Dialog>
    </Protected>
  );
}

function SaveStatus({
  online,
  saving,
  failed,
  dirty,
  onRetry,
}: {
  online: boolean;
  saving: boolean;
  failed: boolean;
  dirty: boolean;
  onRetry: () => void;
}) {
  if (!online) {
    return (
      <span className="rounded-full bg-muted px-2.5 py-1 text-xs text-muted-foreground" role="status">
        Offline — kept locally
      </span>
    );
  }
  if (saving) {
    return (
      <span className="text-xs text-muted-foreground" role="status" aria-live="polite">
        Saving…
      </span>
    );
  }
  if (failed) {
    return (
      <span className="flex items-center gap-1.5 text-xs text-destructive" role="alert">
        Save failed
        <button onClick={onRetry} className="font-medium underline hover:no-underline">
          Retry
        </button>
      </span>
    );
  }
  return (
    <span
      className={cn('text-xs', dirty ? 'text-amber-600 dark:text-amber-400' : 'text-muted-foreground')}
      aria-live="polite"
      role="status"
    >
      {dirty ? '● Unsaved changes' : 'Saved ✓'}
    </span>
  );
}

function TagEditor({
  tags,
  onChange,
  disabled,
}: {
  tags: string[];
  onChange: (tags: string[]) => void;
  disabled?: boolean;
}) {
  const [draft, setDraft] = React.useState('');
  const add = () => {
    const t = draft.trim().toLowerCase().replace(/\s+/g, '-').slice(0, 50);
    if (t && !tags.includes(t) && tags.length < 20) onChange([...tags, t]);
    setDraft('');
  };
  return (
    <span className="flex flex-wrap items-center gap-1" aria-label="Workflow tags">
      {tags.map((t) => (
        <span key={t} className="inline-flex items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-xs">
          {t}
          {!disabled && (
            <button
              aria-label={`Remove tag ${t}`}
              onClick={() => onChange(tags.filter((x) => x !== t))}
              className="text-muted-foreground hover:text-foreground"
            >
              ×
            </button>
          )}
        </span>
      ))}
      {!disabled && (
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault();
              add();
            }
          }}
          onBlur={add}
          placeholder={tags.length === 0 ? 'Add tags…' : '+'}
          aria-label="Add a tag"
          className="h-6 w-24 rounded-full border border-dashed bg-transparent px-2 text-xs outline-none placeholder:text-muted-foreground focus:border-primary"
        />
      )}
    </span>
  );
}
