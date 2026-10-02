'use client';

import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { EmptyState } from '@/components/ui/states';
import { Brain } from 'lucide-react';

export default function MemoryPage() {
  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader title="Memory" description="Architecture placeholder for the future memory engine." breadcrumbs={[{ label: 'Home', href: '/' }, { label: 'Memory' }]} />
          <div className="grid gap-4 md:grid-cols-3">
            {['Overview', 'Memories', 'Conversations'].map((t) => (
              <Card key={t}>
                <CardHeader><CardTitle>{t}</CardTitle><CardDescription>Planned scope</CardDescription></CardHeader>
                <CardContent><p className="text-sm text-muted-foreground">Backend-connected memory management will live here. Nothing is faked.</p></CardContent>
              </Card>
            ))}
          </div>
          <Card>
            <CardContent>
              <EmptyState icon={Brain} title="Memory engine not yet available" description="Namespaced, permission-scoped memory with retention controls ships in a later phase." />
            </CardContent>
          </Card>
        </div>
      </Layout>
    </Protected>
  );
}
