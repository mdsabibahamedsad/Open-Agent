'use client';

import * as React from 'react';
import Link from 'next/link';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Select } from '@/components/ui/form';
import { fetchOrgCloudSettings, saveOrgCloudSettings } from '@/lib/cloud';

export default function CloudSettingsPage() {
  const [residency, setResidency] = React.useState('ANY_REGION');
  const [pool, setPool] = React.useState('default');
  const [maxConcurrent, setMaxConcurrent] = React.useState(10);
  const [retention, setRetention] = React.useState(2592000);
  const [webhooks, setWebhooks] = React.useState(120);
  const [status, setStatus] = React.useState('');

  React.useEffect(() => {
    fetchOrgCloudSettings()
      .then((s) => {
        setResidency(s.residency);
        setPool(s.pool);
        setMaxConcurrent(s.max_concurrent);
        setRetention(s.artifact_retention_s);
        setWebhooks(s.webhook_per_minute);
      })
      .catch(() => {});
  }, []);

  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader
            title="Cloud settings"
            description="Organization execution policy: residency, pools, concurrency and retention."
            breadcrumbs={[{ label: 'Home', href: '/' }, { label: 'Cloud', href: '/cloud' }, { label: 'Settings' }]}
          />
          <Card>
            <CardHeader><CardTitle>Execution policy</CardTitle></CardHeader>
            <CardContent>
              <form
                className="flex flex-col gap-3"
                onSubmit={async (e) => {
                  e.preventDefault();
                  setStatus('Saving…');
                  try {
                    await saveOrgCloudSettings({
                      residency, pool_preference: pool,
                      max_concurrent_executions: maxConcurrent,
                      artifact_retention_seconds: retention,
                      webhook_limit_per_minute: webhooks,
                    });
                    setStatus('Saved');
                  } catch (err) {
                    setStatus(err instanceof Error ? err.message : 'Save failed');
                  }
                }}
              >
                <label className="oa-caption">Data residency
                  <Select value={residency} onChange={(e) => setResidency(e.target.value)}>
                    {['ANY_REGION', 'EU_ONLY', 'US_ONLY', 'APAC_ONLY', 'ORG_SELECTED', 'PRIVATE_REGION'].map((r) => (
                      <option key={r} value={r}>{r}</option>
                    ))}
                  </Select>
                </label>
                <label className="oa-caption">Worker pool preference
                  <Input value={pool} onChange={(e) => setPool(e.target.value)} />
                </label>
                <label className="oa-caption">Max concurrent executions
                  <Input type="number" value={maxConcurrent} onChange={(e) => setMaxConcurrent(Number(e.target.value))} />
                </label>
                <label className="oa-caption">Artifact retention (seconds)
                  <Input type="number" value={retention} onChange={(e) => setRetention(Number(e.target.value))} />
                </label>
                <label className="oa-caption">Webhook limit per minute
                  <Input type="number" value={webhooks} onChange={(e) => setWebhooks(Number(e.target.value))} />
                </label>
                <Button type="submit">Save policy</Button>
                {status ? <span className="oa-caption">{status}</span> : null}
              </form>
            </CardContent>
          </Card>
          <Link href="/cloud" className="oa-caption hover:underline">Back to Cloud overview</Link>
        </div>
      </Layout>
    </Protected>
  );
}
