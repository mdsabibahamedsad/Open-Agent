'use client';

import * as React from 'react';
import { useParams, useRouter } from 'next/navigation';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { Breadcrumbs, PageHeader } from '@/components/ui/page';
import { Button } from '@/components/ui/button';
import { StatusBadge } from '@/components/ui/status';
import { ConfirmDialog } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { PermissionGate } from '@/components/PermissionGate';
import { useToast } from '@/components/ui/toast';
import { toUserMessage } from '@/lib/api';
import { useApproval, useApprovalMutations } from '@/features/approvals/approvals-api';
import { isDangerous, riskTone } from '@/features/approvals/types';
import { cn } from '@/lib/utils';

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-3 gap-2 py-1.5 text-sm">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="col-span-2 break-words">{children}</dd>
    </div>
  );
}

export default function ApprovalDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const id = params.id;
  const { approval: a, isLoading, error, refetch } = useApproval(id);
  const { approve, reject, cancel, escalate } = useApprovalMutations(id);
  const { toast } = useToast();
  const [reason, setReason] = React.useState('');
  const [confirm, setConfirm] = React.useState<'approve' | 'reject' | null>(null);
  const [ack, setAck] = React.useState(false);

  React.useEffect(() => {
    if (error) toast({ kind: 'error', title: 'Failed to load approval', description: toUserMessage(error) });
  }, [error, toast]);

  const run = async (kind: 'approve' | 'reject' | 'cancel' | 'escalate', extra?: { escalate_to?: string }) => {
    try {
      const m = { approve, reject, cancel, escalate }[kind];
      await m.mutateAsync({ reason, ...extra });
      toast({ kind: 'success', title: `Approval ${kind}d` });
      setConfirm(null);
      setReason('');
      setAck(false);
      refetch();
    } catch (e) {
      toast({ kind: 'error', title: `${kind} failed`, description: toUserMessage(e) });
    }
  };

  const dangerous = a ? isDangerous(a) : false;
  const pending = a?.status === 'PENDING';

  return (
    <Protected>
      <Layout>
        <PermissionGate permission="approval:read" fallback={<p className="p-6">Approval view access required.</p>}>
          <div className="space-y-6 p-6">
            <Breadcrumbs items={[{ label: 'Approvals', href: '/approvals' }, { label: id.slice(0, 8) }]} />
            {isLoading && <p>Loading…</p>}
            {a && (
              <>
                <PageHeader
                  title={a.action_description || a.action_type || 'Approval request'}
                  description={`Requested by ${a.requester_type ?? 'agent'} · expires ${a.expires_at ? new Date(a.expires_at).toLocaleString() : '—'}`}
                  actions={
                    <>
                      <StatusBadge status={a.status} />
                      <span className={cn('inline-flex rounded-full border px-2.5 py-0.5 text-xs font-medium', riskTone(a.risk_level))}>
                        {a.risk_level ?? '—'}{typeof a.risk_score === 'number' ? ` · ${a.risk_score}` : ''}
                      </span>
                    </>
                  }
                />
                {dangerous && pending && (
                  <div className="rounded-md border border-red-500/30 bg-red-500/5 p-3 text-sm" role="alert">
                    High-impact action. Approval authorizes this exact action only (single-use, short-lived).
                    Secrets are redacted from this view.
                  </div>
                )}
                <div className="grid gap-6 lg:grid-cols-2">
                  <section className="rounded-lg border p-4">
                    <h2 className="font-semibold">Action &amp; impact</h2>
                    <dl className="mt-2 divide-y divide-border">
                      <Row label="Category">{a.action_category ?? '—'}</Row>
                      <Row label="Target">{[a.target_type, a.target_id, a.target_reference].filter(Boolean).join(' · ') || '—'}</Row>
                      <Row label="Impact">{a.impact_summary || '—'}</Row>
                      <Row label="Policy">{a.policy_decision ?? '—'}{a.required_role ? ` · requires ${a.required_role}` : ''}</Row>
                      <Row label="Kind">{a.approval_kind} · {a.required_approvals} of {a.required_approvals} required</Row>
                      <Row label="Agent">{a.agent_id ?? '—'}</Row>
                      <Row label="Workflow">{a.workflow_execution_id ?? a.workflow_id ?? '—'}</Row>
                    </dl>
                    <h3 className="mt-4 font-semibold">Requested parameters (redacted)</h3>
                    <pre className="mt-1 max-h-64 overflow-auto rounded bg-secondary p-2 text-xs">
                      {JSON.stringify(a.requested_parameters ?? {}, null, 2)}
                    </pre>
                    {(a.risk_reasons ?? []).length > 0 && (
                      <>
                        <h3 className="mt-4 font-semibold">Why approval is needed</h3>
                        <ul className="mt-1 list-disc pl-5 text-sm">
                          {a.risk_reasons.map((r) => (
                            <li key={r}>{r}</li>
                          ))}
                        </ul>
                      </>
                    )}
                  </section>
                  <section className="space-y-4">
                    <div className="rounded-lg border p-4">
                      <h2 className="font-semibold">Decision</h2>
                      <label className="mt-2 block text-sm">
                        Reason (recorded in audit log)
                        <Input
                          className="mt-1"
                          value={reason}
                          onChange={(e) => setReason(e.target.value)}
                          placeholder="Why are you approving or rejecting?"
                        />
                      </label>
                      {pending ? (
                        <PermissionGate permission="approval:approve">
                          <div className="mt-3 flex flex-wrap gap-2">
                            <Button onClick={() => (dangerous && !ack ? setConfirm('approve') : run('approve'))} loading={approve.isPending}>
                              Approve
                            </Button>
                            <Button variant="outline" onClick={() => setConfirm('reject')} loading={reject.isPending}>
                              Reject
                            </Button>
                            <Button variant="ghost" onClick={() => run('cancel')} loading={cancel.isPending}>
                              Cancel
                            </Button>
                            <Button variant="secondary" onClick={() => run('escalate', { escalate_to: 'organization_admin' })} loading={escalate.isPending}>
                              Escalate
                            </Button>
                          </div>
                          {dangerous && (
                            <label className="mt-3 flex items-start gap-2 text-sm">
                              <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} className="mt-1" />
                              I understand this action may modify production resources.
                            </label>
                          )}
                        </PermissionGate>
                      ) : (
                        <p className="mt-2 text-sm text-muted-foreground">
                          Decided: {a.status}
                          {a.approval_reason ? ` — ${a.approval_reason}` : ''}
                          {a.rejection_reason ? ` — ${a.rejection_reason}` : ''}
                        </p>
                      )}
                    </div>
                    <div className="rounded-lg border p-4">
                      <h2 className="font-semibold">Audit timeline</h2>
                      <ul className="mt-2 space-y-1 text-sm">
                        {(a.audit_timeline ?? []).map((e, i) => (
                          <li key={i}>
                            <span className="font-mono text-xs">{e.at ? new Date(e.at).toLocaleString() : '—'}</span>{' '}
                            {e.type}
                            {e.actor_id ? ` · ${e.actor_type}:${e.actor_id.slice(0, 8)}` : ''}
                          </li>
                        ))}
                        {(a.audit_timeline ?? []).length === 0 && <li className="text-muted-foreground">No events yet.</li>}
                      </ul>
                      <Button variant="link" className="mt-2 px-0" onClick={() => router.push('/approvals')}>
                        Back to Approval Center
                      </Button>
                    </div>
                  </section>
                </div>
              </>
            )}
          </div>
          <ConfirmDialog
            open={confirm !== null}
            onClose={() => setConfirm(null)}
            onConfirm={() => run(confirm ?? 'reject')}
            title={confirm === 'approve' ? 'Approve high-impact action?' : 'Reject approval request?'}
            description={
              confirm === 'approve'
                ? `This authorizes the exact action snapshot only. It cannot be replayed for other actions. Reason: ${reason || '(none given)'}`
                : `The requesting agent will receive a structured rejection. Reason: ${reason || '(none given)'}`
            }
            confirmLabel={confirm === 'approve' ? 'Approve' : 'Reject'}
            danger={confirm === 'approve'}
          />
        </PermissionGate>
      </Layout>
    </Protected>
  );
}
