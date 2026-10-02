'use client';

import * as React from 'react';
import dynamic from 'next/dynamic';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { DataTable, Column } from '@/components/ui/table';
import { StatusBadge } from '@/components/ui/status';
import { PermissionGate } from '@/components/PermissionGate';
import {
  codeApi,
  CodingTask,
  CodeWorkspace,
  Repository,
  SearchMode,
  TaskEvent,
} from '@/lib/code';
import { Plus, RefreshCw, GitBranch, Search, FileCode2, X, Pause, Play } from 'lucide-react';

const errText = (e: unknown): string | null => (e ? ((e as Error).message ?? String(e)) : null);

// Monaco is client-only; never render it during SSR.
const MonacoEditor = dynamic(() => import('@monaco-editor/react').then((m) => m.Editor), {
  ssr: false,
  loading: () => <p className="text-xs text-muted-foreground">Loading editor…</p>,
});

function languageForPath(path: string): string {
  const ext = path.split('.').pop()?.toLowerCase() ?? '';
  const map: Record<string, string> = {
    ts: 'typescript', tsx: 'typescript', js: 'javascript', jsx: 'javascript',
    py: 'python', go: 'go', rs: 'rust', java: 'java', cs: 'csharp',
    c: 'c', h: 'c', cpp: 'cpp', hpp: 'cpp', sql: 'sql', html: 'html',
    css: 'css', json: 'json', yaml: 'yaml', yml: 'yaml', md: 'markdown',
    toml: 'ini', ini: 'ini', sh: 'shell', xml: 'xml',
  };
  return map[ext] ?? 'plaintext';
}

type Tab = 'tasks' | 'repositories' | 'workspaces' | 'search';

function useCodeData(tab: Tab) {
  const tasks = useQuery({
    queryKey: ['code-tasks'],
    queryFn: () => codeApi.listTasks(),
    enabled: tab === 'tasks',
  });
  const repositories = useQuery({
    queryKey: ['code-repositories'],
    queryFn: codeApi.listRepositories,
    enabled: tab === 'repositories' || tab === 'tasks',
  });
  const workspaces = useQuery({
    queryKey: ['code-workspaces'],
    queryFn: () => codeApi.listWorkspaces(),
    enabled: tab === 'workspaces' || tab === 'search',
  });
  return { tasks, repositories, workspaces };
}

