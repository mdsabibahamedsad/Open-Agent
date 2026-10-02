'use client';

import * as React from 'react';
import Link from 'next/link';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { fetchMfaStatus, enrollTotp, mintRecoveryCodes } from '@/lib/enterprise';

export default function MfaPage() {
  const [enabled, setEnabled] = React.useState(false);
  const [secret, setSecret] = React.useState('');
  const [codes, setCodes] = React.useState<string[]>([]);

  React.useEffect(() => {
    fetchMfaStatus().then((s) => setEnabled(s.mfa_enabled)).catch(() => {});
  }, []);

  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader
            title="Multi-Factor Authentication"
            description="TOTP, WebAuthn/passkeys and single-use recovery codes."
            breadcrumbs={[{ label: 'Home', href: '/' }, { label: 'Enterprise', href: '/settings/enterprise' }, { label: 'MFA' }]}
          />
          <Card>
            <CardHeader><CardTitle>Status: {enabled ? 'enabled' : 'not enabled'}</CardTitle></CardHeader>
            <CardContent>
              <div className="flex gap-2">
                <Button variant="outline" onClick={async () => {
                  const res = await enrollTotp();
                  setSecret(`${res.secret} — ${res.uri}`);
                }}>Enroll TOTP</Button>
                <Button variant="outline" onClick={async () => {
                  const res = await mintRecoveryCodes();
                  setCodes(res.codes);
                }}>Recovery codes</Button>
              </div>
              {secret ? <p className="oa-code">Scan or save (once): {secret}</p> : null}
              {codes.length > 0 ? <p className="oa-code">Save now (never shown again): {codes.join(' ')}</p> : null}
            </CardContent>
          </Card>
          <Link href="/settings/enterprise" className="oa-caption hover:underline">Back to Enterprise Security</Link>
        </div>
      </Layout>
    </Protected>
  );
}
