'use client';

import * as React from 'react';
import { useRouter } from 'next/navigation';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, Field } from '@/components/ui/form';
import { Dialog } from '@/components/ui/dialog';
import { toUserMessage } from '@/lib/api';
import { useWorkflowMutations } from '@/features/workflows/workflows-api';
import { TEMPLATES } from '@/features/workflows/serialize';

export function CreateWorkflowDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [name, setName] = React.useState('');
  const [description, setDescription] = React.useState('');
  const [templateId, setTemplateId] = React.useState('blank');
  const [error, setError] = React.useState<string | null>(null);
  const { create } = useWorkflowMutations();
  const router = useRouter();

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    const trimmed = name.trim();
    if (!trimmed) {
      setError('Give your workflow a name.');
      return;
    }
    try {
      const template = TEMPLATES.find((t) => t.id === templateId) ?? TEMPLATES[0];
      const wf = await create.mutateAsync({
        name: trimmed,
        description: description.trim() || undefined,
        definition: template.build(),
      });
      onClose();
      router.push(`/workflows/${wf.id}/edit`);
    } catch (err) {
      setError(toUserMessage(err));
    }
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="New workflow"
      description="Workflows start as drafts. Publish only when validation passes."
      footer={
        <>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={submit} loading={create.isPending}>Create & open builder</Button>
        </>
      }
    >
      <form className="space-y-4" onSubmit={submit}>
        {error && (
          <p className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive" role="alert">{error}</p>
        )}
        <Field label="Name" htmlFor="wf-name" required>
          <Input id="wf-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Support triage" autoFocus />
        </Field>
        <Field label="Description" htmlFor="wf-desc">
          <Input id="wf-desc" value={description} onChange={(e) => setDescription(e.target.value)} placeholder="What does this automate?" />
        </Field>
        <Field label="Template" htmlFor="wf-template">
          <Select id="wf-template" value={templateId} onChange={(e) => setTemplateId(e.target.value)}>
            {TEMPLATES.map((t) => (
              <option key={t.id} value={t.id}>{t.name} — {t.description}</option>
            ))}
          </Select>
        </Field>
      </form>
    </Dialog>
  );
}
