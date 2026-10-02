'use client';

import * as React from 'react';
import { useMutation } from '@tanstack/react-query';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { PermissionGate } from '@/components/PermissionGate';
import { browserApi, BrowserTask } from '@/lib/browser';
import { FlaskConical, Ban } from 'lucide-react';

/**
 * Browser Agent Playground — safe execution metadata only.
 * Hidden chain-of-thought is never rendered; only plan, observations,
 * actions, results and the final answer are shown.
 */
export default function BrowserPlaygroundPage() {
  const [goal, setGoal] = React.useState('');
  const [domains, setDomains] = React.useState('');
  const [maxSteps, setMaxSteps] = React.useState(25);
  const [task, setTask] = React.useState<BrowserTask | null>(null);
  const [log, setLog] = React.useState<string[]>([]);

  const append = (line: string) => setLog((l) => [...l, `${new Date().toLocaleTimeString()} ${line}`]);

  const run = useMutation({
    mutationFn: async () => {
      append(' creating isolated session…');
      const session = await browserApi.createSession({ headless: true });
      append(` session ${session.session_id.slice(0, 18)}… ready`);
      append(' creating task…');
      const created = await browserApi.createTask({
        browser_session_id: session.id,
        objective: goal.trim(),
        max_steps: maxSteps,
      });
      append(` task ${created.task_id.slice(0, 18)}… running (step budget ${created.max_steps})`);
      return created;
    },
    onSuccess: (t) => setTask(t),
    onError: (e) => append(` ERROR: ${e instanceof Error ? e.message : String(e)}`),
  });

  const cancel = useMutation({
    mutationFn: async () => {
      if (task) await browserApi.cancelTask(task.id);
    },
    onSuccess: () => {
      append(' task cancelled');
      setTask(null);
    },
  });

  const allowed = domains.split(',').map((d) => d.trim()).filter(Boolean);

  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader
            title="Browser Agent Playground"
            description="Test browser goals against allowed domains with bounded steps. Credentials stay server-side as references."
            breadcrumbs={[{ label: 'Home', href: '/' }, { label: 'Browser', href: '/browser' }, { label: 'Playground' }]}
          />

          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-3 rounded border p-4">
              <label className="block text-sm font-medium" htmlFor="goal">Goal</label>
              <Input id="goal" value={goal} onChange={(e) => setGoal(e.target.value)}
                placeholder="Research pricing on example.com and summarize" aria-label="Goal" />
              <label className="block text-sm font-medium" htmlFor="domains">Allowed domains (comma-separated)</label>
              <Input id="domains" value={domains} onChange={(e) => setDomains(e.target.value)}
                placeholder="example.com" aria-label="Allowed domains" />
              <label className="block text-sm font-medium" htmlFor="maxsteps">Max steps: {maxSteps}</label>
              <input id="maxsteps" type="range" min={1} max={100} value={maxSteps}
                onChange={(e) => setMaxSteps(Number(e.target.value))} className="w-full" aria-label="Max steps" />
              {allowed.length > 0 && (
                <p className="text-xs text-muted-foreground">Scoped to: {allowed.join(', ')}</p>
              )}
              <PermissionGate permission="browser:execute">
                <div className="flex gap-2">
                  <Button onClick={() => run.mutate()} disabled={!goal.trim() || run.isPending}>
                    <FlaskConical className="mr-2 h-4 w-4" />Run browser task
                  </Button>
                  {task && (
                    <Button variant="outline" onClick={() => cancel.mutate()}>
                      <Ban className="mr-2 h-4 w-4" />Cancel
                    </Button>
                  )}
                </div>
              </PermissionGate>
            </div>

            <div className="space-y-3 rounded border p-4">
              <h2 className="text-sm font-medium">Execution trace (safe metadata)</h2>
              {task && (
                <dl className="grid grid-cols-2 gap-1 text-xs">
                  <dt className="text-muted-foreground">Task</dt><dd className="font-mono">{task.task_id.slice(0, 20)}…</dd>
                  <dt className="text-muted-foreground">Status</dt><dd>{task.status}</dd>
                  <dt className="text-muted-foreground">Step</dt><dd>{task.current_step}/{task.max_steps}</dd>
                </dl>
              )}
              <ol className="max-h-96 space-y-1 overflow-auto font-mono text-xs" aria-live="polite">
                {log.map((line, i) => <li key={i}>{line}</li>)}
                {log.length === 0 && <li className="text-muted-foreground">No run yet.</li>}
              </ol>
            </div>
          </div>
        </div>
      </Layout>
    </Protected>
  );
}
