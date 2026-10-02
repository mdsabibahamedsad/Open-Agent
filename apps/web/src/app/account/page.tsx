'use client';

import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { useAuth } from '@/context/AuthContext';

export default function AccountPage() {
  const { user } = useAuth();
  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader title="Account" description="Your profile and session identity." breadcrumbs={[{ label: 'Home', href: '/' }, { label: 'Account' }]} />
          <Card>
            <CardHeader><CardTitle>{user?.display_name ?? 'User'}</CardTitle><CardDescription>{user?.email}</CardDescription></CardHeader>
            <CardContent>
              <dl className="grid gap-2 text-sm sm:grid-cols-2">
                <div><dt className="text-muted-foreground">User ID</dt><dd className="oa-code">{user?.id}</dd></div>
                <div><dt className="text-muted-foreground">Status</dt><dd>{user?.status}</dd></div>
                <div><dt className="text-muted-foreground">Email verified</dt><dd>{user?.email_verified ? 'Yes' : 'No'}</dd></div>
                <div><dt className="text-muted-foreground">Platform owner</dt><dd>{user?.is_platform_owner ? 'Yes' : 'No'}</dd></div>
              </dl>
            </CardContent>
          </Card>
        </div>
      </Layout>
    </Protected>
  );
}
