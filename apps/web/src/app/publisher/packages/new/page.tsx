'use client';

import * as React from 'react';
import { useRouter } from 'next/navigation';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useOrganization } from '@/context/OrganizationContext';
import { toUserMessage } from '@/lib/api';
import { listingsApi, marketplacesApi, publishersApi } from '@/lib/marketplace';
import { packagesApi, PackageSummary } from '@/lib/packages';
import { StudioShell } from '../../shell';
import { useQuery } from '@tanstack/react-query';

export default function NewListingPage() {
  const router = useRouter();
  const { currentOrgId } = useOrganization();
  const [marketplaceId, setMarketplaceId] = React.useState('');
  const [packageId, setPackageId] = React.useState('');
  const [publisherId, setPublisherId] = React.useState('');
  const [slug, setSlug] = React.useState('');
  const [title, setTitle] = React.useState('');
  const [shortDescription, setShortDescription] = React.useState('');
  const [fullDescription, setFullDescription] = React.useState('');
  const [category, setCategory] = React.useState('');
  const [license, setLicense] = React.useState('Apache-2.0');
  const [pricingModel, setPricingModel] = React.useState('FREE');
  const [tags, setTags] = React.useState('');
  const [busy, setBusy] = React.useState(false);
  const [message, setMessage] = React.useState<string | null>(null);

  const publishersQuery = useQuery({
    queryKey: ['studio-publishers', currentOrgId],
    queryFn: () => publishersApi.list(),
    staleTime: 60_000,
  });
  const marketplacesQuery = useQuery({
    queryKey: ['studio-marketplaces', currentOrgId],
    queryFn: () => marketplacesApi.list(currentOrgId!),
    enabled: Boolean(currentOrgId),
    staleTime: 60_000,
  });
  const packagesQuery = useQuery({
    queryKey: ['studio-all-packages', currentOrgId],
    queryFn: () => packagesApi.list(currentOrgId!, { page_size: 100 }),
    enabled: Boolean(currentOrgId),
    staleTime: 30_000,
  });
  const pkgs: PackageSummary[] = (packagesQuery.data?.data as PackageSummary[]) ?? [];

  const submit = async () => {
    if (!currentOrgId) return;
    setBusy(true);
    setMessage(null);
    try {
      const created = await listingsApi.create(currentOrgId, {
        marketplace_id: marketplaceId,
        package_id: packageId,
        publisher_id: publisherId,
        slug,
        title,
        short_description: shortDescription,
        full_description: fullDescription,
        category,
        license,
        pricing_model: pricingModel,
        tags: tags.split(',').map((t) => t.trim()).filter(Boolean),
      });
      router.push(`/publisher/packages/${(created as { id: string }).id}`);
    } catch (e: unknown) {
      setMessage(toUserMessage(e));
      setBusy(false);
    }
  };

  const valid = marketplaceId && packageId && publisherId && slug && title;

  return (
    <StudioShell title="New listing" description="Package an existing reusable package for distribution. It starts as DRAFT; submit runs validation, policy and security gates.">
      <Card>
        <CardHeader><CardTitle className="text-base">Listing details</CardTitle></CardHeader>
        <CardContent className="grid max-w-2xl gap-3 text-sm">
          <label>Marketplace
            <select className="w-full rounded-md border border-input bg-background px-3 py-2" value={marketplaceId} onChange={(e) => setMarketplaceId(e.target.value)} aria-label="Marketplace">
              <option value="">Select a marketplace…</option>
              {(marketplacesQuery.data?.data ?? []).map((m) => (
                <option key={m.id} value={m.id}>{m.name} ({m.type})</option>
              ))}
            </select>
          </label>
          <label>Package
            <select className="w-full rounded-md border border-input bg-background px-3 py-2" value={packageId} onChange={(e) => setPackageId(e.target.value)} aria-label="Package">
              <option value="">Select a package…</option>
              {pkgs.map((p) => (
                <option key={p.id} value={p.id}>{p.name} ({p.slug})</option>
              ))}
            </select>
          </label>
          <label>Publisher
            <select className="w-full rounded-md border border-input bg-background px-3 py-2" value={publisherId} onChange={(e) => setPublisherId(e.target.value)} aria-label="Publisher">
              <option value="">Select a publisher…</option>
              {(publishersQuery.data?.data ?? []).map((p) => (
                <option key={p.id} value={p.id}>{p.display_name} ({p.slug})</option>
              ))}
            </select>
          </label>
          <label>Slug<Input value={slug} onChange={(e) => setSlug(e.target.value)} placeholder="my-workforce" aria-label="Slug" /></label>
          <label>Title<Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="My Workforce" aria-label="Title" /></label>
          <label>Short description<Input value={shortDescription} onChange={(e) => setShortDescription(e.target.value)} aria-label="Short description" /></label>
          <label>Full description (markdown-lite, no scripts)
            <textarea className="min-h-24 w-full rounded-md border border-input bg-background px-3 py-2" value={fullDescription} onChange={(e) => setFullDescription(e.target.value)} aria-label="Full description" />
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label>Category<Input value={category} onChange={(e) => setCategory(e.target.value)} placeholder="ai-agents" aria-label="Category" /></label>
            <label>License<Input value={license} onChange={(e) => setLicense(e.target.value)} aria-label="License" /></label>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <label>Pricing
              <select className="w-full rounded-md border border-input bg-background px-3 py-2" value={pricingModel} onChange={(e) => setPricingModel(e.target.value)} aria-label="Pricing model">
                {['FREE', 'ONE_TIME', 'SUBSCRIPTION', 'USAGE_BASED', 'TIERED', 'ENTERPRISE', 'CUSTOM'].map((m) => (
                  <option key={m} value={m}>{m}</option>
                ))}
              </select>
            </label>
            <label>Tags (comma-separated)<Input value={tags} onChange={(e) => setTags(e.target.value)} placeholder="research, browser" aria-label="Tags" /></label>
          </div>
          {message && <p role="alert" className="text-destructive">{message}</p>}
          <div><Button onClick={submit} disabled={!valid || busy}>Create draft listing</Button></div>
        </CardContent>
      </Card>
    </StudioShell>
  );
}
