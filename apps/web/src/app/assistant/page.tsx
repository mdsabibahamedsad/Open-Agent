'use client';

import { Suspense } from 'react';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { AssistantWorkspace } from '@/components/assistant/AssistantWorkspace';

export default function AssistantPage() {
  return (
    <Protected>
      <Layout>
        <Suspense fallback={null}>
          <AssistantWorkspace />
        </Suspense>
      </Layout>
    </Protected>
  );
}
