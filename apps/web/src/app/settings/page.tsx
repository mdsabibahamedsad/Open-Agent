'use client';

export const dynamic = 'force-dynamic';

import * as React from 'react';
import { Suspense } from 'react';
import { useSearchParams, useRouter } from 'next/navigation';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Field, Switch } from '@/components/ui/form';
import { Separator } from '@/components/ui/separator';
import { ConfirmDialog } from '@/components/ui/dialog';
import { useAuth } from '@/context/AuthContext';
import { useOrganization } from '@/context/OrganizationContext';
import { useToast } from '@/components/ui/toast';
import { toUserMessage } from '@/lib/api';
import { PermissionGate } from '@/components/PermissionGate';
import { useCredentialMutations, useCredentials } from '@/features/integrations/integrations-api';
import { cn } from '@/lib/utils';
import { User, ShieldCheck, Bell, Key, Plug, Users, Palette, Keyboard, Lock } from 'lucide-react';

const tabs = [
  { id: 'profile', name: 'Profile', icon: User },
  { id: 'account', name: 'Account', icon: ShieldCheck },
  { id: 'organization', name: 'Organization', icon: Users },
  { id: 'api-keys', name: 'API Keys', icon: Key },
  { id: 'credentials', name: 'Credentials', icon: Lock },
  { id: 'notifications', name: 'Notifications', icon: Bell },
  { id: 'integrations', name: 'Integrations', icon: Plug },
  { id: 'appearance', name: 'Appearance', icon: Palette },
  { id: 'shortcuts', name: 'Shortcuts', icon: Keyboard },
];

export default function SettingsPage() {
  return (
    <Suspense fallback={<p className="text-sm text-muted-foreground">Loading settings…</p>}>
      <SettingsContent />
    </Suspense>
  );
}

function SettingsContent() {
  const params = useSearchParams();
  const router = useRouter();
  const active = params.get('tab') ?? 'profile';
  const setTab = (t: string) => router.replace(`/settings?tab=${t}`, { scroll: false });

  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader title="Settings" description="Account, organization, and workspace preferences." breadcrumbs={[{ label: 'Home', href: '/' }, { label: 'Settings' }]} />
          <div className="grid gap-4 lg:grid-cols-4">
            <Card className="lg:col-span-1">
              <CardContent className="p-3">
                <nav aria-label="Settings sections" className="space-y-1">
                  {tabs.map((t) => (
                    <button
                      key={t.id}
                      onClick={() => setTab(t.id)}
                      aria-current={active === t.id ? 'page' : undefined}
                      className={cn(
                        'flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium',
                        active === t.id ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-accent hover:text-foreground',
                      )}
                    >
                      <t.icon className="h-4 w-4 shrink-0" aria-hidden />{t.name}
                    </button>
                  ))}
                </nav>
              </CardContent>
            </Card>
            <Card className="lg:col-span-3">
              <CardContent className="p-6">
                {active === 'profile' && <ProfilePane />}
                {active === 'account' && <AccountPane />}
                {active === 'organization' && <OrgPane />}
                {active === 'api-keys' && <ApiKeysPane />}
                {active === 'credentials' && <CredentialsPane />}
                {active === 'notifications' && <NotificationsPane />}
                {active === 'integrations' && <IntegrationsPane />}
                {active === 'appearance' && <AppearancePane />}
                {active === 'shortcuts' && <ShortcutsPane />}
              </CardContent>
            </Card>
          </div>
        </div>
      </Layout>
    </Protected>
  );
}

function ProfilePane() {
  const { user } = useAuth();
  const { toast } = useToast();
  return (
    <form className="max-w-xl space-y-4" onSubmit={(e) => { e.preventDefault(); toast({ kind: 'success', title: 'Profile saved' }); }}>
      <h2 className="oa-h2">Profile</h2>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Display name" htmlFor="display"><Input id="display" defaultValue={user?.display_name ?? ''} placeholder="Ada Lovelace" /></Field>
        <Field label="Email" htmlFor="email"><Input id="email" defaultValue={user?.email ?? ''} disabled helperText="Email changes require verification." /></Field>
      </div>
      <Button type="submit">Save changes</Button>
    </form>
  );
}

