'use client';

import * as React from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { cn } from '@/lib/utils';

const TABS = [
  { href: '/publisher/packages', label: 'Packages', prefix: '/publisher/packages' },
  { href: '/publisher/listings', label: 'Listings', prefix: '/publisher/listings' },
  { href: '/publisher/products', label: 'Products', prefix: '/publisher/products' },
  { href: '/publisher/revenue', label: 'Revenue', prefix: '/publisher/revenue' },
  { href: '/publisher/reviews', label: 'Reviews', prefix: '/publisher/reviews' },
  { href: '/publisher/analytics', label: 'Analytics', prefix: '/publisher/analytics' },
  { href: '/publisher/security', label: 'Security', prefix: '/publisher/security' },
];

export function StudioShell({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader
            title={title}
            description={description}
            breadcrumbs={[{ label: 'Home', href: '/' }, { label: 'Publisher Studio', href: '/publisher/packages' }, { label: title }]}
          />
          <nav className="flex flex-wrap gap-1" aria-label="Publisher studio">
            {TABS.map((t) => {
              const active = pathname === t.href || pathname.startsWith(`${t.prefix}/`);
              return (
                <Link
                  key={t.href}
                  href={t.href}
                  aria-current={active ? 'page' : undefined}
                  className={cn(
                    'rounded-md px-3 py-2 text-sm font-medium',
                    active ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-accent hover:text-foreground',
                  )}
                >
                  {t.label}
                </Link>
              );
            })}
          </nav>
          {children}
        </div>
      </Layout>
    </Protected>
  );
}
