'use client';

import * as React from 'react';
import { useRouter } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { useOrganization } from '@/context/OrganizationContext';
import {
  getSdkMeta, listProjects, createExtension, createVersion,
  EXTENSION_TYPE_DESCRIPTIONS, DEFAULT_PERMISSIONS, permissionHint,
} from '@/lib/developer';
import { toUserMessage } from '@/lib/api';

const STEPS = ['Select type', 'Configure manifest', 'Capabilities', 'Review'];

export default function NewExtensionPage() {
  const router = useRouter();
  const { currentOrgId } = useOrganization();
  const [step, setStep] = React.useState(0);
  const [extType, setExtType] = React.useState('tool');
  const [slug, setSlug] = React.useState('');
  const [displayName, setDisplayName] = React.useState('');
  const [description, setDescription] = React.useState('');
  const [version, setVersion] = React.useState('1.0.0');
  const [license, setLicense] = React.useState('MIT');
  const [projectId, setProjectId] = React.useState('');
  const [perms, setPerms] = React.useState<string[]>([...DEFAULT_PERMISSIONS]);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const sdk = useQuery({ queryKey: ['dev-sdk'], queryFn: getSdkMeta, staleTime: 300_000 });
  const projects = useQuery({
    queryKey: ['dev-projects', currentOrgId],
    queryFn: () => listProjects(currentOrgId ?? ''),
    enabled: !!currentOrgId,
  });
  const catalog = sdk.data?.permissions ?? {};
  const allPerms = Object.keys(catalog).sort();

  function togglePerm(p: string) {
    setPerms((prev) => (prev.includes(p) ? prev.filter((x) => x !== p) : [...prev, p]));
  }

  const manifestPreview = {
    manifest_version: sdk.data?.manifest_version ?? '1',
    name: slug || '<slug>',
    version,
    extension_type: extType,
    display_name: displayName || slug || '<name>',
    description,
    license,
    permissions: perms,
    compatibility: { extension_api: sdk.data?.extension_api ?? '1.x' },
  };

  async function onCreate() {
    if (!currentOrgId) return;
    setBusy(true);
    setError(null);
    try {
      const ext = await createExtension(currentOrgId, {
        slug: slug.trim(), extension_type: extType,
        display_name: displayName.trim() || slug.trim(),
        description: description.trim(), project_id: projectId || undefined, license,
      });
      await createVersion(currentOrgId, ext.id, {
        version: version.trim(),
        manifest: { ...manifestPreview, name: slug.trim(), version: version.trim(), license },
        changelog: 'Initial version from portal builder',
      });
      router.push(`/developer/extensions/${ext.id}`);
    } catch (err) {
      setError(toUserMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader
            title="Extension Builder"
            description="Scaffold a new extension with least-privilege permissions. Review security implications before creating."
            breadcrumbs={[{ label: 'Developer', href: '/developer' }, { label: 'Extensions', href: '/developer/extensions' }, { label: 'New' }]}
          />
          <ol className="flex flex-wrap gap-2" aria-label="Builder steps">
            {STEPS.map((s, i) => (
              <li key={s}>
                <Badge variant={i === step ? 'default' : i < step ? 'success' : 'outline'}>{i + 1}. {s}</Badge>
              </li>
            ))}
          </ol>

          {step === 0 && (
            <Card>
              <CardHeader><CardTitle className="text-base">Select extension type</CardTitle>
                <CardDescription>One canonical registry — pick the kind that matches your capability.</CardDescription></CardHeader>
              <CardContent>
                <div className="grid gap-2 md:grid-cols-2" role="radiogroup" aria-label="Extension type">
                  {(sdk.data?.extension_types ?? Object.keys(EXTENSION_TYPE_DESCRIPTIONS)).map((t) => (
                    <button
                      key={t} role="radio" aria-checked={extType === t} onClick={() => setExtType(t)}
                      className={`rounded-lg border p-3 text-left text-sm hover:border-primary ${extType === t ? 'border-primary ring-1 ring-primary' : ''}`}
                    >
                      <span className="font-medium">{t}</span>
                      <span className="block text-muted-foreground">{EXTENSION_TYPE_DESCRIPTIONS[t] ?? ''}</span>
                    </button>
                  ))}
                </div>
                <div className="mt-4 flex gap-2">
                  <Button onClick={() => setStep(1)}>Continue</Button>
                </div>
              </CardContent>
            </Card>
          )}

          {step === 1 && (
            <Card>
              <CardHeader><CardTitle className="text-base">Configure manifest</CardTitle></CardHeader>
              <CardContent className="grid max-w-xl gap-3">
                <Input label="Slug (lowercase, unique)" value={slug} onChange={(e) => setSlug(e.target.value)} placeholder="my-extension" required />
                <Input label="Display name" value={displayName} onChange={(e) => setDisplayName(e.target.value)} placeholder="My Extension" />
                <Input label="Version (semver)" value={version} onChange={(e) => setVersion(e.target.value)} placeholder="1.0.0" required />
                <Input label="License (required)" value={license} onChange={(e) => setLicense(e.target.value)} placeholder="MIT" required />
                <label className="grid gap-1 text-sm font-medium">Description
                  <textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={3}
                    className="rounded-md border border-input bg-background px-3 py-2 text-sm" placeholder="What does this extension do?" />
                </label>
                <label className="grid gap-1 text-sm font-medium">Project (optional)
                  <select value={projectId} onChange={(e) => setProjectId(e.target.value)}
                    className="rounded-md border border-input bg-background px-3 py-2 text-sm" aria-label="Project">
                    <option value="">No project</option>
                    {(projects.data ?? []).map((p) => <option key={p.id} value={p.id}>{p.slug}</option>)}
                  </select>
                </label>
                <div className="flex gap-2">
                  <Button variant="outline" onClick={() => setStep(0)}>Back</Button>
                  <Button onClick={() => setStep(2)} disabled={!slug || !version || !license}>Continue</Button>
                </div>
              </CardContent>
            </Card>
          )}

          {step === 2 && (
            <Card>
              <CardHeader><CardTitle className="text-base">Capabilities &amp; permissions</CardTitle>
                <CardDescription>Least privilege by default. High-risk permissions require human approval and sandbox confinement.</CardDescription></CardHeader>
              <CardContent className="space-y-2">
                {allPerms.length === 0 && <p className="text-sm text-muted-foreground">Loading permission catalog…</p>}
                {allPerms.map((p) => {
                  const hint = permissionHint(p, catalog[p]);
                  const checked = perms.includes(p);
                  return (
                    <div key={p} className="rounded-lg border p-3 text-sm">
                      <label className="flex items-center gap-2 font-medium">
                        <input type="checkbox" checked={checked} onChange={() => togglePerm(p)} aria-label={`Permission ${p}`} />
                        <span className="oa-code">{p}</span>
                        <Badge variant={hint.risk === 'low' ? 'outline' : hint.risk === 'medium' ? 'secondary' : 'destructive'}>{hint.risk}</Badge>
                        {hint.requiresApproval && <Badge variant="warning">approval</Badge>}
                      </label>
                      <p className="mt-1 text-muted-foreground">{catalog[p]?.description ?? hint.implication}</p>
                      {checked && (
                        <ul className="mt-1 list-disc pl-5 text-xs text-muted-foreground">
                          <li>Implication: {hint.implication}</li>
                          <li>Review: {hint.review}</li>
                          <li>Sandbox: {hint.sandbox}</li>
                        </ul>
                      )}
                    </div>
                  );
                })}
                <div className="flex gap-2 pt-2">
                  <Button variant="outline" onClick={() => setStep(1)}>Back</Button>
                  <Button onClick={() => setStep(3)}>Review</Button>
                </div>
              </CardContent>
            </Card>
          )}

          {step === 3 && (
            <div className="grid gap-4 lg:grid-cols-2">
              <Card>
                <CardHeader><CardTitle className="text-base">Review &amp; create</CardTitle>
                  <CardDescription>Creates the extension definition plus its first version.</CardDescription></CardHeader>
                <CardContent className="space-y-2 text-sm">
                  <p><strong>Slug:</strong> {slug} · <strong>Type:</strong> {extType} · <strong>Version:</strong> {version}</p>
                  <p><strong>Trust on create:</strong> UNTRUSTED (least privilege; approvals required for high-risk permissions).</p>
                  <div aria-label="Requested permissions">
                    <p className="font-medium">Requested permissions ({perms.length})</p>
                    <ul className="list-disc pl-5 text-muted-foreground">
                      {perms.map((p) => <li key={p}><span className="oa-code">{p}</span> — {permissionHint(p, catalog[p]).implication}</li>)}
                    </ul>
                  </div>
                  {perms.includes('secret:access') && (
                    <p className="rounded border border-amber-500/40 p-2 text-amber-700" role="note">
                      secret:access — values are injected at runtime and never stored in code. Never log secret values.
                    </p>
                  )}
                  {(perms.includes('network:restricted') || perms.includes('browser:use')) && (
                    <p className="rounded border border-red-500/40 p-2 text-red-700" role="note">
                      Network/browser scope — SSRF-sensitive. Metadata endpoints are blocked; installs need human approval.
                    </p>
                  )}
                  {error && <p className="text-destructive" role="alert">{error}</p>}
                  <div className="flex gap-2">
                    <Button variant="outline" onClick={() => setStep(2)}>Back</Button>
                    <Button onClick={onCreate} loading={busy} disabled={!currentOrgId || !slug}>Create extension + version</Button>
                  </div>
                </CardContent>
              </Card>
              <Card>
                <CardHeader><CardTitle className="text-base">Manifest preview</CardTitle></CardHeader>
                <CardContent><pre className="max-h-96 overflow-auto rounded bg-muted p-3 text-xs">{JSON.stringify(manifestPreview, null, 2)}</pre></CardContent>
              </Card>
            </div>
          )}
        </div>
      </Layout>
    </Protected>
  );
}
