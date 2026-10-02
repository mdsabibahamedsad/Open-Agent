'use client';

import * as React from 'react';
import { Button } from '@/components/ui/button';
import { StatusBadge } from '@/components/ui/status';
import { PermissionGate } from '@/components/PermissionGate';
import {
  useDelegations,
  useHandoffs,
  useManagementMutation,
  useReviews,
} from './api';

export function DelegationPanel({ runId, onChanged }: { runId: string; onChanged: () => void }) {
  const { items } = useDelegations(runId);
  if (items.length === 0) {
    return <p className="text-sm text-muted-foreground">No delegations for this run.</p>;
  }
  return (
    <ul className="space-y-2">
      {items.map((d) => (
        <li key={d.id} className="rounded border p-3 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium">{d.reason || 'Delegation'}</span>
            <StatusBadge status={d.status} />
            <span className="text-xs text-muted-foreground">policy {d.policy}</span>
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            {d.source_agent_id?.slice(0, 8) ?? '?'} → {d.target_agent_id?.slice(0, 8) ?? 'unassigned'}
            {d.required_capabilities.length > 0 &&
              ` · needs ${d.required_capabilities.join(', ')}`}
          </p>
          {d.status === 'pending' && (
            <div className="mt-2 flex gap-2">
              <TransitionButton path={`/delegations/${d.id}/accept`} label="Approve" onDone={onChanged} />
              <TransitionButton path={`/delegations/${d.id}/reject`} label="Reject" onDone={onChanged} />
              <TransitionButton path={`/delegations/${d.id}/cancel`} label="Cancel" onDone={onChanged} />
            </div>
          )}
        </li>
      ))}
    </ul>
  );
}

export function HandoffPanel({ runId, onChanged }: { runId: string; onChanged: () => void }) {
  const { items } = useHandoffs(runId);
  const [expanded, setExpanded] = React.useState<string | null>(null);
  if (items.length === 0) {
    return <p className="text-sm text-muted-foreground">No handoffs for this run.</p>;
  }
  return (
    <ul className="space-y-2">
      {items.map((h) => {
        const pkg = (h.package ?? {}) as Record<string, unknown>;
        return (
          <li key={h.id} className="rounded border p-3 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-medium">{h.mode.replace(/_/g, ' ')}</span>
              <StatusBadge status={h.status} />
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setExpanded((e) => (e === h.id ? null : h.id))}
                aria-expanded={expanded === h.id}
              >
                {expanded === h.id ? 'Hide' : 'Inspect'}
              </Button>
            </div>
            <p className="mt-1 text-xs text-muted-foreground">
              {h.source_agent_id?.slice(0, 8) ?? '?'} → {h.target_agent_id?.slice(0, 8) ?? '?'} ·
              next: {String(pkg.next_action ?? '—').slice(0, 120)}
            </p>
            {expanded === h.id && (
              <div className="mt-2 space-y-1 text-xs">
                <ManifestRow label="Included" items={h.context_manifest.included_items} />
                <ManifestRow label="Excluded" items={h.context_manifest.excluded_items} />
                <ManifestRow label="Redacted" items={h.context_manifest.redacted_items} />
                <p className="text-muted-foreground">policy: {h.context_manifest.policy}</p>
                <pre className="overflow-auto rounded bg-muted p-2">
                  {JSON.stringify(
                    {
                      completed_work: pkg.completed_work,
                      pending_work: pkg.pending_work,
                      acceptance_criteria: pkg.acceptance_criteria,
                      warnings: pkg.warnings,
                    },
                    null,
                    2,
                  ).slice(0, 3000)}
                </pre>
              </div>
            )}
            {h.status === 'pending_acceptance' && (
              <div className="mt-2 flex gap-2">
                <TransitionButton path={`/handoffs/${h.id}/accept`} label="Accept" onDone={onChanged} />
                <TransitionButton path={`/handoffs/${h.id}/reject`} label="Reject" onDone={onChanged} />
              </div>
            )}
            {h.status === 'accepted' && (
              <div className="mt-2 flex gap-2">
                <TransitionButton path={`/handoffs/${h.id}/execute`} label="Start executing" onDone={onChanged} />
              </div>
            )}
            {h.status === 'executing' && (
              <div className="mt-2 flex gap-2">
                <TransitionButton path={`/handoffs/${h.id}/complete`} label="Complete" onDone={onChanged} />
              </div>
            )}
          </li>
        );
      })}
    </ul>
  );
}

export function ReviewPanel({
  runId,
  taskId,
  onChanged,
}: {
  runId: string;
  taskId: string;
  onChanged: () => void;
}) {
  const { items, refetch } = useReviews(taskId);
  const approve = useManagementMutation('/reviews');
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const submit = (status: string) => {
    setBusy(true);
    setError(null);
    approve
      .mutateAsync({ run_id: runId, task_id: taskId, status_override: status })
      .then(
        () => {
          setBusy(false);
          refetch();
          onChanged();
        },
        (err: unknown) => {
          setBusy(false);
          setError(err instanceof Error ? err.message : 'Review failed.');
        },
      );
  };

  return (
    <div className="space-y-2 text-sm">
      {error && (
        <p role="alert" className="text-destructive">
          {error}
        </p>
      )}
      {items.length === 0 && <p className="text-muted-foreground">No reviews yet.</p>}
      {items.map((r) => (
        <div key={r.id} className="rounded border p-2">
          <div className="flex items-center gap-2">
            <StatusBadge status={r.status} />
            <span className="text-xs text-muted-foreground">revision {r.revision_number}</span>
            {r.gate_result && <span className="text-xs">gate: {r.gate_result}</span>}
          </div>
          {r.required_changes.length > 0 && (
            <ul className="mt-1 list-disc pl-5 text-xs">
              {r.required_changes.map((c, i) => (
                <li key={i}>{c}</li>
              ))}
            </ul>
          )}
        </div>
      ))}
      <div className="flex gap-2">
        <PermissionGate permission="agent:create">
          <Button size="sm" variant="outline" disabled={busy} onClick={() => submit('approved')}>
            Approve
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={busy}
            onClick={() => submit('revision_required')}
          >
            Request revision
          </Button>
          <Button size="sm" variant="outline" disabled={busy} onClick={() => submit('escalate')}>
            Escalate
          </Button>
        </PermissionGate>
      </div>
    </div>
  );
}

function ManifestRow({ label, items }: { label: string; items: string[] }) {
  return (
    <p>
      <span className="font-medium">{label} ({items.length}): </span>
      <span className="text-muted-foreground">{items.join(', ') || '—'}</span>
    </p>
  );
}

function TransitionButton({
  path,
  label,
  onDone,
}: {
  path: string;
  label: string;
  onDone: () => void;
}) {
  const mutation = useManagementMutation(path);
  const [error, setError] = React.useState<string | null>(null);
  return (
    <span>
      <PermissionGate permission="agent:create">
        <Button
          size="sm"
          variant="outline"
          disabled={mutation.isPending}
          onClick={() =>
            mutation.mutateAsync({}).then(
              () => {
                setError(null);
                onDone();
              },
              (err: unknown) => setError(err instanceof Error ? err.message : 'Action failed.'),
            )
          }
        >
          {label}
        </Button>
      </PermissionGate>
      {error && <span className="ml-1 text-xs text-destructive">{error}</span>}
    </span>
  );
}
