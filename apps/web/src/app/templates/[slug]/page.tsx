'use client';

import * as React from 'react';
import { useParams } from 'next/navigation';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { EmptyState, ErrorState } from '@/components/ui/states';
import { StatusBadge } from '@/components/ui/status';
import { useOrganization } from '@/context/OrganizationContext';
import { packagesApi, PackageSummary, PackageVersionInfo } from '@/lib/packages';
import {
  ForkButton,
  InstallWizard,
  PackageDiffView,
  ResourceGraph,
  RiskBadge,
  SecurityReport,
  TrustBadge,
} from '@/features/packages/ui';
import { Download, FileDown } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';

export default function TemplateDetailPage() {
  const params = useParams<{ slug: string }>();
  const slug = params.slug;
  const { currentOrgId } = useOrganization();
  const [wizardOpen, setWizardOpen] = React.useState(false);
  const [selectedVersion, setSelectedVersion] = React.useState('');
  const [compareFrom, setCompareFrom] = React.useState('');
  const [exportMessage, setExportMessage] = React.useState<string | null>(null);

  const pkgQuery = useQuery({
    queryKey: ['package-by-slug', currentOrgId, slug],
    queryFn: async (): Promise<PackageSummary | null> => {
      const res = await packagesApi.list(currentOrgId!, { search: slug, page_size: 20 });
      return (res.data as PackageSummary[]).find((p) => p.slug === slug) ?? null;
    },
    enabled: Boolean(currentOrgId && slug),
  });

  const pkg = pkgQuery.data ?? null;

  const versionsQuery = useQuery({
    queryKey: ['package-versions', currentOrgId, pkg?.id],
    queryFn: () => packagesApi.versions(currentOrgId!, pkg!.id),
    enabled: Boolean(currentOrgId && pkg?.id),
  });
  const versions: PackageVersionInfo[] = (versionsQuery.data?.data as PackageVersionInfo[]) ?? [];

  React.useEffect(() => {
    if (!selectedVersion && versions.length > 0) {
      const published = versions.find((v) => v.status === 'PUBLISHED');
      setSelectedVersion((published ?? versions[0]).version);
      if (versions.length > 1) setCompareFrom(versions[versions.length - 1].version);
    }
  }, [versions, selectedVersion]);

  const detailQuery = useQuery({
    queryKey: ['package-version-detail', currentOrgId, pkg?.id, selectedVersion],
    queryFn: () => packagesApi.versionDetail(currentOrgId!, pkg!.id, selectedVersion),
    enabled: Boolean(currentOrgId && pkg?.id && selectedVersion),
  });

  const securityQuery = useQuery({
    queryKey: ['package-security', currentOrgId, pkg?.id, selectedVersion],
    queryFn: () => packagesApi.security(currentOrgId!, pkg!.id, selectedVersion),
    enabled: Boolean(currentOrgId && pkg?.id && selectedVersion),
  });

  const diffQuery = useQuery({
    queryKey: ['package-diff', currentOrgId, pkg?.id, compareFrom, selectedVersion],
    queryFn: () => packagesApi.diff(currentOrgId!, pkg!.id, compareFrom, selectedVersion),
    enabled: Boolean(currentOrgId && pkg?.id && compareFrom && selectedVersion && compareFrom !== selectedVersion),
  });

  const doExport = async () => {
    if (!currentOrgId || !pkg) return;
    setExportMessage(null);
    try {
      const bundle = await packagesApi.exportBundle(currentOrgId, pkg.id, selectedVersion);
      const blob = new Blob([JSON.stringify(bundle.files, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${pkg.slug}-${selectedVersion}.openagent-package.json`;
      a.click();
      URL.revokeObjectURL(url);
      setExportMessage('Exported. Secrets are never included in exports.');
    } catch (e: unknown) {
      setExportMessage(e instanceof Error ? e.message : 'Export failed.');
    }
  };

  const manifest = (detailQuery.data?.manifest as Record<string, unknown> | undefined) ?? {};
  const resources = ((manifest.resources as { kind: string; slug: string; name: string }[] | undefined) ?? []).slice(0, 30);

  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          {pkgQuery.isLoading && <p className="text-sm text-muted-foreground">Loading package…</p>}
          {pkgQuery.isError && (
            <ErrorState title="Package unavailable" description="Could not load this package." onRetry={() => pkgQuery.refetch()} />
          )}
          {pkgQuery.data === null && !pkgQuery.isLoading && (
            <Card>
              <CardContent>
                <EmptyState title="Package not found" description={`No package with slug "${slug}" is visible to this organization.`} />
              </CardContent>
            </Card>
          )}
          {pkg && (
            <>
              <PageHeader
                title={pkg.name}
                description={pkg.description || 'No description.'}
                breadcrumbs={[{ label: 'Home', href: '/' }, { label: 'Templates', href: '/templates' }, { label: pkg.name }]}
              />
              <div className="flex flex-wrap items-center gap-2">
                <TrustBadge trust={pkg.trust} official={pkg.official} />
                <Badge variant="outline">{pkg.package_type}</Badge>
                {pkg.latest_version && <Badge variant="secondary">latest v{pkg.latest_version}</Badge>}
                <Badge variant="outline">{pkg.license}</Badge>
                <span className="ml-auto flex flex-wrap gap-2">
                  <ForkButton packageId={pkg.id} packageSlug={pkg.slug} />
                  <Button variant="outline" size="sm" onClick={doExport}>
                    <FileDown className="mr-1.5 h-3.5 w-3.5" aria-hidden /> Export
                  </Button>
                  <Button size="sm" onClick={() => setWizardOpen(true)} disabled={!selectedVersion}>
                    <Download className="mr-1.5 h-3.5 w-3.5" aria-hidden /> Install
                  </Button>
                </span>
              </div>
              {exportMessage && <p className="text-xs text-muted-foreground">{exportMessage}</p>}

              <div className="flex flex-wrap items-center gap-2 text-sm">
                <label htmlFor="version-select" className="font-medium">
                  Version
                </label>
                <select
                  id="version-select"
                  className="rounded-md border border-input bg-background px-3 py-1.5"
                  value={selectedVersion}
                  onChange={(e) => setSelectedVersion(e.target.value)}
                >
                  {versions.map((v) => (
                    <option key={v.id} value={v.version}>
                      v{v.version} — {v.status}
                    </option>
                  ))}
                </select>
                {detailQuery.data && <StatusBadge status={detailQuery.data.status} />}
                {securityQuery.data && <RiskBadge risk={String(securityQuery.data.risk ?? 'LOW')} />}
              </div>

              <Tabs defaultValue="overview">
                <TabsList>
                  <TabsTrigger value="overview">Overview</TabsTrigger>
                  <TabsTrigger value="resources">Included resources</TabsTrigger>
                  <TabsTrigger value="graph">Workforce graph</TabsTrigger>
                  <TabsTrigger value="security">Security</TabsTrigger>
                  <TabsTrigger value="versions">Versions & diff</TabsTrigger>
                </TabsList>
                <TabsContent value="overview">
                  <div className="grid gap-4 md:grid-cols-2">
                    <Card>
                      <CardHeader>
                        <CardTitle className="text-base">Capabilities</CardTitle>
                      </CardHeader>
                      <CardContent className="space-y-1 text-sm">
                        <p>
                          Author: <strong>{pkg.author_name || pkg.publisher || '—'}</strong>
                        </p>
                        <p>Categories: {(pkg.categories ?? []).join(', ') || '—'}</p>
                        <p>Tags: {(pkg.tags ?? []).join(', ') || '—'}</p>
                        <p>Visibility: {pkg.visibility}</p>
                      </CardContent>
                    </Card>
                    <Card>
                      <CardHeader>
                        <CardTitle className="text-base">Requirements</CardTitle>
                      </CardHeader>
                      <CardContent className="space-y-1 text-sm">
                        <p>Dependencies: {(manifest.dependencies as unknown[] | undefined)?.length ?? 0}</p>
                        <p>Configuration inputs: {Object.keys(((manifest.configuration as Record<string, unknown> | undefined)?.inputs as object | undefined) ?? {}).length}</p>
                        <p>Approvals: {(((manifest.security as Record<string, unknown> | undefined)?.required_approvals as string[] | undefined) ?? []).join(', ') || 'none declared'}</p>
                      </CardContent>
                    </Card>
                  </div>
                </TabsContent>
                <TabsContent value="resources">
                  <Card>
                    <CardContent>
                      {resources.length === 0 ? (
                        <p className="text-sm text-muted-foreground">No resources in this version.</p>
                      ) : (
                        <ul className="space-y-2 text-sm">
                          {resources.map((r) => (
                            <li key={`${r.kind}-${r.slug}`} className="flex items-center gap-2">
                              <Badge variant="outline">{r.kind}</Badge>
                              <span className="font-medium">{r.name}</span>
                              <span className="text-muted-foreground">{r.slug}</span>
                            </li>
                          ))}
                        </ul>
                      )}
                    </CardContent>
                  </Card>
                </TabsContent>
                <TabsContent value="graph">
                  <Card>
                    <CardContent>
                      {detailQuery.data?.graph ? (
                        <ResourceGraph nodes={detailQuery.data.graph.nodes} edges={detailQuery.data.graph.edges} />
                      ) : (
                        <p className="text-sm text-muted-foreground">Graph unavailable.</p>
                      )}
                    </CardContent>
                  </Card>
                </TabsContent>
                <TabsContent value="security">
                  <Card>
                    <CardContent>
                      {securityQuery.data ? (
                        <SecurityReport
                          findings={securityQuery.data.warnings ?? []}
                          risk={securityQuery.data.risk ?? 'LOW'}
                        />
                      ) : (
                        <p className="text-sm text-muted-foreground">Security report unavailable.</p>
                      )}
                    </CardContent>
                  </Card>
                </TabsContent>
                <TabsContent value="versions">
                  <Card>
                    <CardContent className="space-y-4">
                      <ul className="space-y-1 text-sm">
                        {versions.map((v) => (
                          <li key={v.id} className="flex items-center gap-2">
                            <span className="font-medium">v{v.version}</span>
                            <StatusBadge status={v.status} />
                            <span className="text-muted-foreground">{v.changelog?.slice(0, 80)}</span>
                          </li>
                        ))}
                      </ul>
                      {versions.length > 1 && (
                        <div className="flex flex-wrap items-center gap-2 text-sm">
                          <label htmlFor="compare-from">Compare</label>
                          <select
                            id="compare-from"
                            className="rounded-md border border-input bg-background px-2 py-1"
                            value={compareFrom}
                            onChange={(e) => setCompareFrom(e.target.value)}
                          >
                            {versions.map((v) => (
                              <option key={v.id} value={v.version}>
                                v{v.version}
                              </option>
                            ))}
                          </select>
                          <span>with v{selectedVersion}</span>
                        </div>
                      )}
                      {diffQuery.data && <PackageDiffView diff={diffQuery.data as Record<string, unknown>} />}
                    </CardContent>
                  </Card>
                </TabsContent>
              </Tabs>

              {wizardOpen && (
                <InstallWizard
                  packageId={pkg.id}
                  version={selectedVersion}
                  packageName={pkg.name}
                  open={wizardOpen}
                  onClose={() => setWizardOpen(false)}
                  onInstalled={() => versionsQuery.refetch()}
                />
              )}
            </>
          )}
        </div>
      </Layout>
    </Protected>
  );
}
