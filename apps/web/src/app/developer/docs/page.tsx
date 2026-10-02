'use client';

import Link from 'next/link';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';

const GUIDES = [
  { href: '/developer/projects', title: 'Projects & environments', desc: 'One project owns dev/staging/prod. Production secrets are refused in development.' },
  { href: '/developer/extensions/new', title: 'Build your first extension', desc: 'Wizard: type → manifest → least-privilege permissions → review.' },
  { href: '/developer/extensions', title: 'Lifecycle: validate → publish', desc: 'Validate, test, package, sign offline, then publish behind the scan gate.' },
  { href: '/developer/sdk', title: 'SDK reference', desc: 'Install commands, TS + Python examples, permission catalog.' },
  { href: '/developer/cli', title: 'CLI reference', desc: 'Auth, projects, extensions, registry and webhooks from the terminal.' },
  { href: '/developer/api', title: 'API explorer', desc: 'Try every developer endpoint with your org context.' },
  { href: '/developer/registry', title: 'Local registry', desc: 'Offline .oaext packages for air-gapped installs.' },
  { href: '/developer/marketplace', title: 'Publish to Marketplace', desc: 'Checklist: validate → scan → sign → publish.' },
  { href: '/developer/settings', title: 'Webhooks & usage', desc: 'Event delivery with signing secrets; aggregated usage with no PII.' },
];

const SECURITY = [
  { t: 'Secret handling', d: 'Secrets live in the credential store as references (e.g. secret:access). Values are injected at runtime, redacted in logs, and publishing is blocked when scanners find embedded secrets.' },
  { t: 'Least privilege', d: 'New extensions start with tool:execute + filesystem:workspace only. Installs cannot grant more than the manifest declares; extra grants return 403.' },
  { t: 'Sandbox', d: 'Code runs inside the Sandbox boundary and tests use deterministic mocks — the host is never touched and no credentials are required for contract tests.' },
  { t: 'SSRF', d: 'network:restricted reaches private networks and needs human approval. Webhook URLs must be https (or http://localhost for dev). Production-looking secrets are refused in development environments.' },
  { t: 'Signing', d: 'Two-step Ed25519 signing: the server returns the canonical digest, you sign offline, then submit the signature. Private keys never leave your machine.' },
];

export default function DeveloperDocsPage() {
  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader title="Developer guides" description="Guides across the portal plus the security notes every publisher must read."
            breadcrumbs={[{ label: 'Developer', href: '/developer' }, { label: 'Docs' }]} />
          <section aria-label="Guides">
            <h2 className="mb-2 text-lg font-semibold">Guides</h2>
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {GUIDES.map((g) => (
                <Card key={g.href}>
                  <CardHeader><CardTitle className="text-base">{g.title}</CardTitle><CardDescription>{g.desc}</CardDescription></CardHeader>
                  <CardContent><Link href={g.href} className="text-sm text-primary underline">Open guide</Link></CardContent>
                </Card>
              ))}
            </div>
          </section>
          <section aria-label="Security notes">
            <h2 className="mb-2 text-lg font-semibold">Security notes</h2>
            <div className="grid gap-4 md:grid-cols-2">
              {SECURITY.map((s) => (
                <Card key={s.t}>
                  <CardHeader><CardTitle className="text-base">{s.t}</CardTitle></CardHeader>
                  <CardContent><p className="text-sm text-muted-foreground">{s.d}</p></CardContent>
                </Card>
              ))}
            </div>
          </section>
        </div>
      </Layout>
    </Protected>
  );
}
