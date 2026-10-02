'use client';

import * as React from 'react';
import { useRouter } from 'next/navigation';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Field } from '@/components/ui/form';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { PermissionGate } from '@/components/PermissionGate';
import { useToast } from '@/components/ui/toast';
import { toUserMessage } from '@/lib/api';
import { useWorkflowMutations } from '@/features/workflows/workflows-api';
import { TEMPLATES } from '@/features/workflows/serialize';
import { cn } from '@/lib/utils';

export default function NewWorkflowPage() {
  const [name, setName] = React.useState('');
  const [description, setDescription] = React.useState('');
  const [templateId, setTemplateId] = React.useState('blank');
  const [error, setError] = React.useState<string | null>(null);
  const { create } = useWorkflowMutations();
  const { toast } = useToast();
  const router = useRouter();

  const submit = async (template: string) => {
    setError(null);
    const trimmed = name.trim();
    if (!trimmed) {
      setError('Give your workflow a name first.');
      return;
    }
    try {
      const t = TEMPLATES.find((x) => x.id === template) ?? TEMPLATES[0];
      const wf = await create.mutateAsync({
        name: trimmed,
        description: description.trim() || undefined,
        definition: t.build(),
      });
      toast({ kind: 'success', title: `Created “${wf.name}”` });
      router.push(`/workflows/${wf.id}/edit`);
    } catch (e) {
      setError(toUserMessage(e));
    }
  };

  return (
    <Protected>
      <Layout>
        <div className="oa-page max-w-3xl">
          <PageHeader
            title="New workflow"
            description="Name it, pick a starting point, and the builder opens next."
            breadcrumbs={[{ label: 'Home', href: '/' }, { label: 'Workflows', href: '/workflows' }, { label: 'New' }]}
          />
          <PermissionGate
            permission="workflow:create"
            fallback={<p className="rounded-lg border p-4 text-sm text-muted-foreground" role="alert">You need workflow:create permission to author workflows.</p>}
          >
            <Card>
              <CardContent className="space-y-4 pt-6">
                {error && (
                  <p className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive" role="alert">{error}</p>
                )}
                <Field label="Name" htmlFor="new-wf-name" required>
                  <Input id="new-wf-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Support triage" autoFocus />
                </Field>
                <Field label="Description" htmlFor="new-wf-desc">
                  <Input id="new-wf-desc" value={description} onChange={(e) => setDescription(e.target.value)} placeholder="What does this automate?" />
                </Field>
              </CardContent>
            </Card>
            <div className="grid gap-3 md:grid-cols-3" role="list" aria-label="Templates">
              {TEMPLATES.map((t) => (
                <Card
                  key={t.id}
                  role="listitem"
                  className={cn('cursor-pointer transition-colors hover:border-primary/60', templateId === t.id && 'border-primary')}
                  onClick={() => setTemplateId(t.id)}
                >
                  <CardHeader>
                    <CardTitle className="text-base">{t.name}</CardTitle>
                    <CardDescription>{t.description}</CardDescription>
                  </CardHeader>
                  <CardContent>
                    <Button size="sm" className="w-full" loading={create.isPending && templateId === t.id} onClick={(e) => { e.stopPropagation(); setTemplateId(t.id); submit(t.id); }}>
                      Use template
                    </Button>
                  </CardContent>
                </Card>
              ))}
            </div>
          </PermissionGate>
        </div>
      </Layout>
    </Protected>
  );
}
