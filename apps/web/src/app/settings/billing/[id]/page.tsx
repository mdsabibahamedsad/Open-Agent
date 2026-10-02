'use client';

export const dynamic = 'force-dynamic';

import { useQuery } from '@tanstack/react-query';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { ErrorState } from '@/components/ui/states';
import { commerceApi, formatMinor } from '@/lib/commerce';

export default function InvoiceDetailPage({ params }: { params: { id: string } }) {
  const query = useQuery({
    queryKey: ['invoice', params.id],
    queryFn: () => commerceApi.invoice(params.id),
  });
  const invoice = query.data;

  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader
            title="Invoice"
            description="Secure invoice detail. Access is authenticated and organization-scoped."
            breadcrumbs={[
              { label: 'Home', href: '/' },
              { label: 'Settings', href: '/settings' },
              { label: 'Billing', href: '/settings/billing' },
              { label: 'Invoice' },
            ]}
          />
          {query.isLoading && <p className="text-sm text-muted-foreground">Loading invoice…</p>}
          {query.isError && (
            <ErrorState title="Invoice unavailable" description="Could not load." onRetry={() => query.refetch()} />
          )}
          {invoice && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">
                  {formatMinor(invoice.total_minor, invoice.currency)} · {invoice.status}
                </CardTitle>
              </CardHeader>
              <CardContent className="text-sm">
                <p>Subtotal: {formatMinor(invoice.subtotal_minor, invoice.currency)}</p>
                <p>Tax: {formatMinor(invoice.tax_minor, invoice.currency)}</p>
                <p>Discount: {formatMinor(invoice.discount_minor, invoice.currency)}</p>
                <ul className="mt-3 space-y-2">
                  {invoice.lines.map((line, i) => (
                    <li key={i} className="rounded-md border px-3 py-2">
                      {line.description || '(no description)'} · ×{line.quantity} ·{' '}
                      {formatMinor(line.amount_minor, invoice.currency)}
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}
        </div>
      </Layout>
    </Protected>
  );
}
