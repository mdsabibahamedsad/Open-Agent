'use client';

import * as React from 'react';
import Link from 'next/link';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { StatusBadge } from '@/components/ui/status';
import { Button } from '@/components/ui/button';
import { Select } from '@/components/ui/form';
import { fetchIncidentDetail, transitionIncident } from '@/lib/operations';

const NEXT: Record<string, string[]> = {
  DETECTED: ['ACKNOWLEDGED', 'INVESTIGATING'],
  ACKNOWLEDGED: ['INVESTIGATING', 'MITIGATING'],
  INVESTIGATING: ['MITIGATING', 'MONITORING', 'RESOLVED'],
  MITIGATING: ['MONITORING', 'INVESTIGATING', 'RESOLVED'],
  MONITORING: ['RESOLVED', 'MITIGATING'],
  RESOLVED: ['CLOSED', 'INVESTIGATING'],
  CLOSED: [],
};

export default function IncidentDetailPage({ params }: { params: { id: string } }) {
  const [detail, setDetail] = React.useState<{ title: string; status: string; severity: string; timeline: { at: string; actor: string; message: string }[] } | null>(null);
  const [target, setTarget] = React.useState('');
  const [error, setError] = React.useState<string | null>(null);

  const load = React.useCallback(async () => {
    try {
      const res = await fetchIncidentDetail(params.id);
      setDetail(res);
      setTarget('');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load incident');
    }
  }, [params.id]);

  React.useEffect(() => { load(); }, [load]);

  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader
            title={detail?.title ?? 'Incident'}
            description="Immutable timeline, responders and resolution."
            breadcrumbs={[{ label: 'Home', href: '/' }, { label: 'Operations', href: '/operations' }, { label: 'Incidents', href: '/operations/incidents' }, { label: detail?.title ?? params.id }]}
          />
          {error ? <p className="oa-caption">{error}</p> : detail ? (
            <>
              <Card>
                <CardHeader><CardTitle>Status</CardTitle></CardHeader>
                <CardContent>
                  <StatusBadge status={detail.status} /> <StatusBadge status={detail.severity} />
                  <div className="flex gap-2">
                    <Select value={target} onChange={(e) => setTarget(e.target.value)} aria-label="Next status" className="sm:w-48">
                      <option value="">Move to…</option>
                      {(NEXT[detail.status] ?? []).map((s) => <option key={s} value={s}>{s}</option>)}
                    </Select>
                    <Button disabled={!target} onClick={async () => { await transitionIncident(params.id, target); await load(); }}>
                      Apply
                    </Button>
                  </div>
                </CardContent>
              </Card>
              <Card>
                <CardHeader><CardTitle>Timeline</CardTitle></CardHeader>
                <CardContent>
                  <ol>
                    {detail.timeline.map((t, i) => (
                      <li key={i} className="oa-caption">{new Date(t.at).toLocaleString()} — {t.actor} — {t.message}</li>
                    ))}
                  </ol>
                </CardContent>
              </Card>
            </>
          ) : <p className="oa-caption">Loading…</p>}
          <Link href="/operations/incidents" className="oa-caption hover:underline">Back to incidents</Link>
        </div>
      </Layout>
    </Protected>
  );
}