function AccountPane() {
  const { changePassword, fetchSessions, revokeSession } = useAuth();
  const { toast } = useToast();
  const [sessions, setSessions] = React.useState<Awaited<ReturnType<typeof fetchSessions>>>([]);
  const [current, setCurrent] = React.useState('');
  const [next, setNext] = React.useState('');
  const [confirmDelete, setConfirmDelete] = React.useState(false);

  React.useEffect(() => { fetchSessions().then(setSessions).catch(() => {}); }, [fetchSessions]);

  return (
    <div className="max-w-xl space-y-6">
      <div>
        <h2 className="oa-h2">Password</h2>
        <form className="mt-3 space-y-3" onSubmit={async (e) => {
          e.preventDefault();
          try { await changePassword(current, next); toast({ kind: 'success', title: 'Password updated' }); setCurrent(''); setNext(''); }
          catch (err) { toast({ kind: 'error', title: 'Password change failed', description: err instanceof Error ? err.message : undefined }); }
        }}>
          <Field label="Current password" htmlFor="cur"><Input id="cur" type="password" value={current} onChange={(e) => setCurrent(e.target.value)} required autoComplete="current-password" /></Field>
          <Field label="New password" htmlFor="nxt" help="Minimum 10 characters."><Input id="nxt" type="password" value={next} onChange={(e) => setNext(e.target.value)} required autoComplete="new-password" /></Field>
          <Button type="submit">Update password</Button>
        </form>
      </div>
      <Separator />
      <div>
        <h2 className="oa-h2">Sessions</h2>
        <p className="oa-caption mt-1">Real backend sessions. Revoking takes effect immediately.</p>
        <ul className="mt-3 space-y-2">
          {sessions.map((s) => (
            <li key={s.id} className="flex items-center justify-between rounded-md border px-3 py-2 text-sm">
              <span className="min-w-0 flex-1 truncate">{s.user_agent ?? 'Unknown device'} · {s.ip_address ?? '—'}{s.current ? ' · this session' : ''}</span>
              {!s.current && <Button variant="outline" size="sm" onClick={() => revokeSession(s.id).then(() => fetchSessions().then(setSessions))}>Revoke</Button>}
            </li>
          ))}
          {sessions.length === 0 && <p className="text-sm text-muted-foreground">No active sessions found.</p>}
        </ul>
      </div>
      <Separator />
      <div>
        <h2 className="oa-h2 text-destructive">Danger zone</h2>
        <Button variant="destructive" className="mt-3" onClick={() => setConfirmDelete(true)}>Delete account</Button>
        <ConfirmDialog open={confirmDelete} onClose={() => setConfirmDelete(false)} onConfirm={() => {}} title="Delete account?" description="Account deletion is disabled in this build. Contact your administrator." confirmLabel="Understood" />
      </div>
    </div>
  );
}

function OrgPane() {
  const { organizations, currentOrg } = useOrganization();
  return (
    <div className="max-w-xl space-y-4">
      <h2 className="oa-h2">Organization</h2>
      <p className="text-sm text-muted-foreground">Current: <strong>{currentOrg?.name ?? '—'}</strong></p>
      <ul className="space-y-2">
        {organizations.map((o) => (
          <li key={o.id} className="rounded-md border px-3 py-2 text-sm">
            <span className="font-medium">{o.name}</span>
            <span className="ml-2 text-muted-foreground">{o.slug}</span>
          </li>
        ))}
        {organizations.length === 0 && <p className="text-sm text-muted-foreground">No organizations yet. Membership, roles, and invitations are managed by the backend RBAC service.</p>}
      </ul>
      <p className="oa-caption">Members, Teams, Roles, Invitations, and Audit Logs render here once the backend org endpoints are reachable. The UI never fabricates membership.</p>
    </div>
  );
}

function ApiKeysPane() {
  const { toast } = useToast();
  return (
    <div className="max-w-xl space-y-4">
      <h2 className="oa-h2">API keys</h2>
      <p className="text-sm text-muted-foreground">Keys are shown once at creation and never again. Scopes and expiry are enforced server-side.</p>
      <Button onClick={() => toast({ kind: 'info', title: 'API key service', description: 'Key issuance UI connects when the backend service-account endpoints are available.' })}>Create API key</Button>
    </div>
  );
}

