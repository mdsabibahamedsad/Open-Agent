'use client';

import * as React from 'react';
import Link from 'next/link';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { StatusBadge } from '@/components/ui/status';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { fetchExecutionEvents, cancelCloudExecution, retryCloudExecution, submitCloudExecution } from '@/lib/cloud';

export default function CloudExecutionsPage() {
  const [cls, setCls] = React.useState('workflow');
  const [lastId, setLastId] = React.useState('');
  const [detail, setDetail] = React.useState('');
  const [busy, setBusy] = React.useState(false);

  async function submit() {
    setBusy(true);
    try {
      const res = await submitCloudExecution({ execution_class: cls }, crypto.randomUUID());
      setLastId(res.execution_id);
      setDetail(`${res.execution_id} → ${res.status} (region ${res.region}, queue ${res.queue})`);
    } catch (e) {
      setDetail(e instanceof Error ? e.message : 'Submit failed');
    } finally {
      setBusy(false);
    }
  }

  async function act(kind: 'cancel' | 'retry' | 'events') {
    if (!lastId) { setDetail('Submit or enter an execution id first'); return; }
    try {
      if (kind === 'cancel') {
        const res = await cancelCloudExecution(lastId);
        setDetail(`${res.execution_id} → ${res.status}`);
      } else if (kind === 'retry') {
        const res = await retryCloudExecution(lastId);
        setDetail(`${res.execution_id} → ${res.status}`);
      } else {
        const res = await fetchExecutionEvents(lastId);
        setDetail(res.events.map((e) => `#${e.sequence} ${e.type}`).join('\n') || 'No events yet');
      }
    } catch (e) {
      setDetail(e instanceof Error ? e.message : 'Action failed');
    }
  }

  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader
            title="Executions"
            description="Submit hosted executions and inspect lifecycle, events and retries."
            breadcrumbs={[{ label: 'Home', href: '/' }, { label: 'Cloud', href: '/cloud' }, { label: 'Executions' }]}
          />
          <Card>
            <CardHeader><CardTitle>Submit execution</CardTitle></CardHeader>
            <CardContent>
              <div className="flex flex-col gap-2 sm:flex-row">
                <Input value={cls} onChange={(e) => setCls(e.target.value)} aria-label="Execution class" className="sm:w-48" />
                <Input value={lastId} onChange={(e) => setLastId(e.target.value)} placeholder="execution id (optional lookup)" aria-label="Execution id" />
                <Button onClick={submit} disabled={busy}>{busy ? 'Submitting…' : 'Submit'}</Button>
              </div>
              <div className="flex gap-2">
                <Button variant="outline" onClick={() => act('events')}>Events</Button>
                <Button variant="outline" onClick={() => act('retry')}>Retry</Button>
                <Button variant="outline" onClick={() => act('cancel')}>Cancel</Button>
              </div>
              {detail ? <pre className="oa-code whitespace-pre-wrap">{detail}</pre> : null}
            </CardContent>
          </Card>
          <Link href="/cloud" className="oa-caption hover:underline">Back to Cloud overview</Link>
        </div>
      </Layout>
    </Protected>
  );
}
