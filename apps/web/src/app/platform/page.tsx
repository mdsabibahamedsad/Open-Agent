'use client';

import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { useAuth } from '@/context/AuthContext';
import { ShieldCheck } from 'lucide-react';

export default function PlatformPage() {
  const { user } = useAuth();
  const allowed = !!(user?.is_platform_owner || user?.is_superadmin);
  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader
            title="Platform"
            description="Platform administration is visually separated from organization administration."
            breadcrumbs={[{ label: 'Home', href: '/' }, { label: 'Platform' }]}
          />
          {!allowed ? (
            <Card>
              <CardHeader><CardTitle className="flex items-center gap-2"><ShieldCheck className="h-5 w-5" />Restricted</CardTitle>
              <CardDescription>Only the platform owner can access this area.</CardDescription></CardHeader>
              <CardContent><p className="text-sm text-muted-foreground">Sign in with a platform-owner identity to manage organizations, users, and audit.</p></CardContent>
            </Card>
          ) : (
            <div className="grid gap-4 md:grid-cols-3">
              {['Organizations', 'Users', 'System', 'Marketplace', 'Security', 'Audit'].map((t) => (
                <Card key={t}>
                  <CardHeader><CardTitle>{t}</CardTitle><CardDescription>Platform scope</CardDescription></CardHeader>
                  <CardContent><p className="text-sm text-muted-foreground">Backend-connected tables land here next phase.</p></CardContent>
                </Card>
              ))}
            </div>
          )}
        </div>
      </Layout>
    </Protected>
  );
}
