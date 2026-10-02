'use client';

import * as React from 'react';
import Link from 'next/link';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { StatusBadge } from '@/components/ui/status';
import { PageLoading } from '@/components/ui/loading';
import { fetchPosture, fetchSecurityAnalytics, fetchMfaStatus } from '@/lib/enterprise';

export default function EnterpriseOverviewPage() {
  const [posture, setPosture] = React.useState<Record<string, string | string[]> | null>(null);
  const [analytics, setAnalytics] = React.useState<{ failed_authentications: number; policy_denials: number } | null>(null);
  const [mfa, setMfa] = React.useState<boolean | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [p, a, m] = await Promise.all([
          fetchPosture(),
          fetchSecurityAnalytics().catch(() => ({ failed_authentications: 0, policy_denials: 0 })),
          fetchMfaStatus().catch(() => ({ mfa_enabled: false })),
        ]);
        if (!cancelled) {
          setPosture(p as unknown as Record<string, string | string[]>);
          setAnalytics(a);
          setMfa(m.mfa_enabled);
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Enterprise security unavailable');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const entries = posture ? Object.entries(posture).filter(([k]) => k !== 'Open Issues') : [];

  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader
            title="Enterprise Security"
            description="Evidence-based posture: SSO, SCIM, MFA, sessions, devices, policies and audit."
            breadcrumbs={[{ label: 'Home', href: '/' }, { label: 'Settings', href: '/settings' }, { label: 'Enterprise Security' }]}
          />
          {loading ? <PageLoading label="Loading security posture…" /> : error ? (
            <Card><CardContent><p className="oa-caption">{error}</p></CardContent></Card>
          ) : (
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {entries.map(([control, state]) => (
                <Card key={control}>
                  <CardHeader><CardTitle>{control}</CardTitle></CardHeader>
                  <CardContent>
                    <StatusBadge status={String(state) === 'Enabled' || String(state) === 'Configured' || String(state) === 'Required' ? 'HEALTHY' : 'UNKNOWN'} />
                    <p className="oa-caption">{String(state)}</p>
                  </CardContent>
                </Card>
              ))}
              <Card>
                <CardHeader><CardTitle>My MFA</CardTitle></CardHeader>
                <CardContent>
                  <p className="oa-caption">{mfa ? 'Enabled' : 'Not enabled'}</p>
                  <Link href="/settings/enterprise/mfa" className="oa-caption hover:underline">Manage MFA</Link>
                </CardContent>
              </Card>
              <Card>
                <CardHeader><CardTitle>Failed authentications</CardTitle></CardHeader>
                <CardContent>
                  <p className="text-3xl font-semibold">{analytics?.failed_authentications ?? 0}</p>
                  <p className="oa-caption">{analytics?.policy_denials ?? 0} policy denials</p>
                </CardContent>
              </Card>
            </div>
          )}
          <nav className="flex flex-wrap gap-3" aria-label="Enterprise sections">
            {[
              ['/settings/enterprise/sso', 'SSO'],
              ['/settings/enterprise/scim', 'SCIM'],
              ['/settings/enterprise/mfa', 'MFA'],
              ['/settings/enterprise/sessions', 'Sessions'],
              ['/settings/enterprise/devices', 'Devices'],
              ['/settings/enterprise/policies', 'Policies'],
              ['/settings/enterprise/controls', 'Compliance'],
            ].map(([href, label]) => (
              <Link key={href} href={href} className="oa-caption hover:underline">{label}</Link>
            ))}
          </nav>
        </div>
      </Layout>
    </Protected>
  );
}