// ---------------------------------------------------------------- tasks ---
function TaskDetail({ task, onClose }: { task: CodingTask; onClose: () => void }) {
  const qc = useQueryClient();
  const plan = useQuery({ queryKey: ['code-plan', task.id], queryFn: () => codeApi.taskPlan(task.id) });
  const diff = useQuery({ queryKey: ['code-diff', task.id], queryFn: () => codeApi.taskDiff(task.id) });
  const events = useQuery({ queryKey: ['code-events', task.id], queryFn: () => codeApi.taskEvents(task.id) });
  const [commitMsg, setCommitMsg] = React.useState('');
  const [prTitle, setPrTitle] = React.useState('');

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['code-tasks'] });
    qc.invalidateQueries({ queryKey: ['code-events', task.id] });
    qc.invalidateQueries({ queryKey: ['code-diff', task.id] });
  };

  const pause = useMutation({ mutationFn: () => codeApi.pauseTask(task.id), onSuccess: refresh });
  const resume = useMutation({ mutationFn: () => codeApi.resumeTask(task.id), onSuccess: refresh });
  const cancel = useMutation({ mutationFn: () => codeApi.cancelTask(task.id), onSuccess: refresh });
  const runReview = useMutation({
    mutationFn: () => codeApi.review({ task_id: task.id }),
    onSuccess: refresh,
  });
  const commit = useMutation({
    mutationFn: () => codeApi.commitTask(task.id, commitMsg.trim()),
    onSuccess: () => { setCommitMsg(''); refresh(); },
  });
  const push = useMutation({
    mutationFn: () => codeApi.pushTask(task.id, { approved: true }),
    onSuccess: refresh,
  });
  const preparePR = useMutation({
    mutationFn: () => codeApi.preparePR({ task_id: task.id, title: prTitle.trim() }),
    onSuccess: () => { setPrTitle(''); refresh(); },
  });
  const planTests = useMutation({ mutationFn: () => codeApi.planTests(task.id) });

  const findings = (runReview.data as { findings?: Array<{
    severity: string; file?: string; line?: number; category: string;
    finding: string; suggested_fix?: string;
  }> } | undefined)?.findings ?? [];

  return (
    <div className="space-y-4 rounded border p-4" aria-label="Task detail">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="font-medium">{task.objective}</p>
          <p className="text-xs text-muted-foreground">
            {task.task_id} · branch {task.branch ?? '—'} · step {task.current_step}/{task.max_steps} · risk {task.risk_level}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <StatusBadge status={task.status} />
          <Button size="sm" variant="ghost" onClick={onClose} aria-label="Close task detail"><X className="h-3 w-3" /></Button>
        </div>
      </div>

      <PermissionGate permission="code:execute">
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="outline" onClick={() => pause.mutate()} disabled={pause.isPending}>
            <Pause className="mr-1 h-3 w-3" />Pause
          </Button>
          <Button size="sm" variant="outline" onClick={() => resume.mutate()} disabled={resume.isPending}>
            <Play className="mr-1 h-3 w-3" />Resume
          </Button>
          <Button size="sm" variant="outline" onClick={() => cancel.mutate()} disabled={cancel.isPending}>
            Cancel
          </Button>
          <Button size="sm" variant="outline" onClick={() => runReview.mutate()} disabled={runReview.isPending}>
            Review diff
          </Button>
          <Button size="sm" variant="outline" onClick={() => planTests.mutate()} disabled={planTests.isPending}>
            Plan tests
          </Button>
        </div>
        {planTests.data && (
          <div className="rounded bg-muted p-2 text-xs">
            <p className="font-medium">Test plan</p>
            <p>Targeted: {(planTests.data.targeted ?? []).join(', ') || '—'}</p>
            <p>Regression: {(planTests.data.regression ?? []).join(', ') || '—'}</p>
          </div>
        )}
      </PermissionGate>

      <div className="grid gap-4 md:grid-cols-2">
        <div>
          <h4 className="mb-1 text-sm font-medium">Plan</h4>
          {plan.isLoading && <p className="text-xs text-muted-foreground">Loading plan…</p>}
          {plan.error && <p className="text-xs text-red-600">{errText(plan.error)}</p>}
          <ol className="list-decimal space-y-1 pl-5 text-xs">
            {(plan.data?.steps ?? []).map((s) => (
              <li key={s.step}><span className="font-medium">{s.title}</span>{s.detail ? ` — ${s.detail}` : ''}</li>
            ))}
          </ol>
        </div>
        <div>
          <h4 className="mb-1 text-sm font-medium">Events</h4>
          {events.isLoading && <p className="text-xs text-muted-foreground">Loading events…</p>}
          <ul className="max-h-48 space-y-1 overflow-auto text-xs">
            {(events.data ?? []).map((e: TaskEvent) => (
              <li key={e.id} className="font-mono">
                <span className="text-muted-foreground">{new Date(e.timestamp).toLocaleTimeString()}</span> {e.type}
              </li>
            ))}
          </ul>
        </div>
      </div>

      <div>
        <h4 className="mb-1 text-sm font-medium">Diff</h4>
        {diff.isLoading && <p className="text-xs text-muted-foreground">Loading diff…</p>}
        {diff.error && <p className="text-xs text-red-600">{errText(diff.error)}</p>}
        {typeof diff.data?.diff === 'string' && diff.data.diff.length > 0 ? (
          <pre className="max-h-64 overflow-auto rounded bg-muted p-2 font-mono text-[11px] whitespace-pre-wrap">
            {diff.data.diff.slice(0, 20000)}
          </pre>
        ) : (
          <p className="text-xs text-muted-foreground">No changes yet.</p>
        )}
      </div>

      {findings.length > 0 && (
        <div>
          <h4 className="mb-1 text-sm font-medium">Review findings</h4>
          <ul className="space-y-1 text-xs">
            {findings.map((f, i) => (
              <li key={i} className="rounded border p-2">
                <span className="font-medium">[{f.severity}] {f.category}</span>
                {f.file && <span className="font-mono text-muted-foreground"> {f.file}{f.line ? `:${f.line}` : ''}</span>}
                <p>{f.finding}</p>
                {f.suggested_fix && <p className="text-muted-foreground">Fix: {f.suggested_fix}</p>}
              </li>
            ))}
          </ul>
        </div>
      )}

      <PermissionGate permission="code:execute">
        <div className="space-y-2 border-t pt-3">
          <div className="flex gap-2">
            <Input value={commitMsg} onChange={(e) => setCommitMsg(e.target.value)}
              placeholder="Commit message" aria-label="Commit message" />
            <Button size="sm" onClick={() => commitMsg.trim() && commit.mutate()}
              disabled={!commitMsg.trim() || commit.isPending}>Commit</Button>
          </div>
          <div className="flex gap-2">
            <Input value={prTitle} onChange={(e) => setPrTitle(e.target.value)}
              placeholder="PR title" aria-label="PR title" />
            <Button size="sm" variant="outline" onClick={() => prTitle.trim() && preparePR.mutate()}
              disabled={!prTitle.trim() || preparePR.isPending}>Prepare PR</Button>
            <Button size="sm" variant="outline" onClick={() => push.mutate()} disabled={push.isPending}>
              <GitBranch className="mr-1 h-3 w-3" />Push (approved)
            </Button>
          </div>
          <p className="text-[11px] text-muted-foreground">
            Commits run secret scan + diff review. Push is approval-gated; protected branches stay blocked.
          </p>
        </div>
      </PermissionGate>
    </div>
  );
}

