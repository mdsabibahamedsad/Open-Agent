'use client';

import * as React from 'react';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { StatusBadge } from '@/components/ui/status';
import { DataTable, Column } from '@/components/ui/table';
import { Separator } from '@/components/ui/separator';
import { useParams, useRouter } from 'next/navigation';
import { useOrgScopedList, useOrgScopedMutation } from '@/lib/queries';
import { api } from '@/lib/api';
import { Server, Link2, Terminal, Globe, CheckCircle2, AlertCircle, Shield, RefreshCw, Power, Plug, Database, FileText, Code, Settings, ChevronLeft, ChevronRight } from 'lucide-react';

interface MCPServerDetail {
  id: string;
  name: string;
  display_name?: string;
  description?: string;
  transport: string;
  endpoint?: string;
  command?: string;
  args: string[];
  env: Record<string, string>;
  trust_level: string;
  scope: string;
  status: string;
  enabled: boolean;
  capability_version: number;
  last_connected_at?: string;
  connection_error?: string;
  connections_count: number;
  tools_count: number;
  resources_count: number;
  prompts_count: number;
  health?: {
    status: string;
    last_check: string;
    avg_latency_ms: number;
    tool_success: number;
    tool_failure: number;
  };
}

interface ToolRow {
  id: string;
  name: string;
  display_name?: string;
  risk_level: string;
  capabilities: string[];
  status: string;
}

interface ResourceRow {
  id: string;
  uri: string;
  name: string;
  mime_type?: string;
  status: string;
}

interface PromptRow {
  id: string;
  name: string;
  title?: string;
  description?: string;
  status: string;
}