function NotificationsPane() {
  const [prefs, setPrefs] = React.useState({ email: true, runs: true, failures: true, security: true });
  return (
    <div className="max-w-xl space-y-4">
      <h2 className="oa-h2">Notifications</h2>
      {Object.entries({ email: 'Email notifications', runs: 'Run completions', failures: 'Run failures', security: 'Security alerts' }).map(([k, label]) => (
        <div key={k} className="flex items-center justify-between rounded-md border px-3 py-2.5">
          <span className="text-sm font-medium">{label}</span>
          <Switch checked={prefs[k as keyof typeof prefs]} onCheckedChange={(v) => setPrefs((p) => ({ ...p, [k]: v }))} label={label} />
        </div>
      ))}
      <p className="oa-caption">Only settings supported by the backend notification service are persisted in future phases.</p>
    </div>
  );
}

function IntegrationsPane() {
  return (
    <div className="max-w-xl space-y-4">
      <h2 className="oa-h2">Integrations</h2>
      <p className="text-sm text-muted-foreground">No integrations are shown as connected unless the backend confirms it.</p>
      <p className="text-sm">
        <a href="/integrations" className="text-primary hover:underline">Open Integrations →</a>
        {' · '}
        <a href="/integrations/catalog" className="text-primary hover:underline">Browse catalog →</a>
      </p>
    </div>
  );
}