// ---------------------------------------------------------- repositories ---
function ConnectRepositoryForm({ onDone }: { onDone: () => void }) {
  const qc = useQueryClient();
  const [provider, setProvider] = React.useState('github');
  const [name, setName] = React.useState('');
  const [fullName, setFullName] = React.useState('');
  const [cloneUrl, setCloneUrl] = React.useState('');
  const [credentialRef, setCredentialRef] = React.useState('');

  const create = useMutation({
    mutationFn: () =>
      codeApi.createRepository({
        provider: provider as 'github',
        name: name.trim(),
        full_name: fullName.trim() || name.trim(),
        clone_url: cloneUrl.trim(),
        ...(credentialRef.trim() ? { credential_ref: credentialRef.trim() } : {}),
      }),
    onSuccess: () => {
      setName(''); setFullName(''); setCloneUrl(''); setCredentialRef('');
      qc.invalidateQueries({ queryKey: ['code-repositories'] });
      onDone();
    },
  });

  return (
    <PermissionGate permission="code:execute">
      <div className="grid gap-2 rounded border p-3 md:grid-cols-2">
        <label className="text-xs">Provider
          <select value={provider} onChange={(e) => setProvider(e.target.value)}
            className="mt-1 w-full rounded border px-2 py-1" aria-label="Provider">
            <option value="github">GitHub</option>
            <option value="gitlab">GitLab</option>
            <option value="bitbucket">Bitbucket</option>
            <option value="generic">Generic Git</option>
            <option value="local">Local</option>
          </select>
        </label>
        <label className="text-xs">Name
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="billing-api" aria-label="Name" />
        </label>
        <label className="text-xs">Full name
          <Input value={fullName} onChange={(e) => setFullName(e.target.value)} placeholder="acme/billing-api" aria-label="Full name" />
        </label>
        <label className="text-xs">Clone URL
          <Input value={cloneUrl} onChange={(e) => setCloneUrl(e.target.value)} placeholder="https://… or file path" aria-label="Clone URL" />
        </label>
        <label className="text-xs md:col-span-2">Credential ref (never paste raw tokens)
          <Input value={credentialRef} onChange={(e) => setCredentialRef(e.target.value)}
            placeholder="cred_…" aria-label="Credential ref" type="password" />
        </label>
        <div className="md:col-span-2">
          <Button size="sm" onClick={() => create.mutate()}
            disabled={!name.trim() || !cloneUrl.trim() || create.isPending}>
            <Plus className="mr-1 h-3 w-3" />Connect repository
          </Button>
          {create.error && <p className="mt-1 text-xs text-red-600">{errText(create.error)}</p>}
        </div>
      </div>
    </PermissionGate>
  );
}