export default function MCPServerDetailPage() {
  const params = useParams();
  const serverId = params.id as string;
  const router = useRouter();

  const { items: server, isLoading: serverLoading, refetch: refetchServer } = useOrgScopedList<any>(
    'mcp-server-detail',
    [`/organizations/{orgId}/mcp/servers/${serverId}`, `/mcp/servers/${serverId}`],
    undefined,
    { enabled: !!serverId, staleTime: 0 }
  );

  const { items: tools, isLoading: toolsLoading } = useOrgScopedList<ToolRow>(
    'mcp-tools',
    [`/organizations/{orgId}/mcp/servers/${serverId}/tools`, `/mcp/servers/${serverId}/tools`],
    undefined,
    { enabled: !!serverId }
  );

  const { items: resources, isLoading: resourcesLoading } = useOrgScopedList<ResourceRow>(
    'mcp-resources',
    [`/organizations/{orgId}/mcp/servers/${serverId}/resources`, `/mcp/servers/${serverId}/resources`],
    undefined,
    { enabled: !!serverId }
  );

  const { items: prompts, isLoading: promptsLoading } = useOrgScopedList<PromptRow>(
    'mcp-prompts',
    [`/organizations/{orgId}/mcp/servers/${serverId}/prompts`, `/mcp/servers/${serverId}/prompts`],
    undefined,
    { enabled: !!serverId }
  );

  const { mutate: activateServer } = useOrgScopedMutation(
    (data) => api.post(`/mcp/servers/${serverId}/activate`, data),
    { onSuccess: () => refetchServer() }
  );

  const { mutate: deactivateServer } = useOrgScopedMutation(
    (data) => api.post(`/mcp/servers/${serverId}/deactivate`, data),
    { onSuccess: () => refetchServer() }
  );

  const { mutate: refreshServer } = useOrgScopedMutation(
    (data) => api.post(`/mcp/servers/${serverId}/refresh`, data),
    { onSuccess: () => refetchServer() }
  );

  const { mutate: healthCheck } = useOrgScopedMutation(
    (data) => api.post(`/mcp/servers/${serverId}/health-check`, data),
    { onSuccess: () => refetchServer() }
  );

  const [activeTab, setActiveTab] = React.useState('overview');

  const serverData = server[0];

  if (serverLoading || !serverData) {
    return (
      <Protected>
        <Layout>
          <div className="oa-page">
            <PageHeader title="Loading..." description="Loading server details" />
          </div>
        </Layout>
      </Protected>
    );
  }

  const serverInfo = serverData as MCPServerDetail;

  const trustColors: Record<string, string> = {
    CORE: 'bg-purple-100 text-purple-700',
    VERIFIED: 'bg-blue-100 text-blue-700',
    ORGANIZATION: 'bg-green-100 text-green-700',
    COMMUNITY: 'bg-yellow-100 text-yellow-700',
    UNTRUSTED: 'bg-red-100 text-red-700',
  };

  const transportIcons: Record<string, React.ReactNode> = {
    streamable_http: <Globe className="h-4 w-4" />,
    sse: <Link2 className="h-4 w-4" />,
    stdio: <Terminal className="h-4 w-4" />,
    websocket: <Globe className="h-4 w-4" />,
  };

  const transportLabels: Record<string, string> = {
    streamable_http: 'Streamable HTTP',
    sse: 'Server-Sent Events',
    stdio: 'STDIO',
    websocket: 'WebSocket',
  };

  const overviewContent = (
    <div className="space-y-6">
      {/* Header Card */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <div>
            <CardTitle className="flex items-center gap-3">
              <span className="text-2xl">{transportIcons[serverInfo.transport] || <Server className="h-6 w-6" />}</span>
              {serverInfo.name}
            </CardTitle>
            <CardDescription>
              {serverInfo.description || 'No description'}
            </CardDescription>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant={serverInfo.enabled ? 'outline' : 'default'}
              onClick={() => serverInfo.enabled ? deactivateServer({}) : activateServer({})}
              disabled={serverInfo.status === 'connecting'}
            >
              {serverInfo.enabled ? (
                <>
                  <Power className="h-4 w-4 mr-2" />
                  Deactivate
                </>
              ) : (
                <>
                  <Plug className="h-4 w-4 mr-2" />
                  Activate
                </>
              )}
            </Button>
            <Button variant="outline" onClick={() => refreshServer({})}>
              <RefreshCw className="h-4 w-4 mr-2" />
              Refresh
            </Button>
            <Button variant="outline" onClick={() => healthCheck({})}>
              <Shield className="h-4 w-4 mr-2" />
              Health Check
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-6">
          {/* Status Row */}
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            <div className="flex items-center gap-3 p-4 bg-muted/50 rounded-lg">
              <div className="p-2 bg-primary/10 rounded-lg text-primary">
                <Server className="h-5 w-5" />
              </div>
              <div>
                <p className="text-sm text-muted-foreground">Status</p>
                <div className="flex items-center gap-2">
                  <StatusBadge status={serverInfo.status === 'active' ? 'active' : serverInfo.status === 'connecting' ? 'pending' : 'inactive'} />
                  {serverInfo.enabled && <CheckCircle2 className="h-4 w-4 text-green-500" aria-label="Enabled" />}
                </div>
              </div>
            </div>

            <div className="flex items-center gap-3 p-4 bg-muted/50 rounded-lg">
              <div className="p-2 bg-primary/10 rounded-lg text-primary">
                {transportIcons[serverInfo.transport] || <Server className="h-5 w-5" />}
              </div>
              <div>
                <p className="text-sm text-muted-foreground">Transport</p>
                <p className="font-medium capitalize">{transportLabels[serverInfo.transport] || serverInfo.transport}</p>
              </div>
            </div>

            <div className="flex items-center gap-3 p-4 bg-muted/50 rounded-lg">
              <div className="p-2 bg-primary/10 rounded-lg text-primary">
                <Shield className="h-5 w-5" />
              </div>
              <div>
                <p className="text-sm text-muted-foreground">Trust Level</p>
                <Badge className={trustColors[serverInfo.trust_level] || 'bg-gray-100 text-gray-700'}>
                  {serverInfo.trust_level}
                </Badge>
              </div>
            </div>

            <div className="flex items-center gap-3 p-4 bg-muted/50 rounded-lg">
              <div className="p-2 bg-primary/10 rounded-lg text-primary">
                <Database className="h-5 w-5" />
              </div>
              <div>
                <p className="text-sm text-muted-foreground">Capability Version</p>
                <p className="font-medium">v{serverInfo.capability_version}</p>
              </div>
            </div>
          </div>

          {/* Connection Details */}
          <Separator />
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div className="space-y-3">
              <h4 className="font-medium">Connection Details</h4>
              <div className="grid grid-cols-2 gap-4 text-sm">
                <div>
                  <p className="text-muted-foreground">Transport</p>
                  <p className="font-medium capitalize">{serverInfo.transport.replace('_', ' ')}</p>
                </div>
                {serverInfo.endpoint && (
                  <div>
                    <p className="text-muted-foreground">Endpoint</p>
                    <p className="font-medium truncate">{serverInfo.endpoint}</p>
                  </div>
                )}
                {serverInfo.command && (
                  <div>
                    <p className="text-muted-foreground">Command</p>
                    <p className="font-medium font-mono text-sm truncate">{serverInfo.command}</p>
                  </div>
                )}
                <div>
                  <p className="text-muted-foreground">Trust Level</p>
                  <p className="font-medium">{serverInfo.trust_level}</p>
                </div>
                <div>
                  <p className="text-muted-foreground">Scope</p>
                  <p className="font-medium capitalize">{serverInfo.scope.toLowerCase()}</p>
                </div>
                <div>
                  <p className="text-muted-foreground">Args</p>
                  <p className="font-medium">{serverInfo.args.length} args</p>
                </div>
              </div>
            </div>

            <div className="space-y-3">
              <h4 className="font-medium">Capabilities</h4>
              <div className="grid grid-cols-3 gap-4 text-center">
                <div className="p-4 bg-muted/50 rounded-lg">
                  <p className="text-2xl font-bold">{serverInfo.tools_count}</p>
                  <p className="text-sm text-muted-foreground">Tools</p>
                </div>
                <div className="p-4 bg-muted/50 rounded-lg">
                  <p className="text-2xl font-bold">{serverInfo.resources_count}</p>
                  <p className="text-sm text-muted-foreground">Resources</p>
                </div>
                <div className="p-4 bg-muted/50 rounded-lg">
                  <p className="text-2xl font-bold">{serverInfo.prompts_count}</p>
                  <p className="text-sm text-muted-foreground">Prompts</p>
                </div>
              </div>
            </div>
          </div>

          {/* Health Status */}
          {serverInfo.health && (
            <>
              <Separator />
              <div className="space-y-3">
                <h4 className="font-medium">Health Status</h4>
                <div className="grid grid-cols-1 md:grid-cols-5 gap-4 text-center">
                  <div className="p-4 bg-muted/50 rounded-lg">
                    <p className="text-2xl font-bold">{serverInfo.health.avg_latency_ms}ms</p>
                    <p className="text-sm text-muted-foreground">Avg Latency</p>
                  </div>
                  <div className="p-4 bg-muted/50 rounded-lg">
                    <p className="text-2xl font-bold text-green-600">{serverInfo.health.tool_success}</p>
                    <p className="text-sm text-muted-foreground">Tool Success</p>
                  </div>
                  <div className="p-4 bg-muted/50 rounded-lg">
                    <p className="text-2xl font-bold text-red-600">{serverInfo.health.tool_failure}</p>
                    <p className="text-sm text-muted-foreground">Tool Failures</p>
                  </div>
                  <div className="p-4 bg-muted/50 rounded-lg">
                    <p className="text-2xl font-bold">{new Date(serverInfo.health.last_check).toLocaleTimeString()}</p>
                    <p className="text-sm text-muted-foreground">Last Check</p>
                  </div>
                  <div className="p-4 bg-muted/50 rounded-lg">
                    <Badge variant={serverInfo.health.status === 'HEALTHY' ? 'default' : serverInfo.health.status === 'DEGRADED' ? 'secondary' : 'destructive'}>
                      {serverInfo.health.status}
                    </Badge>
                  </div>
                </div>
              </div>
            </>
          )}
        </CardContent>
      </Card>

      {/* Tools Tab */}
      <TabsContent value="tools" className="mt-6">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Code className="h-5 w-5" />
              Tools ({tools.length})
            </CardTitle>
          </CardHeader>
          <CardContent>
            {toolsLoading ? <div className="text-center py-8 text-muted-foreground">Loading tools...</div> : tools.length === 0 ? (
              <div className="text-center py-8 text-muted-foreground">No tools discovered</div>
            ) : (
              <DataTable
                columns={toolColumns}
                rows={tools}
                keyOf={(r) => r.id}
                loading={toolsLoading}
              />
            )}
          </CardContent>
        </Card>
      </TabsContent>

      {/* Resources Tab */}
      <TabsContent value="resources" className="mt-6">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Database className="h-5 w-5" />
              Resources ({resources.length})
            </CardTitle>
          </CardHeader>
          <CardContent>
            {resourcesLoading ? <div className="text-center py-8 text-muted-foreground">Loading resources...</div> : resources.length === 0 ? (
              <div className="text-center py-8 text-muted-foreground">No resources available</div>
            ) : (
              <DataTable
                columns={resourceColumns}
                rows={resources}
                keyOf={(r) => r.id}
                loading={resourcesLoading}
              />
            )}
          </CardContent>
        </Card>
      </TabsContent>

      {/* Prompts Tab */}
      <TabsContent value="prompts" className="mt-6">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <FileText className="h-5 w-5" />
              Prompts ({prompts.length})
            </CardTitle>
          </CardHeader>
          <CardContent>
            {promptsLoading ? <div className="text-center py-8 text-muted-foreground">Loading prompts...</div> : prompts.length === 0 ? (
              <div className="text-center py-8 text-muted-foreground">No prompts available</div>
            ) : (
              <DataTable
                columns={promptColumns}
                rows={prompts}
                keyOf={(r) => r.id}
                loading={promptsLoading}
              />
            )}
          </CardContent>
        </Card>
      </TabsContent>
    </div>
  );

  return (
    <Protected>
      <Layout>
        <div className="oa-page">
          <PageHeader
            title={serverInfo.display_name || serverInfo.name}
            description={serverInfo.description}
            breadcrumbs={[
              { label: 'Home', href: '/' },
              { label: 'MCP Servers', href: '/mcp' },
              { label: serverInfo.name }
            ]}
          />

          <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full">
            <TabsList className="grid w-full grid-cols-4">
              <TabsTrigger value="overview">Overview</TabsTrigger>
              <TabsTrigger value="tools">Tools ({tools.length})</TabsTrigger>
              <TabsTrigger value="resources">Resources ({resources.length})</TabsTrigger>
              <TabsTrigger value="prompts">Prompts ({prompts.length})</TabsTrigger>
            </TabsList>

            {overviewContent}
          </Tabs>
        </div>
      </Layout>
    </Protected>
  );
}

const trustColors: Record<string, string> = {
  CORE: 'bg-purple-100 text-purple-700',
  VERIFIED: 'bg-blue-100 text-blue-700',
  ORGANIZATION: 'bg-green-100 text-green-700',
  COMMUNITY: 'bg-yellow-100 text-yellow-700',
  UNTRUSTED: 'bg-red-100 text-red-700',
};

const toolColumns: Column<ToolRow>[] = [
  {
    key: 'name',
    header: 'Name',
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
    key: 'risk_level',
    header: 'Risk',
    render: (r) => {
      const colors: Record<string, string> = {
        LOW: 'bg-green-100 text-green-700',
        MEDIUM: 'bg-yellow-100 text-yellow-700',
        HIGH: 'bg-orange-100 text-orange-700',
        CRITICAL: 'bg-red-100 text-red-700',
      };
      return (
        <Badge className={colors[r.risk_level] || 'bg-gray-100 text-gray-700'}>
          {r.risk_level}
        </Badge>
      );
    },
  },
  {
    key: 'capabilities',
    header: 'Capabilities',
    render: (r) => (
      <div className="flex flex-wrap gap-1">
        {r.capabilities.map(c => (
          <Badge key={c} variant="secondary" className="text-xs">{c}</Badge>
        ))}
      </div>
    ),
  },
  {
    key: 'status',
    header: 'Status',
    render: (r) => <StatusBadge status={r.status === 'ACTIVE' ? 'active' : 'inactive'} />,
  },
];

const resourceColumns: Column<ResourceRow>[] = [
  {
    key: 'name',
    header: 'Name',
    accessor: (r) => r.name,
    render: (r) => (
      <div>
        <span className="font-medium">{r.name}</span>
        <p className="text-xs text-muted-foreground truncate max-w-[300px]">{r.uri}</p>
      </div>
    ),
  },
  {
    key: 'mime_type',
    header: 'MIME Type',
    render: (r) => r.mime_type ? <Badge variant="secondary" className="text-xs">{r.mime_type}</Badge> : <span className="text-muted-foreground">—</span>,
  },
  {
    key: 'status',
    header: 'Status',
    render: (r) => <StatusBadge status={r.status === 'ACTIVE' ? 'active' : 'inactive'} />,
  },
];

const promptColumns: Column<PromptRow>[] = [
  {
    key: 'name',
    header: 'Name',
    accessor: (r) => r.name,
    render: (r) => (
      <div>
        <span className="font-medium">{r.name}</span>
        {r.title && <p className="text-sm text-muted-foreground">{r.title}</p>}
      </div>
    ),
  },
  {
    key: 'description',
    header: 'Description',
    render: (r) => <span className="text-muted-foreground text-sm">{r.description || '—'}</span>,
  },
  {
    key: 'status',
    header: 'Status',
    render: (r) => <StatusBadge status={r.status === 'ACTIVE' ? 'active' : 'inactive'} />,
  },
];