'use client';

import * as React from 'react';
import Link from 'next/link';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { DataTable, Column } from '@/components/ui/table';
import { StatusBadge } from '@/components/ui/status';
import { useOrganization } from '@/context/OrganizationContext';
import { createProject, listProjects, DevProject } from '@/lib/developer';
import { toUserMessage } from '@/lib/api';

export default function DeveloperProjectsPage() {
  const { currentOrgId } = useOrganization();
  const qc = useQueryClient();
  const [q, setQ] = React.useState('');
  const [slug, setSlug] = React.useState('');
  const [name, setName] = React.useState('');
  const [creating, setCreating] = React.useState(false);
  const [formError, setFormError] = React.useState<string | null>(null);

  const query = useQuery({
    queryKey: ['dev-projects', currentOrgId],
    queryFn: () => listProjects(currentOrgId ?? ''),
    enabled: !!currentOrgId,
    staleTime: 30_000,
  });
  const items = (query.data ?? []).filter(
    (p) => !q || p.slug.includes(q.toLowerCase()) || p.name.toLowerCase().includes(q.toLowerCase()),
  );
  const columns: Column<DevProject>[] = [
    {
      key: 'slug', header: 'Project', sortable: true, accessor: (r) => r.slug,
      render: (r) => <Link href={`/developer/projects/${r.id}`} className="font-medium text-primary underline">{r.slug}</Link>,
    },
    { key: 'name', header: 'Name', accessor: (r) => r.name, render: (r) => <span>{r.name}</span> },
    { key: 'status', header: 'Status', render: (r) => <StatusBadge status={r.status ?? 'active'} /> },
  ];

  async function onCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!currentOrgId) return;
    setCreating(true);
    setFormError(null);
    try {
      await createProject(currentOrgId, { slug: slug.trim(), name: name.trim() });
      setSlug('');
      setName('');
      await qc.invalidateQueries({ queryKey: ['dev-projects'] });
    } catch (err) {
      setFormError(toUserMessage(err));
    } finally {
      setCreating(false);
    }
  }

  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader
            title="Projects"
            description="Org-scoped developer projects. Each project gets development, staging and production environments."
            breadcrumbs={[{ label: 'Developer', href: '/developer' }, { label: 'Projects' }]}
          />
          <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
            <div className="space-y-3">
              <Input
                value={q} onChange={(e) => setQ(e.target.value)}
                placeholder="Filter projects…" aria-label="Filter projects" className="max-w-sm"
              />
              <DataTable
                columns={columns} rows={items} keyOf={(r) => r.id}
                loading={query.isLoading}
                error={query.error ? toUserMessage(query.error) : null}
                onRetry={() => query.refetch()}
                emptyTitle="No projects yet"
                emptyDescription="Create your first project to get dev/staging/prod environments."
              />
            </div>
            <form onSubmit={onCreate} className="h-fit space-y-3 rounded-lg border p-4" aria-label="Create project">
              <h2 className="font-medium">New project</h2>
              <Input label="Slug" value={slug} onChange={(e) => setSlug(e.target.value)} placeholder="my-project" required minLength={2} />
              <Input label="Name" value={name} onChange={(e) => setName(e.target.value)} placeholder="My Project" required />
              {formError && <p className="text-sm text-destructive" role="alert">{formError}</p>}
              <Button type="submit" loading={creating} disabled={!currentOrgId}>Create project</Button>
            </form>
          </div>
        </div>
      </Layout>
    </Protected>
  );
}
