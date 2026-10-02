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
import {
  sandboxApi,
  Sandbox,
  SandboxExecution,
  SandboxProfile,
  decisionSummary,
  formatBytes,
  formatDuration,
  isTerminalExecutionStatus,
  normalizeExecutionStatus,
  riskTone,
} from '@/lib/sandbox';
import { Plus, RefreshCw, Square, Trash2, Play, Terminal } from 'lucide-react';

const errText = (e: unknown): string | null => (e ? ((e as Error).message ?? String(e)) : null);

type Tab = 'sandboxes' | 'profiles' | 'security';

const toneClass: Record<string, string> = {
  ok: 'text-green-600',
  warn: 'text-amber-600',
  bad: 'text-red-600',
  critical: 'text-red-700 font-bold',
};

function ExecutionPanel({ sandbox }: { sandbox: Sandbox }) {
  const qc = useQueryClient();
  const [command, setCommand] = React.useState('pytest tests/ -q');
  const [workdir, setWorkdir] = React.useState('/workspace');
  const [result, setResult] = React.useState<(SandboxExecution & { reason?: string }) | null>(null);

  const executions = useQuery({
    queryKey: ['sandbox-executions', sandbox.id],
    queryFn: () => sandboxApi.listExecutions(sandbox.id),
  });
  const events = useQuery({
    queryKey: ['sandbox-events', sandbox.id],
    queryFn: () => sandboxApi.events(sandbox.id),
  });
  const artifacts = useQuery({
    queryKey: ['sandbox-artifacts', sandbox.id],
    queryFn: () => sandboxApi.artifacts(sandbox.id),
  });

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['sandbox-executions', sandbox.id] });
    qc.invalidateQueries({ queryKey: ['sandbox-events', sandbox.id] });
    qc.invalidateQueries({ queryKey: ['sandbox-artifacts', sandbox.id] });
    qc.invalidateQueries({ queryKey: ['sandboxes'] });
  };

  const run = useMutation({
    mutationFn: () =>
      sandboxApi.execute(sandbox.id, { command: command.trim(), workdir: workdir.trim() || '/workspace' }),
    onSuccess: (r) => { setResult(r); refresh(); },
    onError: (e) => setResult({ status: 'SANDBOX_ERROR', reason: errText(e) ?? 'failed' } as never),
  });
  const cancel = useMutation({
    mutationFn: (executionId: string) => sandboxApi.cancelExecution(sandbox.id, executionId),
    onSuccess: refresh,
  });

  const latest: (SandboxExecution & { reason?: string }) | null =
    result ?? executions.data?.[0] ?? null;

  return (
    <div className="space-y-4 rounded border p-4" aria-label="Sandbox console">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-xs">{sandbox.sandbox_id.slice(0, 20)}…</span>
        <StatusBadge status={sandbox.status} />
        <span className="text-xs text-muted-foreground">
          {sandbox.profile} · {sandbox.provider} · {sandbox.pinned ? 'pinned image' : 'UNPINNED image'}
        </span>
      </div>

      <PermissionGate permission="sandbox:execute">
        <div className="space-y-2 border-t pt-3">
          <h4 className="text-sm font-medium"><Terminal className="mr-1 inline h-3 w-3" />Command / Execution</h4>
          <div className="flex flex-wrap gap-2">
            <Input value={command} onChange={(e) => setCommand(e.target.value)}
              placeholder="pytest tests/ -q" aria-label="Command" className="min-w-[280px] flex-1 font-mono text-xs" />
            <Input value={workdir} onChange={(e) => setWorkdir(e.target.value)}
              placeholder="/workspace" aria-label="Working directory" className="max-w-[180px] font-mono text-xs" />
            <Button size="sm" onClick={() => command.trim() && run.mutate()}
              disabled={!command.trim() || run.isPending}>
              <Play className="mr-1 h-3 w-3" />Execute
            </Button>
          </div>
          <p className="text-[11px] text-muted-foreground">
            Structured argv only — shell operators are rejected. Network is denied unless the profile
            allows it and the deployment provides filtered egress. Secrets travel as refs only.
          </p>
        </div>
      </PermissionGate>

      {latest && (
        <div className="space-y-2 border-t pt-3">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <StatusBadge status={normalizeExecutionStatus(latest.status)} />
            <span className={toneClass[riskTone(latest.risk_level ?? 'CRITICAL')]}>
              Risk: {latest.risk_level ?? '—'}
            </span>
            <span className="text-muted-foreground">
              exit {latest.exit_code ?? '—'} · {formatDuration(latest.duration_ms)}
              {latest.oom_killed ? ' · OOM-KILLED' : ''}
              {latest.peak_memory_mb ? ` · peak ${latest.peak_memory_mb} MB` : ''}
            </span>
            {!isTerminalExecutionStatus(latest.status) && latest.id && (
              <PermissionGate permission="sandbox:execute">
                <Button size="sm" variant="outline"
                  onClick={() => cancel.mutate(latest.id)}>
                  <Square className="mr-1 h-3 w-3" />Cancel
                </Button>
              </PermissionGate>
            )}
          </div>
          <p className="text-xs text-muted-foreground">{decisionSummary(latest as never)}</p>
          {(latest.risk_reasons ?? []).length > 0 && (
            <ul className="list-disc pl-5 text-[11px] text-muted-foreground">
              {(latest.risk_reasons ?? []).map((r, i) => <li key={i}>{r}</li>)}
            </ul>
          )}
          {latest.stdout_tail && (
            <pre className="max-h-64 overflow-auto rounded bg-muted p-2 font-mono text-[11px] whitespace-pre-wrap"
              aria-label="Terminal output">
              {latest.stdout_tail.slice(0, 20000)}
            </pre>
          )}
          {latest.reason && <p className="text-xs text-red-600">{latest.reason}</p>}
        </div>
      )}

      <div className="grid gap-4 border-t pt-3 md:grid-cols-2">
        <div>
          <h4 className="mb-1 text-sm font-medium">Executions</h4>
          <ul className="max-h-48 space-y-1 overflow-auto text-xs">
            {(executions.data ?? []).map((e) => (
              <li key={e.id} className="flex items-center gap-2 font-mono">
                <StatusBadge status={normalizeExecutionStatus(e.status)} />
                <span className="truncate">{e.command.slice(0, 60)}</span>
                <span className="text-muted-foreground">{formatDuration(e.duration_ms)}</span>
              </li>
            ))}
            {(executions.data ?? []).length === 0 && (
              <li className="text-muted-foreground">No executions yet.</li>
            )}
          </ul>
          {executions.error && <p className="text-xs text-red-600">{errText(executions.error)}</p>}
        </div>
        <div>
          <h4 className="mb-1 text-sm font-medium">Resource monitor</h4>
          <dl className="grid grid-cols-2 gap-1 text-xs">
            <dt className="text-muted-foreground">CPU</dt><dd>{String(sandbox.resource_config.cpu ?? '—')}</dd>
            <dt className="text-muted-foreground">Memory</dt>
            <dd>{sandbox.resource_config.memory_mb ? `${sandbox.resource_config.memory_mb} MB` : '—'}</dd>
            <dt className="text-muted-foreground">Disk</dt>
            <dd>{sandbox.resource_config.disk_mb ? `${sandbox.resource_config.disk_mb} MB` : '—'}</dd>
            <dt className="text-muted-foreground">PIDs</dt><dd>{String(sandbox.resource_config.pids_limit ?? '—')}</dd>
            <dt className="text-muted-foreground">Expires</dt>
            <dd>{sandbox.expires_at ? new Date(sandbox.expires_at).toLocaleString() : '—'}</dd>
          </dl>
          <h4 className="mb-1 mt-3 text-sm font-medium">Artifacts</h4>
          <ul className="space-y-1 text-xs">
            {(artifacts.data ?? []).map((a) => (
              <li key={a.id} className="font-mono">
                {a.name} <span className="text-muted-foreground">{formatBytes(a.size_bytes)} · ref {a.ref.slice(0, 24)}…</span>
              </li>
            ))}
            {(artifacts.data ?? []).length === 0 && (
              <li className="text-muted-foreground">No artifacts. Container paths are never exposed.</li>
            )}
          </ul>
        </div>
      </div>

      <div className="border-t pt-3">
        <h4 className="mb-1 text-sm font-medium">Events / Audit</h4>
        <ul className="max-h-40 space-y-1 overflow-auto font-mono text-[11px]">
          {(events.data ?? []).map((e) => (
            <li key={e.id}>{e.type} <span className="text-muted-foreground">{JSON.stringify(e.payload).slice(0, 160)}</span></li>
          ))}
          {(events.data ?? []).length === 0 && <li className="text-muted-foreground">No events yet.</li>}
        </ul>
      </div>
    </div>
  );
}

