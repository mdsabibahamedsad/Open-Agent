'use client';

import * as React from 'react';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { Input } from '@/components/ui/input';
import { DataTable, Column } from '@/components/ui/table';
import { StatusBadge } from '@/components/ui/status';
import { Button } from '@/components/ui/button';
import { useOrgScopedList, useSearchParamsState } from '@/lib/queries';
import { Search, Plus, Server, Link2, AlertCircle, CheckCircle } from 'lucide-react';

interface MCPServerRow {
  id: string;
  name: string;
  display_name?: string;
  transport: string;
  status: string;
  enabled: boolean;
  trust_level: string;
  capability_version: number;
  last_connected_at?: string;
}

export default function MCPServersPage() {
  const [q, setQ] = React.useState('');
  const debounced = useSearchParamsState(q);
  const { items, isLoading, error, refetch } = useOrgScopedList<MCPServerRow>(
    'mcp-servers',
    ['/organizations/{orgId}/mcp/servers', '/mcp/servers'],
    debounced ? { search: debounced } : undefined,
  );

  const columns: Column<MCPServerRow>[] = [
    {
      key: 'name',
      header: 'Name',
      sortable: true,
      accessor: (r) => r.name,
      render: (r) => (
        <div>
          <span className="font-medium">{r.name}</span>
          {r.display_name && r.display_name !== r.name && (
            <span className="ml-2 text-sm text-muted-foreground">({r.display_name})</span>
          )}
        </div>
      ),
    },
    {
      key: 'transport',
      header: 'Transport',
      render: (r) => (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium rounded-full bg-muted">
          <Server className="h-3 w-3" />
          {r.transport}
        </span>
      ),
    },
    {
      key: 'status',
      header: 'Status',
      render: (r) => (
        <div className="flex items-center gap-2">
          <StatusBadge status={r.status === 'active' ? 'active' : r.status === 'connecting' ? 'pending' : 'inactive'} />
          {r.enabled && <CheckCircle className="h-4 w-4 text-green-500" aria-label="Enabled" />}
        </div>
      ),
    },
    {
      key: 'trust_level',
      header: 'Trust',
      render: (r) => {
        const colors: Record<string, string> = {
          CORE: 'bg-purple-100 text-purple-700',
          VERIFIED: 'bg-blue-100 text-blue-700',
          ORGANIZATION: 'bg-green-100 text-green-700',
          COMMUNITY: 'bg-yellow-100 text-yellow-700',
          UNTRUSTED: 'bg-red-100 text-red-700',
        };
        return (
          <span className={`inline-flex px-2 py-0.5 text-xs font-medium rounded-full ${colors[r.trust_level] || 'bg-gray-100 text-gray-700'}`}>
            {r.trust_level}
          </span>
        );
      },
    },
    {
      key: 'capability_version',
      header: 'Version',
      render: (r) => <span className="text-muted-foreground text-sm">v{r.capability_version}</span>,
    },
    {
      key: 'last_connected_at',
      header: 'Last Connected',
      render: (r) => r.last_connected_at ? (
        <span className="text-muted-foreground text-sm">
          {new Date(r.last_connected_at).toLocaleDateString()}
        </span>
      ) : (
        <span className="text-muted-foreground text-sm">Never</span>
      ),
    },
  ];

  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader
            title="MCP Servers"
            description="Manage Model Context Protocol server connections. Install, configure, and monitor external MCP servers."
            breadcrumbs={[{ label: 'Home', href: '/' }, { label: 'MCP Servers' }]}
            actions={
              <Button onClick={() => window.location.href = '/mcp/install'}>
                <Plus className="h-4 w-4 mr-2" />
                Install Server
              </Button>
            }
          />
          <div className="relative w-full max-w-2xl">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
            <Input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search MCP servers…"
              aria-label="Search MCP servers"
              className="pl-9"
            />
          </div>
          <DataTable
            columns={columns}
            rows={items}
            keyOf={(r) => r.id}
            loading={isLoading}
            error={error}
            onRetry={() => refetch()}
            emptyTitle="No MCP servers installed"
            emptyDescription="Install your first MCP server to connect to external tools, resources, and prompts."
          />
        </div>
      </Layout>
    </Protected>
  );
}

const columns: Column<MCPServerRow>[] = [
  {
    key: 'name',
    header: 'Name',
    sortable: true,
    accessor: (r) => r.name,
    render: (r) => (
      <div>
        <span className="font-medium">{r.name}</span>
        {r.display_name && r.display_name !== r.name && (
          <span className="ml-2 text-sm text-muted-foreground">({r.display_name})</span>
        )}
      </div>
    ),
  },
  {
    key: 'transport',
    header: 'Transport',
    render: (r) => (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium rounded-full bg-muted">
        <Server className="h-3 w-3" />
        {r.transport}
      </span>
    ),
  },
  {
    key: 'status',
    header: 'Status',
    render: (r) => (
      <div className="flex items-center gap-2">
        <StatusBadge status={r.status === 'active' ? 'active' : r.status === 'connecting' ? 'pending' : 'inactive'} />
        {r.enabled && <CheckCircle className="h-4 w-4 text-green-500" aria-label="Enabled" />}
      </div>
    ),
  },
  {
    key: 'trust_level',
    header: 'Trust',
    render: (r) => {
      const colors: Record<string, string> = {
        CORE: 'bg-purple-100 text-purple-700',
        VERIFIED: 'bg-blue-100 text-blue-700',
        ORGANIZATION: 'bg-green-100 text-green-700',
        COMMUNITY: 'bg-yellow-100 text-yellow-700',
        UNTRUSTED: 'bg-red-100 text-red-700',
      };
      return (
        <span className={`inline-flex px-2 py-0.5 text-xs font-medium rounded-full ${colors[r.trust_level] || 'bg-gray-100 text-gray-700'}`}>
          {r.trust_level}
        </span>
      );
    },
  },
  {
    key: 'capability_version',
    header: 'Version',
    render: (r) => <span className="text-muted-foreground text-sm">v{r.capability_version}</span>,
  },
  {
    key: 'last_connected_at',
    header: 'Last Connected',
    render: (r) => r.last_connected_at ? (
      <span className="text-muted-foreground text-sm">
        {new Date(r.last_connected_at).toLocaleDateString()}
      </span>
    ) : (
      <span className="text-muted-foreground text-sm">Never</span>
    ),
  },
];
