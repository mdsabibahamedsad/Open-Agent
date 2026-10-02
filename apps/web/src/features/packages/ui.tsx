'use client';

// MP22: shared Template Center building blocks.

import * as React from 'react';
import Link from 'next/link';
import {
  AlertTriangle,
  BadgeCheck,
  Boxes,
  CheckCircle2,
  Download,
  GitFork,
  Shield,
  ShieldAlert,
  ShieldCheck,
} from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { StatusBadge } from '@/components/ui/status';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { Dialog } from '@/components/ui/dialog';
import { useOrganization } from '@/context/OrganizationContext';
import {
  ConfigField,
  Installation,
  InstallPreview,
  SecurityFinding,
  installationsApi,
  packagesApi,
} from '@/lib/packages';
import { toUserMessage } from '@/lib/api';

// ---------------------------------------------------------------------------

export interface PackageCardData {
  id: string;
  name: string;
  description: string;
  package_type: string;
  latest_version: string;
  trust: string;
  official: boolean;
  categories: string[];
  tags: string[];
}

export function catalogEntryToCard(e: {
  package_id: string;
  name: string;
  description: string;
  type: string;
  version: string;
  trust: string;
  official: boolean;
  categories: string[];
  tags: string[];
}): PackageCardData {
  return {
    id: e.package_id,
    name: e.name,
    description: e.description,
    package_type: e.type,
    latest_version: e.version,
    trust: e.trust,
    official: e.official,
    categories: e.categories ?? [],
    tags: e.tags ?? [],
  };
}

// ---------------------------------------------------------------------------

export function TrustBadge({ trust, official }: { trust: string; official?: boolean }) {
  if (official) {
    return (
      <Badge variant="success" className="gap-1">
        <BadgeCheck className="h-3 w-3" aria-hidden /> Official
      </Badge>
    );
  }
  const variant =
    trust === 'VERIFIED' ? 'success' : trust === 'ORGANIZATION' ? 'default' : trust === 'COMMUNITY' ? 'secondary' : 'warning';
  return <Badge variant={variant}>{trust}</Badge>;
}

export function RiskBadge({ risk }: { risk: string }) {
  const r = risk.toUpperCase();
  const variant = r === 'LOW' ? 'success' : r === 'MEDIUM' ? 'warning' : 'destructive';
  const Icon = r === 'LOW' ? ShieldCheck : ShieldAlert;
  return (
    <Badge variant={variant} className="gap-1">
      <Icon className="h-3 w-3" aria-hidden /> {r} risk
    </Badge>
  );
}

export function PackageCard({
  pkg,
  installed,
  href,
}: {
  pkg: PackageCardData;
  installed?: boolean;
  href: string;
}) {
  return (
    <Link href={href} className="block h-full" aria-label={`Open ${pkg.name}`}>
      <Card className="flex h-full flex-col transition-colors hover:border-primary/50">
        <CardHeader>
          <div className="flex items-start justify-between gap-2">
            <CardTitle className="text-base">{pkg.name}</CardTitle>
            <TrustBadge trust={pkg.trust} official={pkg.official} />
          </div>
          <CardDescription className="line-clamp-2">{pkg.description || 'No description.'}</CardDescription>
        </CardHeader>
        <CardContent className="mt-auto space-y-3">
          <div className="flex flex-wrap gap-1.5">
            <Badge variant="outline">{pkg.package_type}</Badge>
            {pkg.latest_version && <Badge variant="secondary">v{pkg.latest_version}</Badge>}
            {installed && (
              <Badge variant="success" className="gap-1">
                <CheckCircle2 className="h-3 w-3" aria-hidden /> Installed
              </Badge>
            )}
          </div>
          {(pkg.categories?.length > 0 || pkg.tags?.length > 0) && (
            <p className="text-xs text-muted-foreground">
              {[...(pkg.categories ?? []), ...(pkg.tags ?? [])].slice(0, 4).join(' · ')}
            </p>
          )}
        </CardContent>
      </Card>
    </Link>
  );
}