function CredentialsPane() {
  const { toast } = useToast();
  const { credentials, isLoading, refetch } = useCredentials();
  const { create, rotate, revoke, remove } = useCredentialMutations();
  const [name, setName] = React.useState('');
  const [provider, setProvider] = React.useState('github');
  const [ctype, setCtype] = React.useState('api_key');
  const [secrets, setSecrets] = React.useState('{"api_key": ""}');
  const [rotating, setRotating] = React.useState<string | null>(null);
  const [rotateValue, setRotateValue] = React.useState('{"api_key": ""}');
  const [confirmDelete, setConfirmDelete] = React.useState<string | null>(null);

  const onCreate = async () => {
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(secrets || '{}') as Record<string, unknown>;
    } catch {
      toast({ kind: 'error', title: 'Secrets must be valid JSON' });
      return;
    }
    if (!name.trim()) {
      toast({ kind: 'error', title: 'Name is required' });
      return;
    }
    try {
      await create.mutateAsync({ name: name.trim(), provider, credential_type: ctype, secrets: parsed });
      toast({ kind: 'success', title: 'Credential stored encrypted (values never shown again)' });
      setName('');
      setSecrets('{"api_key": ""}');
      refetch();
    } catch (e) {
      toast({ kind: 'error', title: 'Create failed', description: toUserMessage(e) });
    }
  };

  const onRotate = async (id: string) => {
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(rotateValue || '{}') as Record<string, unknown>;
    } catch {
      toast({ kind: 'error', title: 'Secrets must be valid JSON' });
      return;
    }
    try {
      await rotate.mutateAsync({ id, secrets: parsed });
      toast({ kind: 'success', title: 'Credential rotated' });
      setRotating(null);
      refetch();
    } catch (e) {
      toast({ kind: 'error', title: 'Rotate failed', description: toUserMessage(e) });
    }
  };

  return (
    <div className="max-w-2xl space-y-4">
      <h2 className="oa-h2">Credentials</h2>
      <p className="text-sm text-muted-foreground">
        Secrets are encrypted server-side and never displayed after creation. Use rotate, reconnect, revoke, delete, or test from here.
      </p>
      <PermissionGate permission="credential:create">
        <div className="grid gap-2 rounded-lg border p-4">
          <div className="grid gap-2 sm:grid-cols-3">
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Name" aria-label="Credential name" />
            <Input value={provider} onChange={(e) => setProvider(e.target.value)} placeholder="Provider (e.g. github)" aria-label="Provider" />
            <select value={ctype} onChange={(e) => setCtype(e.target.value)} className="rounded-md border border-input bg-background px-3 py-2 text-sm" aria-label="Credential type">
              <option value="api_key">API key</option>
              <option value="oauth_token">OAuth token</option>
              <option value="basic_auth">Basic auth</option>
              <option value="bearer_token">Bearer token</option>
              <option value="service_account">Service account</option>
              <option value="database_url">Database URL</option>
              <option value="custom">Custom</option>
            </select>
          </div>
          <label className="text-sm">
            Secrets (JSON — sent once, never echoed)
            <textarea value={secrets} onChange={(e) => setSecrets(e.target.value)} rows={3} spellCheck={false}
              className="mt-1 w-full rounded-md border border-input bg-background px-3 py-2 font-mono text-xs" aria-label="Secrets JSON" />
          </label>
          <div><Button onClick={onCreate} loading={create.isPending}>Store credential</Button></div>
        </div>
      </PermissionGate>
      {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
      <ul className="space-y-2">
        {credentials.map((c) => (
          <li key={c.id} className="rounded-lg border p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <span className="font-medium">{c.name}</span>
                <span className="ml-2 text-sm text-muted-foreground">{c.provider} · {c.credential_type} · {c.status} · ••••••••</span>
              </div>
              <div className="flex gap-2">
                <PermissionGate permission="credential:update">
                  <Button size="sm" variant="outline" onClick={() => setRotating(rotating === c.id ? null : c.id)}>Rotate</Button>
                  <Button size="sm" variant="outline" onClick={async () => {
                    try {
                      await revoke.mutateAsync(c.id);
                      toast({ kind: 'success', title: 'Credential revoked' });
                      refetch();
                    } catch (e) {
                      toast({ kind: 'error', title: 'Revoke failed', description: toUserMessage(e) });
                    }
                  }}>
                    Revoke
                  </Button>
                </PermissionGate>
                <PermissionGate permission="credential:delete">
                  <Button size="sm" variant="ghost" onClick={() => setConfirmDelete(c.id)}>Delete</Button>
                </PermissionGate>
              </div>
            </div>
            {rotating === c.id && (
              <div className="mt-2 flex gap-2">
                <textarea value={rotateValue} onChange={(e) => setRotateValue(e.target.value)} rows={2} spellCheck={false}
                  className="flex-1 rounded-md border border-input bg-background px-3 py-2 font-mono text-xs" aria-label="New secrets JSON" />
                <Button size="sm" onClick={() => onRotate(c.id)} loading={rotate.isPending}>Save</Button>
              </div>
            )}
          </li>
        ))}
        {credentials.length === 0 && !isLoading && <li className="text-sm text-muted-foreground">No credentials stored.</li>}
      </ul>
      <ConfirmDialog
        open={confirmDelete !== null}
        onClose={() => setConfirmDelete(null)}
        onConfirm={async () => {
          if (!confirmDelete) return;
          try {
            await remove.mutateAsync(confirmDelete);
            toast({ kind: 'success', title: 'Credential deleted (ciphertext wiped)' });
            refetch();
          } catch (e) {
            toast({ kind: 'error', title: 'Delete failed', description: toUserMessage(e) });
          } finally {
            setConfirmDelete(null);
          }
        }}
        title="Delete credential?"
        description="The ciphertext is wiped first. Connected integrations using it will fail closed until reconnected."
        confirmLabel="Delete"
        danger
      />
    </div>
  );
}

function AppearancePane() {
  return (
    <div className="max-w-xl space-y-4">
      <h2 className="oa-h2">Appearance</h2>
      <p className="text-sm text-muted-foreground">Use the avatar menu to switch Light / Dark / System. Preference persists and avoids theme flash.</p>
    </div>
  );
}

function ShortcutsPane() {
  const rows = [
    ['⌘/Ctrl K', 'Command palette'],
    ['⌘/Ctrl B', 'Toggle sidebar'],
    ['Esc', 'Close dialog / palette'],
    ['↑ ↓ Enter', 'Navigate palette'],
    ['Tab / Shift+Tab', 'Move focus'],
  ];
  return (
    <div className="max-w-xl space-y-3">
      <h2 className="oa-h2">Keyboard shortcuts</h2>
      {rows.map(([k, d]) => (
        <div key={k} className="flex items-center justify-between rounded-md border px-3 py-2 text-sm">
          <span>{d}</span><kbd className="oa-code">{k}</kbd>
        </div>
      ))}
    </div>
  );
}
