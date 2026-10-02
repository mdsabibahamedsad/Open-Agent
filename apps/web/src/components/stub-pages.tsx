'use client';

import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { Card, CardContent } from '@/components/ui/card';
import { EmptyState } from '@/components/ui/states';
import { FileStack, BookOpen } from 'lucide-react';

export function StubPage({ title, icon: Icon, description }: { title: string; icon: typeof FileStack; description: string }) {
  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader title={title} description={description} breadcrumbs={[{ label: 'Home', href: '/' }, { label: title }]} />
          <Card><CardContent><EmptyState icon={Icon} title={`${title} — planned`} description={description} /></CardContent></Card>
        </div>
      </Layout>
    </Protected>
  );
}

export function TemplatesPage() {
  return <StubPage title="Templates" icon={FileStack} description="Reusable agent and workflow templates will be listed here once the backend catalog exists." />;
}

export function DocsPage() {
  return <StubPage title="Documentation" icon={BookOpen} description="Product docs live in the repository under docs/. In-app guides arrive later." />;
}