// ---------------------------------------------------------------------------

export function SecurityReport({ findings, risk }: { findings: SecurityFinding[]; risk: string }) {
  const [filter, setFilter] = React.useState('ALL');
  const counts = React.useMemo(() => {
    const c: Record<string, number> = { ALL: findings.length, INFO: 0, WARNING: 0, ERROR: 0, BLOCKER: 0 };
    for (const f of findings) c[f.severity] = (c[f.severity] ?? 0) + 1;
    return c;
  }, [findings]);
  const shown = filter === 'ALL' ? findings : findings.filter((f) => f.severity === filter);
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <RiskBadge risk={risk} />
        <span className="text-sm text-muted-foreground">
          {findings.length === 0 ? 'No findings. Trust still never grants permissions.' : `${findings.length} finding(s)`}
        </span>
        <div className="ml-auto flex gap-1.5">
          {['ALL', 'INFO', 'WARNING', 'ERROR', 'BLOCKER'].map((s) => (
            <Button key={s} variant={filter === s ? 'default' : 'outline'} size="sm" onClick={() => setFilter(s)}>
              {s} ({counts[s] ?? 0})
            </Button>
          ))}
        </div>
      </div>
      {shown.length === 0 ? (
        <p className="text-sm text-muted-foreground">Static scan is clean for this filter.</p>
      ) : (
        <ul className="space-y-2">
          {shown.map((f, i) => (
            <li key={i} className="flex gap-3 rounded-md border p-3 text-sm">
              {f.severity === 'INFO' ? (
                <Shield className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
              ) : (
                <AlertTriangle
                  className={`mt-0.5 h-4 w-4 shrink-0 ${f.severity === 'BLOCKER' || f.severity === 'ERROR' ? 'text-destructive' : 'text-yellow-500'}`}
                  aria-hidden
                />
              )}
              <div>
                <p className="font-medium">
                  {f.code} <span className="text-muted-foreground">· {f.path}</span>
                </p>
                <p className="text-muted-foreground">{f.message}</p>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------

export function PackageDiffView({ diff }: { diff: Record<string, unknown> }) {
  const added = (diff.added_resources as unknown[]) ?? [];
  const removed = (diff.removed_resources as unknown[]) ?? [];
  const changed = (diff.changed_resources as unknown[]) ?? [];
  const deps = (diff.dependency_changes as { added: unknown[]; removed: unknown[]; changed: unknown[] }) ?? {
    added: [],
    removed: [],
    changed: [],
  };
  const perms = (diff.permission_changes as { approvals_added: string[]; approvals_removed: string[] }) ?? {
    approvals_added: [],
    approvals_removed: [],
  };
  return (
    <div className="space-y-4 text-sm">
      <p className="text-muted-foreground">
        v{String(diff.from_version)} → v{String(diff.to_version)}
        {diff.security_changed ? ' · security manifest changed' : ''}
        {diff.configuration_changed ? ' · configuration changed' : ''}
      </p>
      {(perms.approvals_added.length > 0 || perms.approvals_removed.length > 0) && (
        <div className="rounded-md border border-yellow-500/40 bg-yellow-500/5 p-3">
          <p className="font-medium">Permission changes (review carefully)</p>
          {perms.approvals_added.length > 0 && <p>Added approvals: {perms.approvals_added.join(', ')}</p>}
          {perms.approvals_removed.length > 0 && <p>Removed approvals: {perms.approvals_removed.join(', ')}</p>}
        </div>
      )}
      <DiffList title={`Added (${added.length})`} items={added} tone="added" />
      <DiffList title={`Removed (${removed.length})`} items={removed} tone="removed" />
      <DiffList title={`Changed (${changed.length})`} items={changed} tone="changed" />
      <DiffList title={`Dependencies added (${deps.added.length})`} items={deps.added} tone="added" />
      <DiffList title={`Dependencies removed (${deps.removed.length})`} items={deps.removed} tone="removed" />
      <DiffList title={`Dependencies changed (${deps.changed.length})`} items={deps.changed} tone="changed" />
    </div>
  );
}

function DiffList({ title, items, tone }: { title: string; items: unknown[]; tone: 'added' | 'removed' | 'changed' }) {
  if (items.length === 0) return null;
  const color = tone === 'added' ? 'text-emerald-600' : tone === 'removed' ? 'text-destructive' : 'text-yellow-600';
  return (
    <div>
      <p className={`font-medium ${color}`}>{title}</p>
      <ul className="mt-1 list-disc space-y-1 pl-5 text-muted-foreground">
        {items.slice(0, 20).map((item, i) => (
          <li key={i} className="break-all">
            <code className="text-xs">{JSON.stringify(item).slice(0, 220)}</code>
          </li>
        ))}
        {items.length > 20 && <li>…and {items.length - 20} more</li>}
      </ul>
    </div>
  );
}

// ---------------------------------------------------------------------------

export function ResourceGraph({
  nodes,
  edges,
}: {
  nodes: { id: string; kind: string; slug: string; name: string }[];
  edges: { from: string; to: string; relation: string }[];
}) {
  const children = React.useMemo(() => {
    const map = new Map<string, { relation: string; to: string }[]>();
    for (const e of edges) {
      if (!map.has(e.from)) map.set(e.from, []);
      map.get(e.from)!.push({ relation: e.relation, to: e.to });
    }
    return map;
  }, [edges]);
  const byId = React.useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);
  const roots = nodes.filter((n) => !edges.some((e) => e.to === n.id)).slice(0, 12);
  return (
    <div className="space-y-2 text-sm">
      {roots.length === 0 && <p className="text-muted-foreground">No resources declared.</p>}
      {roots.map((root) => (
        <GraphNodeView key={root.id} node={root} byId={byId} childrenMap={children} depth={0} />
      ))}
    </div>
  );
}

function GraphNodeView({
  node,
  byId,
  childrenMap,
  depth,
}: {
  node: { id: string; kind: string; slug: string; name: string };
  byId: Map<string, { id: string; kind: string; slug: string; name: string }>;
  childrenMap: Map<string, { relation: string; to: string }[]>;
  depth: number;
}) {
  const [open, setOpen] = React.useState(depth < 2);
  const kids = childrenMap.get(node.id) ?? [];
  return (
    <div style={{ marginLeft: depth * 16 }}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 rounded px-1 py-0.5 text-left hover:bg-accent"
        aria-expanded={open}
      >
        <Boxes className="h-3.5 w-3.5 text-primary" aria-hidden />
        <span className="font-medium">{node.name}</span>
        <Badge variant="outline">{node.kind}</Badge>
        {kids.length > 0 && <span className="text-xs text-muted-foreground">({kids.length})</span>}
      </button>
      {open &&
        kids.map((k, i) => {
          const child = byId.get(k.to);
          if (!child) return null;
          return <GraphNodeView key={i} node={child} byId={byId} childrenMap={childrenMap} depth={depth + 1} />;
        })}
    </div>
  );
}

// ---------------------------------------------------------------------------

export function ConfigForm({
  fields,
  values,
  onChange,
}: {
  fields: ConfigField[];
  values: Record<string, unknown>;
  onChange: (values: Record<string, unknown>) => void;
}) {
  if (fields.length === 0) return <p className="text-sm text-muted-foreground">No configuration required.</p>;
  return (
    <div className="space-y-4">
      {fields.map((f) => (
        <div key={f.name}>
          <label htmlFor={`cfg-${f.name}`} className="mb-1 block text-sm font-medium">
            {f.label} {f.required && <span className="text-destructive">*</span>}
            {f.sensitive && (
              <Badge variant="warning" className="ml-2">
                reference only — never paste secrets
              </Badge>
            )}
          </label>
          {f.description && <p className="mb-1 text-xs text-muted-foreground">{f.description}</p>}
          {f.type === 'enum' ? (
            <select
              id={`cfg-${f.name}`}
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
              value={String(values[f.name] ?? f.default ?? '')}
              onChange={(e) => onChange({ ...values, [f.name]: e.target.value })}
            >
              <option value="">Select…</option>
              {f.options.map((o) => (
                <option key={o} value={o}>
                  {o}
                </option>
              ))}
            </select>
          ) : f.type === 'boolean' ? (
            <input
              id={`cfg-${f.name}`}
              type="checkbox"
              checked={Boolean(values[f.name] ?? f.default ?? false)}
              onChange={(e) => onChange({ ...values, [f.name]: e.target.checked })}
              className="h-4 w-4"
            />
          ) : (
            <Input
              id={`cfg-${f.name}`}
              type={f.sensitive ? 'text' : f.type === 'number' ? 'number' : 'text'}
              placeholder={f.sensitive ? 'Paste a credential/connection reference ID' : String(f.default ?? '')}
              value={String(values[f.name] ?? '')}
              onChange={(e) => onChange({ ...values, [f.name]: e.target.value })}
              autoComplete="off"
            />
          )}
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Multi-step installation wizard: Overview → Dependencies → Permissions →
// Credentials → Configuration → Security → Review → Install → Verification.
// ---------------------------------------------------------------------------

const WIZARD_STEPS = [
  'Overview',
  'Dependencies',
  'Permissions',
  'Credentials',
  'Configuration',
  'Security',
  'Review',
  'Install',
] as const;

export function InstallWizard({
  packageId,
  version,
  packageName,
  open,
  onClose,
  onInstalled,
}: {
  packageId: string;
  version: string;
  packageName: string;
  open: boolean;
  onClose: () => void;
  onInstalled: () => void;
}) {
  const { currentOrgId } = useOrganization();
  const [step, setStep] = React.useState(0);
  const [preview, setPreview] = React.useState<InstallPreview | null>(null);
  const [values, setValues] = React.useState<Record<string, unknown>>({});
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [result, setResult] = React.useState<{ status: string; error: string } | null>(null);

  React.useEffect(() => {
    if (!open || !currentOrgId) return;
    setStep(0);
    setPreview(null);
    setValues({});
    setError(null);
    setResult(null);
    setLoading(true);
    packagesApi
      .preview(currentOrgId, packageId, version, {})
      .then((p) => {
        setPreview(p);
        const defaults: Record<string, unknown> = {};
        for (const f of p.configuration_fields) {
          if (f.default !== undefined) defaults[f.name] = f.default;
        }
        setValues(defaults);
      })
      .catch((e: unknown) => setError(toUserMessage(e)))
      .finally(() => setLoading(false));
  }, [open, currentOrgId, packageId, version]);

  const refreshPreview = () => {
    if (!currentOrgId) return;
    setLoading(true);
    setError(null);
    packagesApi
      .preview(currentOrgId, packageId, version, values)
      .then(setPreview)
      .catch((e: unknown) => setError(toUserMessage(e)))
      .finally(() => setLoading(false));
  };

  const doInstall = async () => {
    if (!currentOrgId) return;
    setLoading(true);
    setError(null);
    try {
      const res = await packagesApi.install(currentOrgId, packageId, version, values);
      setResult(res);
      if (res.status === 'INSTALLED') onInstalled();
    } catch (e: unknown) {
      setError(toUserMessage(e));
    } finally {
      setLoading(false);
    }
  };

  const stepName = WIZARD_STEPS[step];
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={`Install ${packageName} v${version}`}
      description={`Step ${step + 1} of ${WIZARD_STEPS.length}: ${stepName}. Nothing privileged is created silently.`}
      wide
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            {result ? 'Close' : 'Cancel'}
          </Button>
          {step > 0 && !result && (
            <Button variant="outline" onClick={() => setStep((s) => s - 1)} disabled={loading}>
              Back
            </Button>
          )}
          {!result && step < WIZARD_STEPS.length - 1 && (
            <Button onClick={() => setStep((s) => s + 1)} disabled={loading || !preview}>
              Next
            </Button>
          )}
          {!result && step === WIZARD_STEPS.length - 1 && (
            <Button onClick={doInstall} loading={loading} disabled={!preview?.can_install}>
              <Download className="mr-2 h-4 w-4" aria-hidden /> Install
            </Button>
          )}
        </>
      }
    >
      {loading && !preview && <p className="text-sm text-muted-foreground">Loading installation preview…</p>}
      {error && (
        <p role="alert" className="rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm">
          {error}
        </p>
      )}
      {preview && !result && (
        <div className="space-y-4 text-sm">
          {stepName === 'Overview' && (
            <ul className="space-y-1">
              <li>
                <strong>{preview.estimated_changes.resources}</strong> resource(s) will be created
              </li>
              <li>
                <strong>{preview.dependencies.length}</strong> dependenc(ies) resolved
              </li>
              <li>
                Risk: <strong>{preview.risk}</strong>
              </li>
            </ul>
          )}
          {stepName === 'Dependencies' && (
            <div>
              {preview.dependencies.length === 0 && <p className="text-muted-foreground">No dependencies.</p>}
              <ul className="space-y-1">
                {preview.dependencies.map((d, i) => (
                  <li key={i}>
                    <code className="text-xs">
                      {d.type}:{d.package}@{d.resolved_version}
                    </code>
                    {d.optional && <span className="text-muted-foreground"> (optional)</span>}
                  </li>
                ))}
              </ul>
              {preview.dependency_failures.length > 0 && (
                <div className="mt-2 space-y-1 text-destructive">
                  {preview.dependency_failures.map((f, i) => (
                    <p key={i}>{f.message}</p>
                  ))}
                </div>
              )}
              {preview.dependency_warnings.length > 0 && (
                <div className="mt-2 space-y-1 text-yellow-600">
                  {preview.dependency_warnings.map((w, i) => (
                    <p key={i}>{w}</p>
                  ))}
                </div>
              )}
            </div>
          )}
          {stepName === 'Permissions' && (
            <div>
              <p className="text-muted-foreground">Capabilities requested by this package:</p>
              <ul className="mt-1 list-disc pl-5">
                {preview.required_permissions.map((p) => (
                  <li key={p}>{p}</li>
                ))}
                {preview.required_permissions.length === 0 && <li>None declared.</li>}
              </ul>
              {preview.policy_conflicts.length > 0 && (
                <div className="mt-2 rounded-md border border-destructive/40 p-2 text-destructive">
                  {preview.policy_conflicts.map((c, i) => (
                    <p key={i}>{c}</p>
                  ))}
                </div>
              )}
            </div>
          )}
          {stepName === 'Credentials' && (
            <div>
              {preview.required_credentials.length === 0 && (
                <p className="text-muted-foreground">No credentials required.</p>
              )}
              <ul className="list-disc space-y-1 pl-5">
                {preview.required_credentials.map((c) => (
                  <li key={c.name}>
                    {c.name} ({c.type}){c.required === 'True' ? ' — required' : ' — optional'}
                  </li>
                ))}
              </ul>
              {(preview.required_connectors.length > 0 || preview.required_tools.length > 0) && (
                <p className="mt-2 text-muted-foreground">
                  Connectors: {preview.required_connectors.join(', ') || 'none'} · Tools:{' '}
                  {preview.required_tools.join(', ') || 'none'}
                </p>
              )}
            </div>
          )}
          {stepName === 'Configuration' && (
            <div>
              <ConfigForm fields={preview.configuration_fields} values={values} onChange={setValues} />
              <Button variant="outline" size="sm" className="mt-3" onClick={refreshPreview} disabled={loading}>
                Re-validate
              </Button>
              {preview.configuration_errors.length > 0 && (
                <div className="mt-2 text-destructive">
                  {preview.configuration_errors.map((e, i) => (
                    <p key={i}>{e}</p>
                  ))}
                </div>
              )}
            </div>
          )}
          {stepName === 'Security' && (
            <SecurityReport findings={preview.security_warnings} risk={preview.risk} />
          )}
          {stepName === 'Review' && (
            <div className="space-y-1">
              <p>
                Install <strong>{preview.package.name}</strong> v{preview.version} into this organization.
              </p>
              <p className={preview.can_install ? 'text-emerald-600' : 'text-destructive'}>
                {preview.can_install
                  ? 'All checks pass. Proceed to Install.'
                  : 'Blocked: resolve failures, policy conflicts or configuration errors first.'}
              </p>
            </div>
          )}
          {stepName === 'Install' && (
            <p className="text-muted-foreground">
              Press Install to create {preview.estimated_changes.resources} resource(s). The operation is
              idempotent and fully audited.
            </p>
          )}
        </div>
      )}
      {result && (
        <div className="space-y-2 text-sm" role="status">
          <p>
            Status: <StatusBadge status={result.status} />
          </p>
          {result.error && <p className="text-destructive">{result.error}</p>}
          {result.status === 'AWAITING_CONFIGURATION' && (
            <p>Additional configuration is required — reopen the wizard with the missing values.</p>
          )}
        </div>
      )}
    </Dialog>
  );
}

export function ForkButton({ packageId, packageSlug }: { packageId: string; packageSlug: string }) {
  const { currentOrgId } = useOrganization();
  const [busy, setBusy] = React.useState(false);
  const [message, setMessage] = React.useState<string | null>(null);
  const fork = async () => {
    if (!currentOrgId) return;
    setBusy(true);
    setMessage(null);
    try {
      const slug = `${packageSlug}-fork`;
      await packagesApi.fork(currentOrgId, packageId, slug, `${packageSlug} (fork)`);
      setMessage(`Forked as ${slug}.`);
    } catch (e: unknown) {
      setMessage(toUserMessage(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <span className="inline-flex items-center gap-2">
      <Button variant="outline" size="sm" onClick={fork} disabled={busy}>
        <GitFork className="mr-1.5 h-3.5 w-3.5" aria-hidden /> Fork
      </Button>
      {message && <span className="text-xs text-muted-foreground">{message}</span>}
    </span>
  );
}

export function UpdateControls({ installation }: { installation: Installation }) {
  const { currentOrgId } = useOrganization();
  const [message, setMessage] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);
  const run = async (fn: () => Promise<unknown>, label: string) => {
    if (!currentOrgId) return;
    setBusy(true);
    setMessage(null);
    try {
      await fn();
      setMessage(`${label} succeeded.`);
    } catch (e: unknown) {
      setMessage(toUserMessage(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <span className="inline-flex flex-wrap items-center gap-2">
      {installation.update_available && (
        <Button
          variant="outline"
          size="sm"
          disabled={busy}
          onClick={() =>
            run(async () => {
              await installationsApi.planUpdate(currentOrgId!, installation.id, installation.update_available);
              await installationsApi.applyUpdate(currentOrgId!, installation.id);
            }, 'Update')
          }
        >
          Update to v{installation.update_available}
        </Button>
      )}
      <Button
        variant="outline"
        size="sm"
        disabled={busy}
        onClick={() => run(() => installationsApi.rollback(currentOrgId!, installation.id), 'Rollback')}
      >
        Roll back
      </Button>
      <Button
        variant="destructive"
        size="sm"
        disabled={busy}
        onClick={() => run(() => installationsApi.uninstall(currentOrgId!, installation.id), 'Uninstall')}
      >
        Uninstall
      </Button>
      {message && <span className="text-xs text-muted-foreground">{message}</span>}
    </span>
  );
}

export function PackageTabsFallback() {
  return (
    <Tabs defaultValue="overview">
      <TabsList>
        <TabsTrigger value="overview">Overview</TabsTrigger>
        <TabsTrigger value="security">Security</TabsTrigger>
      </TabsList>
      <TabsContent value="overview">Loading…</TabsContent>
      <TabsContent value="security">Loading…</TabsContent>
    </Tabs>
  );
}
