'use client';

export const dynamic = 'force-dynamic';

import * as React from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { ErrorState } from '@/components/ui/states';
import { useToast } from '@/components/ui/toast';
import { toUserMessage } from '@/lib/api';
import { commerceApi } from '@/lib/commerce';

const TRUST_ORDER = ['UNTRUSTED', 'UNKNOWN', 'COMMUNITY', 'ORGANIZATION', 'VERIFIED', 'OFFICIAL', 'CORE'];

export default function RegistriesPage() {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: ['commerce-registries'],
    queryFn: () => commerceApi.registries(),
    staleTime: 30_000,
  });
  const [slug, setSlug] = React.useState('');
  const [name, setName] = React.useState('');
  const [registryType, setRegistryType] = React.useState('PRIVATE');
  const [endpoint, setEndpoint] = React.useState('');
  const [visibility, setVisibility] = React.useState('PRIVATE');

  const create = useMutation({
    mutationFn: () =>
      commerceApi.createRegistry({
        slug: slug.trim(),
        name: name.trim(),
        registry_type: registryType,
        endpoint: endpoint.trim(),
        visibility,
        trust_level: 'UNKNOWN',
        auth_type: 'PUBLIC',
      }),
    onSuccess: () => {
      setSlug('');
      setName('');
      setEndpoint('');
      queryClient.invalidateQueries({ queryKey: ['commerce-registries'] });
      toast({ kind: 'success', title: 'Registry added' });
    },
    onError: (e) => toast({ kind: 'error', title: 'Add failed', description: toUserMessage(e) }),
  });

  const sync = useMutation({
    mutationFn: (id: string) => commerceApi.syncRegistry(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['commerce-registries'] });
      toast({ kind: 'success', title: 'Sync recorded' });
    },
    onError: (e) => toast({ kind: 'error', title: 'Sync failed', description: toUserMessage(e) }),
  });

  const test = useMutation({
    mutationFn: (id: string) => commerceApi.testRegistry(id),
    onSuccess: (r) =>
      toast({
        kind: r.usable ? 'success' : 'error',
        title: r.usable ? 'Registry reachable' : 'Registry unusable',
        description: r.reason,
      }),
    onError: (e) => toast({ kind: 'error', title: 'Test failed', description: toUserMessage(e) }),
  });

  const rows = query.data?.data ?? [];

  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader
            title="Registries"
            description="Local, public, private, and enterprise package registries. Private registries never leak into public search."
            breadcrumbs={[{ label: 'Home', href: '/' }, { label: 'Settings', href: '/settings' }, { label: 'Registries' }]}
          />
          {query.isLoading && <p className="text-sm text-muted-foreground">Loading registries…</p>}
          {query.isError && (
            <ErrorState
              title="Registries unavailable"
              description={query.error instanceof Error ? query.error.message : 'Could not load.'}
              onRetry={() => query.refetch()}
            />
          )}
          {query.data && (
            <div className="grid gap-3 md:grid-cols-2">
              {rows.map((r) => (
                <Card key={r.id}>
                  <CardHeader>
                    <CardTitle className="text-base">{r.name}</CardTitle>
                    <CardDescription>
                      {r.slug} · {r.registry_type || r.kind} · trust {r.trust_level} (
                      {TRUST_ORDER.indexOf(r.trust_level) + 1}/{TRUST_ORDER.length})
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="flex flex-wrap items-center gap-2 text-sm">
                    <span className="text-muted-foreground">
                      {r.visibility} · {r.enabled ? 'enabled' : 'disabled'} · {r.status}
                      {r.mirror_of ? ` · mirror of ${r.mirror_of}` : ''}
                    </span>
                    <span className="flex-1" />
                    <Button size="sm" variant="outline" onClick={() => test.mutate(r.id)} loading={test.isPending}>
                      Test
                    </Button>
                    <Button size="sm" variant="outline" onClick={() => sync.mutate(r.id)} loading={sync.isPending}>
                      Sync
                    </Button>
                  </CardContent>
                </Card>
              ))}
              {rows.length === 0 && (
                <p className="text-sm text-muted-foreground">No registries configured. The local registry is always available offline.</p>
              )}
            </div>
          )}
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Add registry</CardTitle>
              <CardDescription>Secrets are referenced via credential handles, never pasted here.</CardDescription>
            </CardHeader>
            <CardContent className="grid max-w-2xl gap-2">
              <div className="grid gap-2 sm:grid-cols-2">
                <Input value={slug} onChange={(e) => setSlug(e.target.value)} placeholder="Slug (e.g. acme-internal)" aria-label="Registry slug" />
                <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Display name" aria-label="Registry name" />
              </div>
              <div className="grid gap-2 sm:grid-cols-3">
                <select value={registryType} onChange={(e) => setRegistryType(e.target.value)} className="rounded-md border border-input bg-background px-3 py-2 text-sm" aria-label="Registry type">
                  {['LOCAL', 'PUBLIC', 'PRIVATE', 'ORGANIZATION', 'ENTERPRISE', 'GIT', 'OBJECT_STORAGE', 'CLOUD'].map((t) => (
                    <option key={t} value={t}>{t}</option>
                  ))}
                </select>
                <select value={visibility} onChange={(e) => setVisibility(e.target.value)} className="rounded-md border border-input bg-background px-3 py-2 text-sm" aria-label="Visibility">
                  <option value="PRIVATE">PRIVATE</option>
                  <option value="PUBLIC">PUBLIC</option>
                </select>
                <Input value={endpoint} onChange={(e) => setEndpoint(e.target.value)} placeholder="Endpoint (optional)" aria-label="Endpoint" />
              </div>
              <div>
                <Button onClick={() => create.mutate()} loading={create.isPending} disabled={!slug.trim() || !name.trim()}>
                  Add registry
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      </Layout>
    </Protected>
  );
}
