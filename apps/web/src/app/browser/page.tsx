'use client';

import * as React from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { DataTable, Column } from '@/components/ui/table';
import { StatusBadge } from '@/components/ui/status';
import { PermissionGate } from '@/components/PermissionGate';
import { browserApi, BrowserSession, BrowserTask, BrowserProfile, DomainPolicy } from '@/lib/browser';
import { Plus, Pause, Play, X, RefreshCw, Globe, ShieldAlert } from 'lucide-react';

function useBrowserData() {
  const sessions = useQuery({ queryKey: ['browser-sessions'], queryFn: browserApi.listSessions });
  const tasks = useQuery({ queryKey: ['browser-tasks'], queryFn: browserApi.listTasks });
  const profiles = useQuery({ queryKey: ['browser-profiles'], queryFn: browserApi.listProfiles });
  const policies = useQuery({ queryKey: ['browser-policies'], queryFn: browserApi.listPolicies });
  return { sessions, tasks, profiles, policies };
}

const errText = (e: unknown): string | null => (e ? ((e as Error).message ?? String(e)) : null);

export default function BrowserWorkspacePage() {
  const qc = useQueryClient();
  const { sessions, tasks, profiles, policies } = useBrowserData();
  const [tab, setTab] = React.useState<'sessions' | 'tasks' | 'profiles' | 'policies'>('sessions');
  const [newDomain, setNewDomain] = React.useState('');
  const [newAction, setNewAction] = React.useState('DENY');

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['browser-sessions'] });
    qc.invalidateQueries({ queryKey: ['browser-tasks'] });
    qc.invalidateQueries({ queryKey: ['browser-profiles'] });
    qc.invalidateQueries({ queryKey: ['browser-policies'] });
  };

  const createSession = useMutation({ mutationFn: () => browserApi.createSession({ headless: true }), onSuccess: invalidate });
  const closeSession = useMutation({ mutationFn: (id: string) => browserApi.closeSession(id), onSuccess: invalidate });
  const pauseSession = useMutation({ mutationFn: (id: string) => browserApi.pauseSession(id), onSuccess: invalidate });
  const resumeSession = useMutation({ mutationFn: (id: string) => browserApi.resumeSession(id), onSuccess: invalidate });
  const cancelTask = useMutation({ mutationFn: (id: string) => browserApi.cancelTask(id), onSuccess: invalidate });
  const createPolicy = useMutation({
    mutationFn: () => browserApi.createPolicy({ domain: newDomain.trim().toLowerCase(), action: newAction }),
    onSuccess: () => { setNewDomain(''); invalidate(); },
  });

  const sessionCols: Column<BrowserSession>[] = [
    { key: 'id', header: 'Session', render: (r) => <span className="font-mono text-xs">{r.session_id.slice(0, 24)}…</span> },
    { key: 'provider', header: 'Provider', render: (r) => <span className="text-muted-foreground">{r.provider} · {r.headless ? 'headless' : 'headed'}</span> },
    { key: 'status', header: 'Status', render: (r) => <StatusBadge status={r.status} /> },
    {
      key: 'actions', header: 'Actions', render: (r) => (
        <div className="flex gap-1">
          <Button size="sm" variant="outline" onClick={() => pauseSession.mutate(r.session_id)} aria-label="Pause session"><Pause className="h-3 w-3" /></Button>
          <Button size="sm" variant="outline" onClick={() => resumeSession.mutate(r.session_id)} aria-label="Resume session"><Play className="h-3 w-3" /></Button>
          <Button size="sm" variant="outline" onClick={() => closeSession.mutate(r.session_id)} aria-label="Close session"><X className="h-3 w-3" /></Button>
        </div>
      ),
    },
  ];

  const taskCols: Column<BrowserTask>[] = [
    { key: 'objective', header: 'Objective', render: (r) => <span className="font-medium">{r.objective.slice(0, 80)}</span> },
    { key: 'step', header: 'Step', render: (r) => <span className="text-muted-foreground">{r.current_step}/{r.max_steps}</span> },
    { key: 'status', header: 'Status', render: (r) => <StatusBadge status={r.status} /> },
    {
      key: 'actions', header: 'Actions', render: (r) => (
        <Button size="sm" variant="outline" onClick={() => cancelTask.mutate(r.id)}>Cancel</Button>
      ),
    },
  ];

  const profileCols: Column<BrowserProfile>[] = [
    { key: 'name', header: 'Profile', render: (r) => <span className="font-medium">{r.display_name}</span> },
    { key: 'type', header: 'Type', render: (r) => <span className="text-muted-foreground">{r.profile_type} · {r.browser_type}</span> },
  ];

  const policyCols: Column<DomainPolicy>[] = [
    { key: 'domain', header: 'Domain', render: (r) => <span className="font-mono text-xs">{r.domain}</span> },
    {
      key: 'action', header: 'Policy', render: (r) => (
        <span className={r.action === 'DENY' ? 'text-red-600 font-medium' : r.action === 'CONFIRM' ? 'text-amber-600 font-medium' : 'text-green-600'}>
          {r.action}
        </span>
      ),
    },
  ];

  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader
            title="Browser Workspace"
            description="Controlled browser sessions, tasks, profiles and domain policies. Web content is untrusted; high-risk actions require approval."
            breadcrumbs={[{ label: 'Home', href: '/' }, { label: 'Browser' }]}
            actions={
              <PermissionGate permission="browser:execute">
                <Button onClick={() => createSession.mutate()} disabled={createSession.isPending}>
                  <Plus className="mr-2 h-4 w-4" />New session
                </Button>
              </PermissionGate>
            }
          />

          <div className="flex gap-2 border-b pb-2" role="tablist" aria-label="Browser sections">
            {(['sessions', 'tasks', 'profiles', 'policies'] as const).map((t) => (
              <Button key={t} variant={tab === t ? 'default' : 'ghost'} size="sm" role="tab" aria-selected={tab === t} onClick={() => setTab(t)}>
                {t === 'sessions' && <Globe className="mr-1 h-3 w-3" />}
                {t === 'policies' && <ShieldAlert className="mr-1 h-3 w-3" />}
                {t[0].toUpperCase() + t.slice(1)}
              </Button>
            ))}
            <Button variant="ghost" size="sm" onClick={invalidate} aria-label="Refresh"><RefreshCw className="h-3 w-3" /></Button>
          </div>

          {tab === 'sessions' && (
            <DataTable columns={sessionCols} rows={sessions.data ?? []} keyOf={(r) => r.id}
              loading={sessions.isLoading} error={errText(sessions.error)} onRetry={() => sessions.refetch()} />
          )}
          {tab === 'tasks' && (
            <DataTable columns={taskCols} rows={tasks.data ?? []} keyOf={(r) => r.id}
              loading={tasks.isLoading} error={errText(tasks.error)} onRetry={() => tasks.refetch()} />
          )}
          {tab === 'profiles' && (
            <DataTable columns={profileCols} rows={profiles.data ?? []} keyOf={(r) => r.id}
              loading={profiles.isLoading} error={errText(profiles.error)} onRetry={() => profiles.refetch()} />
          )}
          {tab === 'policies' && (
            <div className="space-y-4">
              <PermissionGate permission="browser:execute">
                <div className="flex gap-2">
                  <Input value={newDomain} onChange={(e) => setNewDomain(e.target.value)} placeholder="example.com" aria-label="Domain" className="max-w-xs" />
                  <select value={newAction} onChange={(e) => setNewAction(e.target.value)} aria-label="Policy action" className="rounded border px-2">
                    <option value="DENY">DENY</option>
                    <option value="ALLOW">ALLOW</option>
                    <option value="CONFIRM">CONFIRM</option>
                  </select>
                  <Button onClick={() => newDomain.trim() && createPolicy.mutate()} disabled={!newDomain.trim() || createPolicy.isPending}>
                    Add policy
                  </Button>
                </div>
              </PermissionGate>
              <DataTable columns={policyCols} rows={policies.data ?? []} keyOf={(r) => r.id}
                loading={policies.isLoading} error={errText(policies.error)} onRetry={() => policies.refetch()} />
            </div>
          )}
        </div>
      </Layout>
    </Protected>
  );
}
