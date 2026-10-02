'use client';

import * as React from 'react';
import Link from 'next/link';
import { useQuery } from '@tanstack/react-query';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { useOrganization } from '@/context/OrganizationContext';
import {
  getSdkMeta,
  listProjects,
  listExtensions,
  listDeployments,
} from '@/lib/developer';
import { toUserMessage } from '@/lib/api';

export default function DeveloperHomePage() {
  const { currentOrgId } = useOrganization();
  const sdk = useQuery({ queryKey: ['dev-sdk'], queryFn: getSdkMeta, staleTime: 300_000 });
  const projects = useQuery({
    queryKey: ['dev-projects', currentOrgId],
    queryFn: () => listProjects(currentOrgId ?? ''),
    enabled: !!currentOrgId,
    staleTime: 30_000,
  });
  const extensions = useQuery({
    queryKey: ['dev-extensions', currentOrgId],
    queryFn: () => listExtensions(currentOrgId ?? ''),
    enabled: !!currentOrgId,
    staleTime: 30_000,
  });
  const deployments = useQuery({
    queryKey: ['dev-deployments', currentOrgId],
    queryFn: () => listDeployments(currentOrgId ?? ''),
    enabled: !!currentOrgId,
    staleTime: 30_000,
  });

  const err = projects.error ?? extensions.error ?? deployments.error;
  const counts = [
    { label: 'Projects', value: projects.data?.length ?? 0, href: '/developer/projects', loading: projects.isLoading },
    { label: 'Extensions', value: extensions.data?.length ?? 0, href: '/developer/extensions', loading: extensions.isLoading },
    { label: 'Deployments', value: deployments.data?.length ?? 0, href: '/developer/extensions', loading: deployments.isLoading },
  ];

  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader
            title="Developer Home"
            description="Build, validate, sign and ship OpenAgent extensions. All counts below are live backend data."
            breadcrumbs={[{ label: 'Home', href: '/' }, { label: 'Developer' }]}
            actions={
              <>
                <Link href="/developer/extensions/new"><Button>New extension</Button></Link>
                <Link href="/developer/api"><Button variant="outline">API explorer</Button></Link>
              </>
            }
          />

          {!currentOrgId && (
            <p className="rounded-md border p-4 text-sm text-muted-foreground" role="status">
              Select an organization to load developer data.
            </p>
          )}
          {err && (
            <p className="rounded-md border border-destructive/30 p-4 text-sm text-destructive" role="alert">
              {toUserMessage(err)}
            </p>
          )}

          <div className="grid gap-4 md:grid-cols-3">
            {counts.map((c) => (
              <Card key={c.label}>
                <CardHeader>
                  <CardTitle className="text-sm text-muted-foreground">{c.label}</CardTitle>
                </CardHeader>
                <CardContent className="flex items-end justify-between">
                  <span className="text-3xl font-semibold" aria-label={`${c.label}: ${c.value}`}>
                    {c.loading ? '…' : c.value}
                  </span>
                  <Link href={c.href} className="text-sm text-primary underline">View</Link>
                </CardContent>
              </Card>
            ))}
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle className="text-base">SDK versions</CardTitle>
                <CardDescription>Live from GET /api/v1/developer/sdk (public, no auth).</CardDescription>
              </CardHeader>
              <CardContent>
                {sdk.isLoading && <p className="text-sm text-muted-foreground">Loading SDK metadata…</p>}
                {sdk.error && <p className="text-sm text-destructive" role="alert">{toUserMessage(sdk.error)}</p>}
                {sdk.data && (
                  <dl className="flex flex-wrap gap-2 text-sm">
                    <span><Badge variant="outline">TS {sdk.data.sdk.typescript}</Badge></span>
                    <span><Badge variant="outline">Py {sdk.data.sdk.python}</Badge></span>
                    <span><Badge variant="outline">API {sdk.data.api_version}</Badge></span>
                    <span><Badge variant="outline">ext-api {sdk.data.extension_api}</Badge></span>
                    <span><Badge variant="outline">manifest v{sdk.data.manifest_version}</Badge></span>
                  </dl>
                )}
                <div className="mt-4 flex flex-wrap gap-2">
                  <Link href="/developer/sdk"><Button variant="outline" size="sm">SDK reference</Button></Link>
                  <Link href="/developer/cli"><Button variant="outline" size="sm">CLI reference</Button></Link>
                  <Link href="/developer/docs"><Button variant="outline" size="sm">Guides</Button></Link>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="text-base">Quickstart</CardTitle>
                <CardDescription>Validate → scan → sign → publish. Secrets never leave the vault.</CardDescription>
              </CardHeader>
              <CardContent>
                <ol className="list-decimal space-y-1 pl-5 text-sm">
                  <li>Create a <Link className="text-primary underline" href="/developer/projects">project</Link> (gets dev/staging/prod environments).</li>
                  <li>Scaffold with the <Link className="text-primary underline" href="/developer/extensions/new">extension builder</Link> — least-privilege permissions by default.</li>
                  <li>Validate, test and package from the <Link className="text-primary underline" href="/developer/extensions">extension detail</Link> page.</li>
                  <li>Sign offline, then publish. Installs beyond the manifest are refused.</li>
                </ol>
                <div className="mt-4 flex flex-wrap gap-2">
                  <Link href="/developer/registry"><Button variant="outline" size="sm">Local registry</Button></Link>
                  <Link href="/developer/settings"><Button variant="outline" size="sm">Webhooks &amp; usage</Button></Link>
                </div>
              </CardContent>
            </Card>
          </div>
        </div>
      </Layout>
    </Protected>
  );
}
