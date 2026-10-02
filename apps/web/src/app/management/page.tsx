'use client';

import * as React from 'react';
import Link from 'next/link';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { StatusBadge } from '@/components/ui/status';
import { PermissionGate } from '@/components/PermissionGate';
import { useManagerConsole } from '@/features/management/api';

export default function ManagementPage() {
  const { console: data, isLoading } = useManagerConsole();

  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader
            title="Manager Console"
            description="Active teams, tasks, delegations, escalations, and worker health."
            breadcrumbs={[{ label: 'Home', href: '/' }, { label: 'Management' }]}
            actions={
              <PermissionGate permission="agent:read">
                <Link href="/management/escalations" className="underline text-sm">
                  Escalation Center
                </Link>
              </PermissionGate>
            }
          />
          {isLoading && <p className="text-sm text-muted-foreground">Loading console…</p>}
          {data && (
            <>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <Stat title="Active tasks" value={data.active_tasks} />
                <Stat title="Blocked tasks" value={data.blocked_tasks} alert={data.blocked_tasks > 0} />
                <Stat title="Failed tasks" value={data.failed_tasks} alert={data.failed_tasks > 0} />
                <Stat
                  title="Open escalations"
                  value={data.open_escalations}
                  alert={data.open_escalations > 0}
                />
                <Stat title="Active teams" value={data.active_teams} />
                <Stat title="Pending delegations" value={data.pending_delegations} />
              </div>
              <div className="grid gap-3 lg:grid-cols-2">
                <Card>
                  <CardHeader>
                    <CardTitle>Teams</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <ul className="space-y-1 text-sm">
                      {data.teams.length === 0 && (
                        <li className="text-muted-foreground">No teams.</li>
                      )}
                      {data.teams.map((t) => (
                        <li key={t.id} className="flex items-center gap-2">
                          <span className="font-medium">{t.name}</span>
                          <StatusBadge status={t.status} />
                        </li>
                      ))}
                    </ul>
                  </CardContent>
                </Card>
                <Card>
                  <CardHeader>
                    <CardTitle>Escalations</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <ul className="space-y-1 text-sm">
                      {data.escalations.length === 0 && (
                        <li className="text-muted-foreground">No open escalations.</li>
                      )}
                      {data.escalations.map((e) => (
                        <li key={e.id} className="flex items-center gap-2">
                          <span className="font-medium">{e.severity}</span>
                          <StatusBadge status={e.status} />
                        </li>
                      ))}
                    </ul>
                  </CardContent>
                </Card>
              </div>
            </>
          )}
        </div>
      </Layout>
    </Protected>
  );
}

function Stat({ title, value, alert }: { title: string; value: number; alert?: boolean }) {
  return (
    <Card>
      <CardContent className="pt-6">
        <p className="text-xs uppercase text-muted-foreground">{title}</p>
        <p className={`text-2xl font-semibold ${alert ? 'text-destructive' : ''}`}>{value}</p>
      </CardContent>
    </Card>
  );
}
