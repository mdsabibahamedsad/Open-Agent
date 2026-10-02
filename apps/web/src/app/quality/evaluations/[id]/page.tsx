'use client';

import * as React from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { Breadcrumbs, PageHeader } from '@/components/ui/page';
import { Button } from '@/components/ui/button';
import { StatusBadge } from '@/components/ui/status';
import { Input } from '@/components/ui/input';
import { PermissionGate } from '@/components/PermissionGate';
import { useToast } from '@/components/ui/toast';
import { toUserMessage } from '@/lib/api';
import { useEvaluation, useEvaluationMutations } from '@/features/quality/quality-api';
import { decisionTone, trustTone } from '@/features/quality/types';
import { cn } from '@/lib/utils';

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-3 gap-2 py-1.5 text-sm">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="col-span-2 break-words">{children}</dd>
    </div>
  );
}

export default function EvaluationDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const { evaluation: e, isLoading, error, refetch } = useEvaluation(id);
  const { retry, correct, feedback } = useEvaluationMutations(id);
  const { toast } = useToast();
  const [verdict, setVerdict] = React.useState('correct');
  const [reason, setReason] = React.useState('');

  React.useEffect(() => {
    if (error) toast({ kind: 'error', title: 'Failed to load evaluation', description: toUserMessage(error) });
  }, [error, toast]);

  const sendFeedback = async () => {
    try {
      await feedback.mutateAsync({ verdict, reason });
      toast({ kind: 'success', title: 'Feedback recorded (history unchanged)' });
      setReason('');
      refetch();
    } catch (err) {
      toast({ kind: 'error', title: 'Feedback failed', description: toUserMessage(err) });
    }
  };

  const planCorrection = async () => {
    try {
      await correct.mutateAsync({});
      toast({ kind: 'success', title: 'Correction plan created' });
      refetch();
    } catch (err) {
      toast({ kind: 'error', title: 'Correction failed', description: toUserMessage(err) });
    }
  };

  const retryEvaluation = async () => {
    try {
      await retry.mutateAsync({ reason: 'manual retry from Quality Center' });
      toast({ kind: 'success', title: 'New linked evaluation created' });
      refetch();
    } catch (err) {
      toast({ kind: 'error', title: 'Retry failed', description: toUserMessage(err) });
    }
  };

  return (
    <Protected>
      <Layout>
        <PermissionGate permission="evaluation:read" fallback={<p className="p-6">Evaluation view access required.</p>}>
          <div className="space-y-6 p-6">
            <Breadcrumbs items={[{ label: 'Quality', href: '/quality' }, { label: id.slice(0, 8) }]} />
            {isLoading && <p>Loading…</p>}
            {e && (
              <>
                <PageHeader
                  title={`${e.evaluation_type} evaluation`}
                  description={`Attempt ${e.attempt_number}${e.parent_evaluation_id ? ` · retry of ${e.parent_evaluation_id.slice(0, 8)}` : ''}`}
                  actions={
                    <>
                      <StatusBadge status={e.status} />
                      <span className={cn('inline-flex rounded-full border px-2.5 py-0.5 text-xs font-medium', decisionTone(e.decision))}>
                        {e.decision ?? '—'}
                        {typeof e.score === 'number' ? ` · ${(e.score * 100).toFixed(1)}%` : ''}
                      </span>
                    </>
                  }
                />
                {(e.failure_reason || e.uncertainty_reason) && (
                  <div className="rounded-md border border-amber-500/30 bg-amber-500/5 p-3 text-sm" role="alert">
                    {e.failure_reason || e.uncertainty_reason}
                  </div>
                )}
                <div className="grid gap-6 lg:grid-cols-2">
                  <section className="rounded-lg border p-4">
                    <h2 className="font-semibold">Evidence (traceable)</h2>
                    <ul className="mt-2 space-y-2 text-sm">
                      {(e.evidence ?? []).map((ev) => (
                        <li key={ev.id} className="rounded border p-2">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="font-mono text-xs">{ev.evidence_type}</span>
                            <span className={cn('inline-flex rounded-full border px-2 py-0.5 text-xs', trustTone(ev.trust))}>
                              {ev.trust}
                            </span>
                            <span className="text-muted-foreground">{ev.source}</span>
                          </div>
                          <pre className="mt-1 max-h-40 overflow-auto rounded bg-secondary p-2 text-xs">
                            {JSON.stringify(ev.content ?? {}, null, 2)}
                          </pre>
                          <div className="mt-1 font-mono text-[11px] text-muted-foreground">hash {ev.content_hash || '—'}</div>
                        </li>
                      ))}
                      {(e.evidence ?? []).length === 0 && <li className="text-muted-foreground">No evidence captured.</li>}
                    </ul>
                    <h3 className="mt-4 font-semibold">Verification checks</h3>
                    <ul className="mt-1 space-y-1 text-sm">
                      {(e.checks ?? []).map((c, i) => (
                        <li key={i}>
                          {c.passed ? '✓' : '✗'} <span className="font-mono text-xs">{c.name}</span>
                          {!c.passed && <span className="text-muted-foreground"> — {c.reason}</span>}
                        </li>
                      ))}
                      {(e.checks ?? []).length === 0 && <li className="text-muted-foreground">No checks run.</li>}
                    </ul>
                    <h3 className="mt-4 font-semibold">Evaluator votes</h3>
                    <ul className="mt-1 space-y-1 text-sm">
                      {(e.votes ?? []).map((v, i) => (
                        <li key={i}>
                          <span className="font-mono text-xs">{v.source}</span>: {v.decision} · {(v.score * 100).toFixed(0)}%
                          {v.reason_codes.length > 0 && <span className="text-muted-foreground"> ({v.reason_codes.join(', ')})</span>}
                        </li>
                      ))}
                      {(e.votes ?? []).length === 0 && <li className="text-muted-foreground">No votes recorded.</li>}
                    </ul>
                  </section>
                  <section className="space-y-4">
                    <div className="rounded-lg border p-4">
                      <h2 className="font-semibold">Correction timeline</h2>
                      <ol className="mt-2 space-y-2 text-sm">
                        <li>Attempt {e.attempt_number} → {e.decision ?? e.status}</li>
                        {(e.correction_plans ?? []).map((p) => (
                          <li key={p.id}>
                            Plan <span className="font-mono text-xs">{p.id.slice(0, 8)}</span> · {p.strategy} · {p.status}
                          </li>
                        ))}
                        {(e.correction_plans ?? []).length === 0 && (
                          <li className="text-muted-foreground">No correction plans yet.</li>
                        )}
                      </ol>
                      <PermissionGate permission="evaluation:decide">
                        <div className="mt-3 flex flex-wrap gap-2">
                          <Button variant="outline" onClick={planCorrection} loading={correct.isPending}>
                            Plan correction
                          </Button>
                          <Button variant="outline" onClick={retryEvaluation} loading={retry.isPending}>
                            Retry (new evaluation)
                          </Button>
                        </div>
                      </PermissionGate>
                    </div>
                    <div className="rounded-lg border p-4">
                      <h2 className="font-semibold">Human feedback (append-only)</h2>
                      <ul className="mt-2 space-y-1 text-sm">
                        {(e.feedback ?? []).map((f, i) => (
                          <li key={i}>
                            {f.verdict} — {f.reason} <span className="text-muted-foreground">({f.at ?? '—'})</span>
                          </li>
                        ))}
                        {(e.feedback ?? []).length === 0 && <li className="text-muted-foreground">No feedback yet.</li>}
                      </ul>
                      <PermissionGate permission="evaluation:create">
                        <div className="mt-3 flex flex-wrap items-center gap-2">
                          <select
                            value={verdict}
                            onChange={(ev) => setVerdict(ev.target.value)}
                            className="rounded-md border border-input bg-background px-3 py-2 text-sm"
                            aria-label="Verdict"
                          >
                            <option value="correct">correct</option>
                            <option value="incorrect">incorrect</option>
                            <option value="partially_correct">partially_correct</option>
                          </select>
                          <Input
                            className="min-w-40 flex-1"
                            value={reason}
                            onChange={(ev) => setReason(ev.target.value)}
                            placeholder="Reason"
                          />
                          <Button onClick={sendFeedback} loading={feedback.isPending}>
                            Submit
                          </Button>
                        </div>
                      </PermissionGate>
                    </div>
                    <div className="rounded-lg border p-4 text-sm">
                      <h2 className="font-semibold">Reproducibility</h2>
                      <dl className="mt-1">
                        <Row label="Evaluator">{e.evaluator_version}</Row>
                        <Row label="Rubric">{e.rubric_version ?? '—'}</Row>
                        <Row label="Model">{e.model_version ?? '—'}</Row>
                        <Row label="Input hash">
                          <span className="font-mono text-xs">{e.input_hash ?? '—'}</span>
                        </Row>
                        <Row label="Output hash">
                          <span className="font-mono text-xs">{e.output_hash ?? '—'}</span>
                        </Row>
                      </dl>
                      <Link href="/quality" className="mt-2 inline-block text-primary hover:underline">
                        Back to Quality Center
                      </Link>
                    </div>
                  </section>
                </div>
              </>
            )}
          </div>
        </PermissionGate>
      </Layout>
    </Protected>
  );
}
