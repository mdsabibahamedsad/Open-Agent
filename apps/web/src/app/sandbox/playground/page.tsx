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
import {
  sandboxApi,
  Sandbox,
  decisionSummary,
  formatDuration,
} from '@/lib/sandbox';
import { FlaskConical, Ban } from 'lucide-react';

/**
 * Sandbox Execution Playground — controlled command execution with visible
 * policy decisions. Never a host shell: profile allowlists, workdir jail,
 * network deny-by-default, and redacted output.
 */
export default function SandboxPlaygroundPage() {
  const [profile, setProfile] = React.useState('TEST');
  const [command, setCommand] = React.useState('pytest tests/ -q');
  const [timeout, setTimeout] = React.useState(300);
  const [sandbox, setSandbox] = React.useState<Sandbox | null>(null);
  const [log, setLog] = React.useState<string[]>([]);

  const profiles = useQuery({ queryKey: ['sandbox-profiles'], queryFn: sandboxApi.listProfiles });

  const append = (line: string) =>
    setLog((l) => [...l.slice(-200), `${new Date().toLocaleTimeString()} ${line}`]);

  const run = useMutation({
    mutationFn: async () => {
      append(` creating sandbox (profile ${profile})…`);
      const sb = await sandboxApi.create({ profile, ttl_seconds: 1800 });
      setSandbox(sb);
      append(` sandbox ${sb.sandbox_id.slice(0, 18)}… ${sb.status}`);
      append(' starting…');
      const ready = await sandboxApi.start(sb.id);
      setSandbox(ready);
      append(` status ${ready.status} — executing with policy gates…`);
      const res = await sandboxApi.execute(sb.id, {
        command: command.trim(),
        workdir: '/workspace',
        timeout_seconds: timeout,
      });
      return res;
    },
    onSuccess: (res) => {
      append(` decision: ${decisionSummary(res as never)}`);
      append(` result: ${res.status} exit=${res.exit_code ?? '—'} duration=${formatDuration(res.duration_ms)}`);
      if (res.stdout_tail) append(` --- output (tail) ---\n${res.stdout_tail.slice(0, 3000)}`);
      if ((res as { reason?: string }).reason) append(` denied: ${(res as { reason?: string }).reason}`);
    },
    onError: (e) => append(` ERROR: ${e instanceof Error ? e.message : String(e)}`),
  });

  const teardown = useMutation({
    mutationFn: async () => {
      if (sandbox) await sandboxApi.destroy(sandbox.id);
    },
    onSuccess: () => {
      append(' sandbox destroyed; leases released, credentials revoked');
      setSandbox(null);
    },
  });

  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader
            title="Sandbox Playground"
            description="Try profile-gated commands in an isolated container. Policy decisions, risk, and resource usage are shown — secrets never are."
            breadcrumbs={[
              { label: 'Home', href: '/' },
              { label: 'Sandbox', href: '/sandbox' },
              { label: 'Playground' },
            ]}
          />

          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-3 rounded border p-4">
              <label className="block text-sm font-medium" htmlFor="profile">Profile</label>
              <select id="profile" value={profile} onChange={(e) => setProfile(e.target.value)}
                className="w-full rounded border px-2 py-1 text-sm" aria-label="Profile">
                {(profiles.data ?? []).map((p) => (
                  <option key={p.name} value={p.name}>
                    {p.name} — L{p.security_level}, net {p.network.mode}
                  </option>
                ))}
                {(profiles.data ?? []).length === 0 && <option value="TEST">TEST</option>}
              </select>
              <label className="block text-sm font-medium" htmlFor="command">Command (argv, no shell operators)</label>
              <Input id="command" value={command} onChange={(e) => setCommand(e.target.value)}
                placeholder="pytest tests/ -q" aria-label="Command" className="font-mono text-xs" />
              <label className="block text-sm font-medium" htmlFor="timeout">Timeout: {timeout}s</label>
              <input id="timeout" type="range" min={5} max={3600} value={timeout}
                onChange={(e) => setTimeout(Number(e.target.value))} className="w-full" aria-label="Timeout" />
              <PermissionGate permission="sandbox:execute">
                <div className="flex gap-2">
                  <Button onClick={() => run.mutate()} disabled={!command.trim() || run.isPending}>
                    <FlaskConical className="mr-2 h-4 w-4" />Run in sandbox
                  </Button>
                  {sandbox && (
                    <Button variant="outline" onClick={() => teardown.mutate()} disabled={teardown.isPending}>
                      <Ban className="mr-2 h-4 w-4" />Destroy sandbox
                    </Button>
                  )}
                </div>
              </PermissionGate>
              {sandbox && (
                <p className="flex items-center gap-2 text-sm">
                  Sandbox: <StatusBadge status={sandbox.status} />
                  <span className="font-mono text-xs">{sandbox.sandbox_id.slice(0, 18)}…</span>
                </p>
              )}
              {(() => {
                const found = (profiles.data ?? []).find((p) => p.name === profile);
                return found ? (
                  <p className="text-xs text-muted-foreground">
                    CPU {found.cpu} · {found.memory_mb}MB · {found.disk_mb}MB · {found.pids_limit} pids ·
                    timeout {found.timeout_seconds}s · fs {found.filesystem.mode}
                  </p>
                ) : null;
              })()}
            </div>
            <div className="rounded border p-4">
              <h3 className="mb-2 text-sm font-medium">
                Execution log <span className="text-muted-foreground">(policy metadata only)</span>
              </h3>
              <ul className="max-h-96 space-y-1 overflow-auto font-mono text-[11px] whitespace-pre-wrap" aria-live="polite">
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