// ------------------------------------------------------------ workspaces ---
function WorkspaceFiles({ workspace }: { workspace: CodeWorkspace }) {
  const [prefix, setPrefix] = React.useState('');
  const [selected, setSelected] = React.useState<string | null>(null);
  const files = useQuery({
    queryKey: ['code-files', workspace.id, prefix],
    queryFn: () => codeApi.listFiles(workspace.id, prefix),
  });
  const content = useQuery({
    queryKey: ['code-file', workspace.id, selected],
    queryFn: () => codeApi.readFile(workspace.id, selected as string),
    enabled: selected !== null,
  });

  return (
    <div className="grid gap-4 md:grid-cols-2">
      <div>
        <div className="mb-2 flex gap-2">
          <Input value={prefix} onChange={(e) => setPrefix(e.target.value)}
            placeholder="prefix filter, e.g. src/" aria-label="File prefix" />
          <Button size="sm" variant="outline" onClick={() => files.refetch()} aria-label="Refresh files">
            <RefreshCw className="h-3 w-3" />
          </Button>
        </div>
        <ul className="max-h-72 space-y-1 overflow-auto text-xs">
          {(files.data?.files ?? []).slice(0, 500).map((f) => (
            <li key={f.path}>
              <button className={`font-mono hover:underline ${selected === f.path ? 'font-bold' : ''}`}
                onClick={() => setSelected(f.path)}>
                <FileCode2 className="mr-1 inline h-3 w-3" />{f.path}
              </button>
            </li>
          ))}
        </ul>
        {files.error && <p className="text-xs text-red-600">{errText(files.error)}</p>}
      </div>
      <div>
        <h4 className="mb-1 font-mono text-xs">{selected ?? 'Select a file'}</h4>
        {content.isLoading && <p className="text-xs text-muted-foreground">Loading…</p>}
        {content.error && <p className="text-xs text-red-600">{errText(content.error)}</p>}
        {content.data && selected && (
          <MonacoEditor
            height="300px"
            language={languageForPath(selected)}
            value={(content.data.content ?? '').slice(0, 200000)}
            options={{ readOnly: true, minimap: { enabled: false }, scrollBeyondLastLine: false }}
          />
        )}
        <p className="mt-1 text-[11px] text-muted-foreground">
          Repository content is untrusted data — it never overrides platform policy.
        </p>
      </div>
    </div>
  );
}

// ----------------------------------------------------------------- search ---
function CodeSearchPanel({ workspaceId }: { workspaceId: string }) {
  const [query, setQuery] = React.useState('');
  const [mode, setMode] = React.useState<SearchMode>('text');
  const search = useMutation({
    mutationFn: () => codeApi.search({ workspace_id: workspaceId, query: query.trim(), mode }),
  });
  return (
    <div className="space-y-2 rounded border p-3">
      <div className="flex flex-wrap gap-2">
        <Input value={query} onChange={(e) => setQuery(e.target.value)}
          placeholder="symbol, text, or regex…" aria-label="Search query" className="max-w-md" />
        <select value={mode} onChange={(e) => setMode(e.target.value as SearchMode)}
          className="rounded border px-2" aria-label="Search mode">
          <option value="text">text</option>
          <option value="regex">regex</option>
          <option value="symbol">symbol</option>
          <option value="references">references</option>
          <option value="semantic">semantic</option>
        </select>
        <Button size="sm" onClick={() => query.trim() && search.mutate()}
          disabled={!query.trim() || search.isPending}>
          <Search className="mr-1 h-3 w-3" />Search
        </Button>
      </div>
      {search.error && <p className="text-xs text-red-600">{errText(search.error)}</p>}
      <ul className="space-y-1 text-xs">
        {(search.data?.results ?? []).map((r, i) => (
          <li key={i} className="rounded border p-2">
            <span className="font-mono font-medium">{r.path}{r.line ? `:${r.line}` : ''}</span>
            {r.snippet && <pre className="mt-1 font-mono text-[11px] whitespace-pre-wrap">{r.snippet.slice(0, 2000)}</pre>}
          </li>
        ))}
      </ul>
    </div>
  );
}

