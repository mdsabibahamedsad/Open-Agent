'use client';

import * as React from 'react';
import { useQuery, useMutation } from '@tanstack/react-query';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { StatusBadge } from '@/components/ui/status';
import { PermissionGate } from '@/components/PermissionGate';
import { codeApi, CodingTask } from '@/lib/code';
import { FlaskConical, Ban } from 'lucide-react';

/**
 * Code Agent Playground — bounded task execution with live event tail.
 * Hidden chain-of-thought is never rendered; only plan, events,
 * diffs and the final result are shown.
 */
export default function CodePlaygroundPage() {
  const [repositoryId, setRepositoryId] = React.useState('');
  const [objective, setObjective] = React.useState('');
  const [maxSteps, setMaxSteps] = React.useState(25);
  const [task, setTask] = React.useState<CodingTask | null>(null);
  const [log, setLog] = React.useState<string[]>([]);

  const repos = useQuery({ queryKey: ['code-repositories'], queryFn: codeApi.listRepositories });

  const append = (line: string) =>
    setLog((l) => [...l.slice(-200), `${new Date().toLocaleTimeString()} ${line}`]);

  const run = useMutation({
    mutationFn: async () => {
      append(' creating bounded coding task…');
      const created = await codeApi.createTask({
        repository_id: repositoryId,
        objective: objective.trim(),
        max_steps: maxSteps,
        risk_level: 'MEDIUM',
      });
      append(` task ${created.task_id} queued (step budget ${created.max_steps})`);
      return created;
    },
    onSuccess: (t) => {
      setTask(t);
      append(' polling task status…');
      void poll(t.id);
    },
    onError: (e) => append(` ERROR: ${e instanceof Error ? e.message : String(e)}`),
  });

  const poll = async (id: string) => {
    for (let i = 0; i < 30; i++) {
      await new Promise((r) => setTimeout(r, 2000));
      try {
        const t = await codeApi.getTask(id);
        setTask(t);
        if (['SUCCEEDED', 'FAILED', 'CANCELLED', 'TIMED_OUT', 'READY_FOR_PR'].includes(t.status)) {
          append(` task ${t.status} at step ${t.current_step}/${t.max_steps}`);
          const events = await codeApi.taskEvents(id);
          events.slice(-8).forEach((e) => append(` event ${e.type}`));
          try {
            const d = await codeApi.taskDiff(id);
            const files = d.files ?? [];
            append(` diff: ${files.length} file(s) changed`);
          } catch {
            append(' diff unavailable');
          }
          return;
        }
      } catch (e) {
        append(` poll error: ${e instanceof Error ? e.message : String(e)}`);
        return;
      }
    }
    append(' poll budget exhausted — check the Code workspace for status');
  };

  const cancel = useMutation({
    mutationFn: async () => {
      if (task) await codeApi.cancelTask(task.id);
    },
    onSuccess: () => {
      append(' task cancelled');
      setTask(null);
    },
  });

  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader
            title="Code Agent Playground"
            description="Try a coding objective against a connected repository with bounded steps. Patches stay inspectable; push stays approval-gated."
            breadcrumbs={[
              { label: 'Home', href: '/' },
              { label: 'Code', href: '/code' },
              { label: 'Playground' },
            ]}
          />

          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-3 rounded border p-4">
              <label className="block text-sm font-medium" htmlFor="repo">Repository</label>
              <select id="repo" value={repositoryId} onChange={(e) => setRepositoryId(e.target.value)}
                className="w-full rounded border px-2 py-1 text-sm" aria-label="Repository">
                <option value="">Select repository…</option>
                {(repos.data ?? []).map((r) => (
                  <option key={r.id} value={r.id}>{r.full_name} ({r.provider})</option>
                ))}
              </select>
              <label className="block text-sm font-medium" htmlFor="objective">Objective</label>
              <Input id="objective" value={objective} onChange={(e) => setObjective(e.target.value)}
                placeholder="Fix the failing session-validation test and add a regression test"
                aria-label="Objective" />
              <label className="block text-sm font-medium" htmlFor="maxsteps">Max steps: {maxSteps}</label>
              <input id="maxsteps" type="range" min={1} max={100} value={maxSteps}
                onChange={(e) => setMaxSteps(Number(e.target.value))} className="w-full" aria-label="Max steps" />
              <PermissionGate permission="code:execute">
                <div className="flex gap-2">
                  <Button onClick={() => run.mutate()} disabled={!repositoryId || !objective.trim() || run.isPending}>
                    <FlaskConical className="mr-2 h-4 w-4" />Run task
                  </Button>
                  {task && (
                    <Button variant="outline" onClick={() => cancel.mutate()} disabled={cancel.isPending}>
                      <Ban className="mr-2 h-4 w-4" />Cancel
                    </Button>
                  )}
                </div>
              </PermissionGate>
              {task && (
                <p className="flex items-center gap-2 text-sm">
                  Status: <StatusBadge status={task.status} />
                  <span className="text-muted-foreground">{task.current_step}/{task.max_steps}</span>
                </p>
              )}
            </div>
            <div className="rounded border p-4">
              <h3 className="mb-2 text-sm font-medium">Execution events</h3>
              <ul className="max-h-96 space-y-1 overflow-auto font-mono text-[11px]" aria-live="polite">
                {log.map((line, i) => (
                  <li key={i}>{line}</li>
                ))}
                {log.length === 0 && <li className="text-muted-foreground">No events yet.</li>}
              </ul>
            </div>
          </div>
        </div>
      </Layout>
    </Protected>
  );
}
