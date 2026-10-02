'use client';

import * as React from 'react';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { Button } from '@/components/ui/button';
import { StatusBadge } from '@/components/ui/status';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { PermissionGate } from '@/components/PermissionGate';
import { useEscalations, useManagementMutation } from '@/features/management/api';

const ACTIONS = [
  { id: 'ack', label: 'Acknowledge' },
  { id: 'progress', label: 'Start progress' },
  { id: 'resolve', label: 'Resolve' },
  { id: 'chain', label: 'Escalate up' },
  { id: 'close', label: 'Close' },
] as const;

export default function EscalationCenterPage() {
  const { items, isLoading, refetch } = useEscalations();
  const [actionError, setActionError] = React.useState<string | null>(null);

  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader
            title="Escalation Center"
            description="Severity, source, holder, reason, recommended action, status, history."
            breadcrumbs={[
              { label: 'Home', href: '/' },
              { label: 'Management', href: '/management' },
              { label: 'Escalations' },
            ]}
          />
          {isLoading && <p className="text-sm text-muted-foreground">Loading escalations…</p>}
          {actionError && (
            <p role="alert" className="text-sm text-destructive">
              {actionError}
            </p>
          )}
          <ul className="space-y-3">
            {items.length === 0 && !isLoading && (
              <li className="text-sm text-muted-foreground">No open escalations.</li>
            )}
            {items.map((e) => (
              <li key={e.id}>
                <Card>
                  <CardHeader>
                    <CardTitle>
                      {e.severity.toUpperCase()} · {e.trigger}
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="flex flex-wrap items-center gap-2 text-sm">
                      <StatusBadge status={e.status} />
                      <span className="text-muted-foreground">
                        level {e.chain_level} of {e.chain.join(' → ')}
                      </span>
                    </div>
                    <p className="mt-2 text-sm">{e.reason}</p>
                    {e.recommended_action && (
                      <p className="mt-1 text-sm text-muted-foreground">
                        Recommended: {e.recommended_action}
                      </p>
                    )}
                    {e.history.length > 0 && (
                      <ul className="mt-2 space-y-1 border-l pl-3 text-xs text-muted-foreground">
                        {e.history.map((h, i) => (
                          <li key={i}>{JSON.stringify(h)}</li>
                        ))}
                      </ul>
                    )}
                    <div className="mt-3 flex flex-wrap gap-2">
                      {ACTIONS.map((a) => (
                        <EscalationAction
                          key={a.id}
                          escalationId={e.id}
                          action={a.id}
                          label={a.label}
                          onDone={() => refetch()}
                          onError={setActionError}
                        />
                      ))}
                    </div>
                  </CardContent>
                </Card>
              </li>
            ))}
          </ul>
        </div>
      </Layout>
    </Protected>
  );
}

function EscalationAction({
  escalationId,
  action,
  label,
  onDone,
  onError,
}: {
  escalationId: string;
  action: string;
  label: string;
  onDone: () => void;
  onError: (msg: string | null) => void;
}) {
  const mutation = useManagementMutation(`/escalations/${escalationId}/${action}`);
  return (
    <PermissionGate permission="agent:create">
      <Button
        size="sm"
        variant="outline"
        disabled={mutation.isPending}
        onClick={() =>
          mutation.mutateAsync({ note: '' }).then(
            () => {
              onError(null);
              onDone();
            },
            (err: unknown) => onError(err instanceof Error ? err.message : 'Action failed.'),
          )
        }
      >
        {label}
      </Button>
    </PermissionGate>
  );
}