export default function SandboxConsolePage() {
  const qc = useQueryClient();
  const [tab, setTab] = React.useState<Tab>('sandboxes');
  const [selected, setSelected] = React.useState<Sandbox | null>(null);
  const [profile, setProfile] = React.useState('TEST');

  const sandboxes = useQuery({
    queryKey: ['sandboxes'],
    queryFn: () => sandboxApi.list(),
    enabled: tab === 'sandboxes',
  });
  const profiles = useQuery({
    queryKey: ['sandbox-profiles'],
    queryFn: sandboxApi.listProfiles,
    enabled: tab === 'profiles',
  });
  const secCheck = useQuery({
    queryKey: ['sandbox-security-check'],
    queryFn: sandboxApi.securityCheck,
    enabled: tab === 'security',
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['sandboxes'] });
    qc.invalidateQueries({ queryKey: ['sandbox-profiles'] });
  };

  const create = useMutation({
    mutationFn: () => sandboxApi.create({ profile }),
    onSuccess: invalidate,
  });
  const start = useMutation({
    mutationFn: (id: string) => sandboxApi.start(id),
    onSuccess: invalidate,
  });
  const stop = useMutation({
    mutationFn: (id: string) => sandboxApi.stop(id),
    onSuccess: invalidate,
  });
  const destroy = useMutation({
    mutationFn: (id: string) => sandboxApi.destroy(id),
    onSuccess: () => { setSelected(null); invalidate(); },
  });

  const sbCols: Column<Sandbox>[] = [
    { key: 'id', header: 'Sandbox', render: (r) => <span className="font-mono text-xs">{r.sandbox_id.slice(0, 18)}…</span> },
    { key: 'profile', header: 'Profile', render: (r) => <span className="text-muted-foreground">{r.profile} · {r.provider}</span> },
    { key: 'image', header: 'Image', render: (r) => <span className="font-mono text-xs">{r.image}{r.pinned ? '' : ' (unpinned)'}</span> },
    { key: 'status', header: 'Status', render: (r) => <StatusBadge status={r.status} /> },
    {
      key: 'actions', header: 'Actions', render: (r) => (
        <div className="flex gap-1">
          <Button size="sm" variant="outline" onClick={() => setSelected(r)}>Open</Button>
          <PermissionGate permission="sandbox:execute">
            <Button size="sm" variant="outline" onClick={() => start.mutate(r.id)}>Start</Button>
            <Button size="sm" variant="outline" onClick={() => stop.mutate(r.id)}>Stop</Button>
            <Button size="sm" variant="outline" onClick={() => destroy.mutate(r.id)} aria-label="Destroy">
              <Trash2 className="h-3 w-3" />
            </Button>
          </PermissionGate>
        </div>
      ),
    },
  ];

  const profileCols: Column<SandboxProfile>[] = [
    { key: 'name', header: 'Profile', render: (r) => <span className="font-medium">{r.name}</span> },
    {
      key: 'limits', header: 'Limits',
      render: (r) => <span className="text-muted-foreground">CPU {r.cpu} · {r.memory_mb}MB · {r.disk_mb}MB · {r.pids_limit} pids · {r.timeout_seconds}s</span>,
    },
    {
      key: 'policy', header: 'Policy',
      render: (r) => <span className="text-muted-foreground">L{r.security_level} · net {r.network.mode} · fs {r.filesystem.mode}</span>,
    },
  ];

  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader
            title="Sandbox Console"
            description="Isolated execution environments for agents, tools, and workflows. Untrusted code never touches the host — every run is policy-gated, resourced-capped, and audited."
            breadcrumbs={[{ label: 'Home', href: '/' }, { label: 'Sandbox' }]}
          />

          <div className="flex gap-2 border-b pb-2" role="tablist" aria-label="Sandbox sections">
            {(['sandboxes', 'profiles', 'security'] as const).map((t) => (
              <Button key={t} variant={tab === t ? 'default' : 'ghost'} size="sm" role="tab"
                aria-selected={tab === t} onClick={() => setTab(t)}>
                {t[0].toUpperCase() + t.slice(1)}
              </Button>
            ))}
            <Button variant="ghost" size="sm" onClick={invalidate} aria-label="Refresh"><RefreshCw className="h-3 w-3" /></Button>
          </div>

          {tab === 'sandboxes' && (
            <div className="space-y-4">
              <PermissionGate permission="sandbox:execute">
                <div className="flex flex-wrap gap-2">
                  <select value={profile} onChange={(e) => setProfile(e.target.value)}
                    className="rounded border px-2 py-1 text-sm" aria-label="Profile">
                    {['READ_ONLY', 'TEST', 'LINT', 'TYPECHECK', 'BUILD', 'PACKAGE', 'DEVELOPMENT', 'DATA_PROCESSING', 'CUSTOM'].map((p) => (
                      <option key={p} value={p}>{p}</option>
                    ))}
                  </select>
                  <Button size="sm" onClick={() => create.mutate()} disabled={create.isPending}>
                    <Plus className="mr-1 h-3 w-3" />Create sandbox
                  </Button>
                </div>
                {create.error && <p className="text-xs text-red-600">{errText(create.error)}</p>}
              </PermissionGate>
              <DataTable columns={sbCols} rows={sandboxes.data ?? []} keyOf={(r) => r.id}
                loading={sandboxes.isLoading} error={errText(sandboxes.error)} onRetry={() => sandboxes.refetch()} />
              {selected && <ExecutionPanel sandbox={selected} />}
            </div>
          )}

          {tab === 'profiles' && (
            <DataTable columns={profileCols} rows={profiles.data ?? []} keyOf={(r) => r.name}
              loading={profiles.isLoading} error={errText(profiles.error)} onRetry={() => profiles.refetch()} />
          )}

          {tab === 'security' && (
            <div className="space-y-2 rounded border p-4 text-xs">
              <h4 className="text-sm font-medium">Production security check</h4>
              {secCheck.isLoading && <p className="text-muted-foreground">Running checks…</p>}
              {secCheck.error && <p className="text-red-600">{errText(secCheck.error)}</p>}
              {secCheck.data && (
                <pre className="overflow-auto rounded bg-muted p-2 font-mono text-[11px] whitespace-pre-wrap">
                  {JSON.stringify(secCheck.data, null, 2).slice(0, 8000)}
                </pre>
              )}
              <p className="text-muted-foreground">
                Docker socket mounts, privileged mode, broad host mounts, and production
                local-fallback are denied by policy and covered by automated tests.
              </p>
            </div>
          )}
        </div>
      </Layout>
    </Protected>
  );
}
