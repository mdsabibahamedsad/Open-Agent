'use client';

import * as React from 'react';
import { useParams } from 'next/navigation';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { StatusBadge } from '@/components/ui/status';
import { DataTable, Column } from '@/components/ui/table';
import { ConfirmDialog } from '@/components/ui/dialog';
import { useOrganization } from '@/context/OrganizationContext';
import {
  getExtension, listDeployments, validateExtension, testExtension,
  packageExtension, publishExtension, deployExtension, disableExtension,
  quarantineExtension, rollbackExtension, signExtension, artifactMeta,
  ExtVersion, DeploymentRow,
} from '@/lib/developer';
import { toUserMessage } from '@/lib/api';

export default function ExtensionDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const { currentOrgId } = useOrganization();
  const qc = useQueryClient();
  const [tab, setTab] = React.useState('overview');
  const [busy, setBusy] = React.useState<string | null>(null);
  const [result, setResult] = React.useState<string | null>(null);
  const [resultError, setResultError] = React.useState<string | null>(null);
  const [confirm, setConfirm] = React.useState<null | 'disable' | 'quarantine' | 'publish'>(null);
  const [quarantineReason, setQuarantineReason] = React.useState('');
  const [deployVersion, setDeployVersion] = React.useState('');
  const [deployEnv, setDeployEnv] = React.useState('staging');
  const [pubkey, setPubkey] = React.useState('');
  const [installationId, setInstallationId] = React.useState('');

  const detail = useQuery({
    queryKey: ['dev-extension', currentOrgId, id],
    queryFn: () => getExtension(currentOrgId ?? '', id),
    enabled: !!currentOrgId && !!id,
  });
  const deployments = useQuery({
    queryKey: ['dev-deployments', currentOrgId],
    queryFn: () => listDeployments(currentOrgId ?? ''),
    enabled: !!currentOrgId,
  });
  const artifact = useQuery({
    queryKey: ['dev-artifact', currentOrgId, id],
    queryFn: () => artifactMeta(currentOrgId ?? '', id),
    enabled: false,
  });

  const extDeployments = (deployments.data ?? []).filter((d) => d.extension === id);
  const versions: ExtVersion[] = detail.data?.versions ?? [];

  async function run(label: string, fn: () => Promise<unknown>) {
    setBusy(label);
    setResult(null);
    setResultError(null);
    try {
      const out = await fn();
      setResult(JSON.stringify(out, null, 2));
      await qc.invalidateQueries({ queryKey: ['dev-extension'] });
      await qc.invalidateQueries({ queryKey: ['dev-deployments'] });
    } catch (err) {
      setResultError(toUserMessage(err));
    } finally {
      setBusy(null);
      setConfirm(null);
    }
  }

  const org = currentOrgId ?? '';
  const verCols: Column<ExtVersion>[] = [
    { key: 'v', header: 'Version', render: (r) => <span className="font-medium">{r.version}</span> },
    { key: 'd', header: 'Digest', render: (r) => <span className="oa-code">{r.digest ? `${r.digest.slice(0, 16)}…` : '—'}</span> },
  ];
  const depCols: Column<DeploymentRow>[] = [
    { key: 'env', header: 'Environment', render: (r) => <span>{r.environment}</span> },
    { key: 'status', header: 'Status', render: (r) => <StatusBadge status={r.status} /> },
    { key: 'stages', header: 'Stages', render: (r) => <span className="text-xs text-muted-foreground">{(r.stages ?? []).join(' → ') || '—'}</span> },
  ];
  const dangerous = confirm === 'disable' || confirm === 'quarantine';

  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader
            title={detail.data?.slug ?? 'Extension'}
            description={detail.data ? `${detail.data.type} · trust ${detail.data.trust ?? 'unknown'}` : undefined}
            breadcrumbs={[{ label: 'Developer', href: '/developer' }, { label: 'Extensions', href: '/developer/extensions' }, { label: detail.data?.slug ?? id }]}
            actions={detail.data ? <StatusBadge status={detail.data.lifecycle} /> : undefined}
          />
          {detail.isLoading && <p className="text-sm text-muted-foreground">Loading extension…</p>}
          {detail.error && <p className="text-sm text-destructive" role="alert">{toUserMessage(detail.error)}</p>}
          {detail.data?.quarantine.at && (
            <p className="rounded-md border border-destructive/40 p-3 text-sm" role="alert">
              Quarantined: {detail.data.quarantine.reason ?? 'no reason recorded'} (installs and deploys are refused).
            </p>
          )}

          {detail.data && (
            <Tabs value={tab} onValueChange={setTab}>
              <TabsList aria-label="Extension sections">
                <TabsTrigger value="overview">Overview</TabsTrigger>
                <TabsTrigger value="versions">Versions</TabsTrigger>
                <TabsTrigger value="security">Security</TabsTrigger>
                <TabsTrigger value="deploy">Deployments</TabsTrigger>
              </TabsList>

              <TabsContent value="overview">
                <Card>
                  <CardHeader>
                    <CardTitle className="text-base">Lifecycle actions</CardTitle>
                    <CardDescription>Each button calls the real backend endpoint. Dangerous actions ask for confirmation.</CardDescription>
                  </CardHeader>
                  <CardContent className="flex flex-wrap gap-2">
                    <Button size="sm" variant="outline" disabled={busy !== null} onClick={() => run('validate', () => validateExtension(org, id, {}))}>
                      {busy === 'validate' ? 'Validating…' : 'Validate'}
                    </Button>
                    <Button size="sm" variant="outline" disabled={busy !== null} onClick={() => run('test', () => testExtension(org, id, { suite: 'contract' }))}>
                      {busy === 'test' ? 'Testing…' : 'Test'}
                    </Button>
                    <Button size="sm" variant="outline" disabled={busy !== null} onClick={() => run('package', () => packageExtension(org, id, {}))}>
                      {busy === 'package' ? 'Packaging…' : 'Package'}
                    </Button>
                    <Button size="sm" variant="outline" disabled={busy !== null} onClick={() => artifact.refetch()}>
                      Artifact metadata
                    </Button>
                    <Button size="sm" disabled={busy !== null} onClick={() => run('deploy', () => deployExtension(org, id, { version: deployVersion || versions[0]?.version || '1.0.0', environment: deployEnv }))}>
                      {busy === 'deploy' ? 'Deploying…' : 'Deploy'}
                    </Button>
                    <Button size="sm" variant="outline" onClick={() => setConfirm('publish')}>Publish…</Button>
                    <Button size="sm" variant="destructive" onClick={() => setConfirm('disable')}>Disable…</Button>
                    <Button size="sm" variant="destructive" onClick={() => setConfirm('quarantine')}>Quarantine…</Button>
                  </CardContent>
                </Card>
                {(result || resultError || artifact.data) && (
                  <Card>
                    <CardHeader><CardTitle className="text-base">Server result</CardTitle></CardHeader>
                    <CardContent>
                      {resultError && <p className="text-sm text-destructive" role="alert">{resultError}</p>}
                      {result && <pre className="max-h-96 overflow-auto rounded bg-muted p-3 text-xs" aria-label="Action result">{result}</pre>}
                      {artifact.data && <pre className="mt-2 overflow-auto rounded bg-muted p-3 text-xs" aria-label="Artifact metadata">{JSON.stringify(artifact.data, null, 2)}</pre>}
                    </CardContent>
                  </Card>
                )}
              </TabsContent>

              <TabsContent value="versions">
                <DataTable columns={verCols} rows={versions} keyOf={(r) => r.id}
                  emptyTitle="No versions yet" emptyDescription="Create a version via POST …/versions, then validate it." />
              </TabsContent>

              <TabsContent value="security">
                <div className="grid gap-4 md:grid-cols-2">
                  <Card>
                    <CardHeader><CardTitle className="text-base">Validation &amp; scan</CardTitle>
                      <CardDescription>Validate checks manifest + sources without executing. Publish runs the secret scan gate.</CardDescription></CardHeader>
                    <CardContent className="space-y-2">
                      <Button size="sm" variant="outline" disabled={busy !== null} onClick={() => run('validate', () => validateExtension(org, id, {}))}>
                        Run validation
                      </Button>
                      <Button size="sm" variant="outline" disabled={busy !== null} onClick={() => run('test', () => testExtension(org, id, { suite: 'all' }))}>
                        Run full test suite
                      </Button>
                      <p className="text-xs text-muted-foreground">Publishing is blocked when secrets are detected unless an explicit audited override reason is supplied.</p>
                    </CardContent>
                  </Card>
                  <Card>
                    <CardHeader><CardTitle className="text-base">Offline signing</CardTitle>
                      <CardDescription>Private keys never leave your machine. Server returns the digest; you sign offline.</CardDescription></CardHeader>
                    <CardContent className="space-y-2">
                      <Input label="Ed25519 public key" value={pubkey} onChange={(e) => setPubkey(e.target.value)} placeholder="base64 public key" />
                      <Button size="sm" variant="outline" disabled={busy !== null || !pubkey}
                        onClick={() => run('sign', () => signExtension(org, id, { public_key: pubkey }))}>
                        Register key &amp; get digest
                      </Button>
                    </CardContent>
                  </Card>
                </div>
              </TabsContent>

              <TabsContent value="deploy">
                <div className="grid gap-4 md:grid-cols-[320px_1fr]">
                  <Card>
                    <CardHeader><CardTitle className="text-base">Deploy / rollback</CardTitle></CardHeader>
                    <CardContent className="space-y-2">
                      <Input label="Version" value={deployVersion} onChange={(e) => setDeployVersion(e.target.value)} placeholder={versions[0]?.version ?? '1.0.0'} />
                      <Input label="Environment" value={deployEnv} onChange={(e) => setDeployEnv(e.target.value)} placeholder="staging" />
                      <Button size="sm" disabled={busy !== null} onClick={() => run('deploy', () => deployExtension(org, id, { version: deployVersion || versions[0]?.version || '1.0.0', environment: deployEnv }))}>
                        Deploy version
                      </Button>
                      <Input label="Installation ID (for rollback)" value={installationId} onChange={(e) => setInstallationId(e.target.value)} placeholder="installation uuid" />
                      <Button size="sm" variant="outline" disabled={busy !== null || !installationId}
                        onClick={() => run('rollback', () => rollbackExtension(org, id, installationId))}>
                        Rollback installation
                      </Button>
                    </CardContent>
                  </Card>
                  <DataTable columns={depCols} rows={extDeployments} keyOf={(r) => r.id}
                    loading={deployments.isLoading}
                    error={deployments.error ? toUserMessage(deployments.error) : null}
                    onRetry={() => deployments.refetch()}
                    emptyTitle="No deployments for this extension"
                    emptyDescription="Deploy a version to start the validate → test → scan → sign → health-check pipeline." />
                </div>
              </TabsContent>
            </Tabs>
          )}
        </div>

        <ConfirmDialog
          open={confirm === 'publish'} onClose={() => setConfirm(null)}
          title="Publish extension"
          description="The security scan gate runs first. Secrets block publishing unless removed."
          confirmLabel="Publish now"
          onConfirm={() => run('publish', () => publishExtension(org, id, {}))}
        />
        <ConfirmDialog
          open={confirm === 'disable'} onClose={() => setConfirm(null)}
          title="Disable extension"
          description="Installs keep working but new installs are discouraged. Continue?"
          confirmLabel="Disable" danger
          onConfirm={() => run('disable', () => disableExtension(org, id))}
        />
        <div aria-live="polite">
          <ConfirmDialog
            open={confirm === 'quarantine'} onClose={() => setConfirm(null)}
            title="Quarantine extension"
            description="Emergency action: installs and deploys are refused immediately. A reason is required."
            confirmLabel={dangerous ? 'Quarantine' : 'Confirm'} danger
            onConfirm={() => run('quarantine', () => quarantineExtension(org, id, quarantineReason || 'manual quarantine from portal'))}
          />
        </div>
        {confirm === 'quarantine' && (
          <div className="fixed bottom-6 left-1/2 z-[60] w-[min(92vw,420px)] -translate-x-1/2 rounded-lg border bg-card p-4 shadow-lg">
            <label htmlFor="quarantine-reason" className="mb-1 block text-sm font-medium">Quarantine reason (required)</label>
            <Input id="quarantine-reason" value={quarantineReason} onChange={(e) => setQuarantineReason(e.target.value)} placeholder="e.g. malicious network egress observed" />
          </div>
        )}
      </Layout>
    </Protected>
  );
}