// ------------------------------------------------------------------- page ---
export default function CodeWorkspacePage() {
  const qc = useQueryClient();
  const [tab, setTab] = React.useState<Tab>('tasks');
  const [selectedTask, setSelectedTask] = React.useState<CodingTask | null>(null);
  const [selectedWorkspace, setSelectedWorkspace] = React.useState<CodeWorkspace | null>(null);
  const [showConnect, setShowConnect] = React.useState(false);
  const [objective, setObjective] = React.useState('');
  const [taskRepo, setTaskRepo] = React.useState('');
  const [branchName, setBranchName] = React.useState('');
  const { tasks, repositories, workspaces } = useCodeData(tab);

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['code-tasks'] });
    qc.invalidateQueries({ queryKey: ['code-repositories'] });
    qc.invalidateQueries({ queryKey: ['code-workspaces'] });
  };

  const createTask = useMutation({
    mutationFn: () =>
      codeApi.createTask({ repository_id: taskRepo, objective: objective.trim(), max_steps: 50 }),
    onSuccess: () => { setObjective(''); invalidate(); },
  });
  const createWorkspace = useMutation({
    mutationFn: (repository_id: string) => codeApi.createWorkspace({ repository_id }),
    onSuccess: invalidate,
  });
  const deleteWorkspace = useMutation({
    mutationFn: (id: string) => codeApi.deleteWorkspace(id),
    onSuccess: () => { setSelectedWorkspace(null); invalidate(); },
  });
  const syncRepo = useMutation({ mutationFn: (id: string) => codeApi.syncRepository(id), onSuccess: invalidate });
  const connectRepo = useMutation({ mutationFn: (id: string) => codeApi.connectRepository(id), onSuccess: invalidate });
  const deleteRepo = useMutation({ mutationFn: (id: string) => codeApi.deleteRepository(id), onSuccess: invalidate });
  const createBranch = useMutation({
    mutationFn: ({ ws, name }: { ws: string; name: string }) => codeApi.createBranch(ws, name),
    onSuccess: invalidate,
  });

  const taskCols: Column<CodingTask>[] = [
    { key: 'objective', header: 'Objective', render: (r) => <span className="font-medium">{r.objective.slice(0, 90)}</span> },
    { key: 'step', header: 'Step', render: (r) => <span className="text-muted-foreground">{r.current_step}/{r.max_steps}</span> },
    { key: 'risk', header: 'Risk', render: (r) => <span className="text-muted-foreground">{r.risk_level}</span> },
    { key: 'status', header: 'Status', render: (r) => <StatusBadge status={r.status} /> },
    {
      key: 'actions', header: 'Detail', render: (r) => (
        <Button size="sm" variant="outline" onClick={() => setSelectedTask(r)}>Open</Button>
      ),
    },
  ];

  const repoCols: Column<Repository>[] = [
    { key: 'full_name', header: 'Repository', render: (r) => <span className="font-medium">{r.full_name}</span> },
    { key: 'provider', header: 'Provider', render: (r) => <span className="text-muted-foreground">{r.provider} · {r.default_branch}</span> },
    { key: 'status', header: 'Status', render: (r) => <StatusBadge status={r.status} /> },
    {
      key: 'actions', header: 'Actions', render: (r) => (
        <PermissionGate permission="code:execute">
          <div className="flex gap-1">
            <Button size="sm" variant="outline" onClick={() => connectRepo.mutate(r.id)}>Connect</Button>
            <Button size="sm" variant="outline" onClick={() => syncRepo.mutate(r.id)}>Sync</Button>
            <Button size="sm" variant="outline" onClick={() => createWorkspace.mutate(r.id)}>Workspace</Button>
            <Button size="sm" variant="outline" onClick={() => deleteRepo.mutate(r.id)}>Delete</Button>
          </div>
        </PermissionGate>
      ),
    },
  ];

  const wsCols: Column<CodeWorkspace>[] = [
    { key: 'branch', header: 'Branch', render: (r) => <span className="font-mono text-xs">{r.branch}</span> },
    { key: 'status', header: 'Status', render: (r) => <StatusBadge status={r.status} /> },
    {
      key: 'actions', header: 'Detail', render: (r) => (
        <Button size="sm" variant="outline" onClick={() => setSelectedWorkspace(r)}>Open</Button>
      ),
    },
  ];

  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader
            title="Code Workspace"
            description="AI software-engineering workspace: isolated checkouts, bounded coding tasks, patch-first edits, tests and review. Execution stays inside the sandbox boundary."
            breadcrumbs={[{ label: 'Home', href: '/' }, { label: 'Code' }]}
            actions={
              <Button variant="outline" onClick={() => { setTab('tasks'); }}>
                <Plus className="mr-2 h-4 w-4" />New coding task
              </Button>
            }
          />

          <div className="flex gap-2 border-b pb-2" role="tablist" aria-label="Code sections">
            {(['tasks', 'repositories', 'workspaces', 'search'] as const).map((t) => (
              <Button key={t} variant={tab === t ? 'default' : 'ghost'} size="sm" role="tab"
                aria-selected={tab === t} onClick={() => setTab(t)}>
                {t[0].toUpperCase() + t.slice(1)}
              </Button>
            ))}
            <Button variant="ghost" size="sm" onClick={invalidate} aria-label="Refresh"><RefreshCw className="h-3 w-3" /></Button>
          </div>

          {tab === 'tasks' && (
            <div className="space-y-4">
              <PermissionGate permission="code:execute">
                <div className="flex flex-wrap gap-2">
                  <select value={taskRepo} onChange={(e) => setTaskRepo(e.target.value)}
                    className="rounded border px-2 py-1 text-sm" aria-label="Task repository">
                    <option value="">Select repository…</option>
                    {(repositories.data ?? []).map((r) => (
                      <option key={r.id} value={r.id}>{r.full_name}</option>
                    ))}
                  </select>
                  <Input value={objective} onChange={(e) => setObjective(e.target.value)}
                    placeholder="Objective, e.g. Fix failing auth tests and open a PR" aria-label="Task objective"
                    className="min-w-[300px] flex-1" />
                  <Button size="sm" onClick={() => objective.trim() && taskRepo && createTask.mutate()}
                    disabled={!objective.trim() || !taskRepo || createTask.isPending}>
                    <Plus className="mr-1 h-3 w-3" />Create task
                  </Button>
                </div>
                {createTask.error && <p className="text-xs text-red-600">{errText(createTask.error)}</p>}
              </PermissionGate>
              <DataTable columns={taskCols} rows={tasks.data ?? []} keyOf={(r) => r.id}
                loading={tasks.isLoading} error={errText(tasks.error)} onRetry={() => tasks.refetch()} />
              {selectedTask && <TaskDetail task={selectedTask} onClose={() => setSelectedTask(null)} />}
            </div>
          )}

          {tab === 'repositories' && (
            <div className="space-y-4">
              <Button size="sm" variant="outline" onClick={() => setShowConnect((v) => !v)}>
                {showConnect ? 'Hide connect form' : 'Connect repository'}
              </Button>
              {showConnect && <ConnectRepositoryForm onDone={() => setShowConnect(false)} />}
              <DataTable columns={repoCols} rows={repositories.data ?? []} keyOf={(r) => r.id}
                loading={repositories.isLoading} error={errText(repositories.error)} onRetry={() => repositories.refetch()} />
            </div>
          )}

          {tab === 'workspaces' && (
            <div className="space-y-4">
              <DataTable columns={wsCols} rows={workspaces.data ?? []} keyOf={(r) => r.id}
                loading={workspaces.isLoading} error={errText(workspaces.error)} onRetry={() => workspaces.refetch()} />
              {selectedWorkspace && (
                <div className="space-y-3 rounded border p-4">
                  <div className="flex items-center justify-between">
                    <p className="font-mono text-xs">branch {selectedWorkspace.branch} · {selectedWorkspace.status}</p>
                    <PermissionGate permission="code:execute">
                      <div className="flex gap-2">
                        <Input value={branchName} onChange={(e) => setBranchName(e.target.value)}
                          placeholder="new branch name" aria-label="New branch name" className="max-w-[200px]" />
                        <Button size="sm" variant="outline"
                          onClick={() => branchName.trim() && createBranch.mutate({ ws: selectedWorkspace.id, name: branchName.trim() })}
                          disabled={!branchName.trim()}>
                          <GitBranch className="mr-1 h-3 w-3" />Branch
                        </Button>
                        <Button size="sm" variant="outline" onClick={() => deleteWorkspace.mutate(selectedWorkspace.id)}>
                          Delete
                        </Button>
                      </div>
                    </PermissionGate>
                  </div>
                  <WorkspaceFiles workspace={selectedWorkspace} />
                </div>
              )}
            </div>
          )}

          {tab === 'search' && (
            <div className="space-y-4">
              {(workspaces.data ?? []).map((w) => (
                <div key={w.id}>
                  <p className="mb-1 font-mono text-xs text-muted-foreground">workspace {w.workspace_id.slice(0, 12)}… · {w.branch}</p>
                  <CodeSearchPanel workspaceId={w.id} />
                </div>
              ))}
              {(workspaces.data ?? []).length === 0 && (
                <p className="text-sm text-muted-foreground">Create a workspace first to enable search.</p>
              )}
            </div>
          )}
        </div>
      </Layout>
    </Protected>
  );
}
