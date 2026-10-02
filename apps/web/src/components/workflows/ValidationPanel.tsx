'use client';

import * as React from 'react';
import type { WorkflowEditor } from '@/features/workflows/use-workflow-editor';
import { useValidateDefinition } from '@/features/workflows/workflows-api';
import { Button } from '@/components/ui/button';
import { AlertTriangle, CheckCircle2, XCircle, Loader2, ShieldCheck } from 'lucide-react';
import { cn } from '@/lib/utils';

export function ValidationPanel({ editor }: { editor: WorkflowEditor }) {
  const { validation, select, definition } = editor;
  const serverValidate = useValidateDefinition();
  const [serverResult, setServerResult] = React.useState<null | {
    valid: boolean;
    errors: { code: string; message: string; node_id?: string }[];
    warnings: { code: string; message: string; node_id?: string }[];
  }>(null);

  const runServerValidation = async () => {
    setServerResult(null);
    try {
      const res = await serverValidate.mutateAsync(editor.definition);
      setServerResult(res);
    } catch {
      setServerResult(null);
    }
  };

  const shown = serverResult ?? { valid: validation.valid, errors: validation.errors, warnings: validation.warnings };

  return (
    <div className="flex h-full flex-col rounded-lg border bg-card" aria-live="polite">
      <div className="flex items-center justify-between gap-2 border-b p-3">
        <h2 className="flex items-center gap-2 text-sm font-semibold">
          {shown.valid ? (
            <CheckCircle2 className="h-4 w-4 text-emerald-500" aria-hidden />
          ) : (
            <XCircle className="h-4 w-4 text-destructive" aria-hidden />
          )}
          {shown.valid ? 'Valid' : `${shown.errors.length} problem${shown.errors.length === 1 ? '' : 's'}`}
        </h2>
        <Button size="sm" variant="outline" onClick={runServerValidation} disabled={serverValidate.isPending}>
          {serverValidate.isPending ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <ShieldCheck className="mr-1.5 h-3.5 w-3.5" />}
          Dry-run
        </Button>
      </div>
      <div className="flex-1 space-y-1 overflow-y-auto p-2">
        {serverValidate.isError && (
          <p className="rounded-md bg-destructive/10 px-2.5 py-2 text-xs text-destructive" role="alert">
            Server validation unavailable — showing local results. The backend remains authoritative at publish time.
          </p>
        )}
        {serverResult && (
          <p className="oa-caption px-1.5 pb-1">Server verdict · {serverResult.valid ? 'valid' : 'invalid'}</p>
        )}
        {shown.errors.map((e, i) => (
          <IssueRow
            key={`e-${i}`}
            kind="error"
            message={e.message}
            nodeId={e.node_id}
            onSelect={() => e.node_id && selectKind(e.node_id, definition, select)}
          />
        ))}
        {shown.warnings.map((w, i) => (
          <IssueRow
            key={`w-${i}`}
            kind="warning"
            message={w.message}
            nodeId={w.node_id}
            onSelect={() => w.node_id && selectKind(w.node_id, definition, select)}
          />
        ))}
        {shown.errors.length === 0 && shown.warnings.length === 0 && (
          <p className="px-1.5 py-4 text-center text-xs text-muted-foreground">
            No problems. Publish when ready — the server re-validates.
          </p>
        )}
      </div>
    </div>
  );
}

function selectKind(
  nodeId: string,
  definition: WorkflowEditor['definition'],
  select: WorkflowEditor['select'],
) {
  if (definition.triggers.some((t) => t.id === nodeId)) {
    select({ kind: 'trigger', id: nodeId });
  } else {
    select({ kind: 'node', id: nodeId });
  }
}

function IssueRow({
  kind,
  message,
  nodeId,
  onSelect,
}: {
  kind: 'error' | 'warning';
  message: string;
  nodeId?: string;
  onSelect?: () => void;
}) {
  const inner = (
    <>
      {kind === 'error' ? (
        <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-destructive" aria-hidden />
      ) : (
        <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-500" aria-hidden />
      )}
      <span className="min-w-0 flex-1">
        {message}
        {nodeId && <span className="oa-code ml-1.5">{nodeId}</span>}
      </span>
    </>
  );
  const cls = cn(
    'flex w-full items-start gap-2 rounded-md px-2.5 py-2 text-left text-xs',
    kind === 'error' ? 'bg-destructive/5 hover:bg-destructive/10' : 'hover:bg-accent',
  );
  if (nodeId && onSelect) {
    return (
      <button className={cls} onClick={onSelect} aria-label={`Go to ${nodeId}: ${message}`}>
        {inner}
      </button>
    );
  }
  return <div className={cls}>{inner}</div>;
}
