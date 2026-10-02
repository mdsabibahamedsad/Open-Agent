'use client';

import * as React from 'react';
import { Layout } from '@/components/layout';
import { Protected } from '@/components/protected';
import { PageHeader } from '@/components/ui/page';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Label } from '@/components/ui/label';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Separator } from '@/components/ui/separator';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { useRouter } from 'next/navigation';
import { useOrgScopedMutation } from '@/lib/queries';
import { api } from '@/lib/api';
import { ChevronLeft, ChevronRight, CheckCircle2, AlertCircle, Info, Shield, Server, Link2, Terminal, Globe, Lock, AlertCircle as AlertCircleIcon, CheckCircle2 as CheckCircle2Icon } from 'lucide-react';

interface InstallFormData {
  step: number;
  name: string;
  display_name: string;
  description: string;
  transport: 'streamable_http' | 'sse' | 'stdio';
  endpoint?: string;
  command?: string;
  args: string[];
  env: Record<string, string>;
  working_directory?: string;
  credential_id?: string;
  trust_level: 'CORE' | 'VERIFIED' | 'ORGANIZATION' | 'COMMUNITY' | 'UNTRUSTED';
  scope: 'ORGANIZATION' | 'TEAM' | 'USER';
  configuration?: Record<string, unknown>;
}

const STEPS = [
  { id: 1, title: 'Server Info', description: 'Basic server identification' },
  { id: 2, title: 'Transport', description: 'Connection method and endpoint' },
  { id: 3, title: 'Security', description: 'Trust level, credentials, and scope' },
  { id: 4, title: 'Review', description: 'Review and install' },
];

const TRANSPORT_OPTIONS = [
  { value: 'streamable_http', label: 'Streamable HTTP', icon: Globe, description: 'Modern HTTP transport with streaming support' },
  { value: 'sse', label: 'Server-Sent Events (SSE)', icon: Link2, description: 'Traditional SSE-based connection' },
  { value: 'stdio', label: 'STDIO (Local Process)', icon: Terminal, description: 'Local subprocess communication' },
] as const;

const TRUST_LEVELS = [
  { value: 'CORE', label: 'Core', description: 'Built-in, fully vetted servers', color: 'bg-purple-100 text-purple-700' },
  { value: 'VERIFIED', label: 'Verified', description: 'Officially verified third-party servers', color: 'bg-blue-100 text-blue-700' },
  { value: 'ORGANIZATION', label: 'Organization', description: 'Trusted within your organization', color: 'bg-green-100 text-green-700' },
  { value: 'COMMUNITY', label: 'Community', description: 'Community-contributed servers', color: 'bg-yellow-100 text-yellow-700' },
  { value: 'UNTRUSTED', label: 'Untrusted', description: 'No trust verification - use with caution', color: 'bg-red-100 text-red-700' },
] as const;

const SCOPE_OPTIONS = [
  { value: 'ORGANIZATION', label: 'Organization', description: 'Available to all members of the organization' },
  { value: 'TEAM', label: 'Team', description: 'Restricted to specific teams' },
  { value: 'USER', label: 'Personal', description: 'Only available to you' },
] as const;

export default function MCPInstallPage() {
  const router = useRouter();
  const [step, setStep] = React.useState(1);
  const [formData, setFormData] = React.useState<InstallFormData>({
    step: 1,
    name: '',
    display_name: '',
    description: '',
    transport: 'streamable_http',
    args: [],
    env: {},
    trust_level: 'COMMUNITY',
    scope: 'ORGANIZATION',
  });
  const [errors, setErrors] = React.useState<Record<string, string>>({});
  const [isSubmitting, setIsSubmitting] = React.useState(false);
  const [testResult, setTestResult] = React.useState<{ success: boolean; message: string } | null>(null);

  const { mutate: installServer, isPending: isInstalling } = useOrgScopedMutation(
    (data) => api.post('/mcp/servers/install', data),
    {
      onSuccess: () => {
        router.push('/mcp');
      },
      onError: (error: Error) => {
        setErrors({ submit: error.message });
      },
    }
  );

  const { mutate: testConnection, isPending: isTesting } = useOrgScopedMutation(
    (data) => api.post('/mcp/servers/test-connection', data),
    {
      onSuccess: (result: any) => {
        setTestResult({ success: result.success, message: result.success ? 'Connection successful!' : result.error || 'Connection failed' });
      },
      onError: (error: Error) => {
        setTestResult({ success: false, message: error.message });
      },
    }
  );

  const handleChange = (field: keyof InstallFormData, value: any) => {
    setFormData(prev => ({ ...prev, [field]: value }));
    if (errors[field]) {
      setErrors(prev => { const n = { ...prev }; delete n[field]; return n; });
    }
  };

  const validateStep = (currentStep: number): boolean => {
    const newErrors: Record<string, string> = {};

    if (currentStep >= 1) {
      if (!formData.name.trim()) newErrors.name = 'Server name is required';
      if (formData.name.length > 100) newErrors.name = 'Name must be 100 characters or less';
    }

    if (currentStep >= 2) {
      if (formData.transport === 'streamable_http' || formData.transport === 'sse') {
        if (!formData.endpoint?.trim()) newErrors.endpoint = 'Endpoint URL is required';
        else {
          try { new URL(formData.endpoint); } catch { newErrors.endpoint = 'Invalid URL format'; }
        }
      } else if (formData.transport === 'stdio') {
        if (!formData.command?.trim()) newErrors.command = 'Command is required for STDIO transport';
      }
    }

    if (currentStep >= 3) {
      if (!formData.trust_level) newErrors.trust_level = 'Trust level is required';
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleNext = () => {
    if (validateStep(step) && step < STEPS.length) {
      setStep(step + 1);
    }
  };

  const handleBack = () => {
    if (step > 1) setStep(step - 1);
  };

  const handleSubmit = () => {
    if (validateStep(STEPS.length)) {
      setIsSubmitting(true);
      installServer(formData);
    }
  };

  const handleTestConnection = () => {
    if (validateStep(2)) {
      setTestResult(null);
      testConnection({
        transport: formData.transport,
        endpoint: formData.endpoint,
        command: formData.command,
        args: formData.args,
        env: formData.env,
        credential_id: formData.credential_id,
        trust_level: formData.trust_level,
        scope: formData.scope,
        configuration: formData.configuration,
      });
    }
  };

  const currentStepInfo = STEPS[step - 1];

  return (
    <Protected>
      <Layout>
        <div className="oa-page max-w-3xl">
          <PageHeader
            title="Install MCP Server"
            description="Add a new Model Context Protocol server to connect external tools, resources, and prompts."
            breadcrumbs={[{ label: 'Home', href: '/' }, { label: 'MCP Servers', href: '/mcp' }, { label: 'Install' }]}
          />

          {/* Progress Indicator */}
          <div className="mb-8">
            <div className="flex items-center justify-between">
              {STEPS.map((s, i) => (
                <React.Fragment key={s.id}>
                  <div className="flex flex-col items-center">
                    <div className={`flex h-10 w-10 items-center justify-center rounded-full text-sm font-medium transition-colors ${
                      i + 1 < step ? 'bg-green-500 text-white' :
                      i + 1 === step ? 'bg-primary text-primary-foreground' :
                      'bg-muted text-muted-foreground'
                    }`}>
                      {i + 1 < step ? <CheckCircle2Icon className="h-5 w-5" /> : s.id}
                    </div>
                    <span className={`mt-2 text-xs font-medium text-center ${i + 1 === step ? 'text-primary' : 'text-muted-foreground'}`}>
                      {s.title}
                    </span>
                  </div>
                  {i < STEPS.length - 1 && (
                    <div className={`flex-1 h-1 mx-2 ${i + 1 < step ? 'bg-green-500' : 'bg-muted'}`} />
                  )}
                </React.Fragment>
              ))}
            </div>
          </div>

          {/* Step Content */}
          <Card className="mb-6">
            <CardHeader>
              <CardTitle>{currentStepInfo.title}</CardTitle>
              <CardDescription>{currentStepInfo.description}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              {step === 1 && (
                <div className="space-y-4">
                  <div>
                    <Label htmlFor="name">Server Name *</Label>
                    <Input
                      id="name"
                      value={formData.name}
                      onChange={(e) => handleChange('name', e.target.value)}
                      placeholder="github-mcp"
                      error={errors.name}
                    />
                    <p className="text-sm text-muted-foreground">Unique identifier (lowercase, hyphens only)</p>
                  </div>
                  <div>
                    <Label htmlFor="display_name">Display Name</Label>
                    <Input
                      id="display_name"
                      value={formData.display_name}
                      onChange={(e) => handleChange('display_name', e.target.value)}
                      placeholder="GitHub MCP"
                    />
                    <p className="text-sm text-muted-foreground">Human-readable name (optional)</p>
                  </div>
                  <div>
                    <Label htmlFor="description">Description</Label>
                    <textarea
                      id="description"
                      value={formData.description}
                      onChange={(e) => handleChange('description', e.target.value)}
                      placeholder="Connect to GitHub APIs for repository management"
                      className="w-full min-h-[80px] p-3 border rounded-md bg-background text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
                      rows={3}
                    />
                  </div>
                </div>
              )}

              {step === 2 && (
                <div className="space-y-6">
                  <div>
                    <Label>Transport Protocol</Label>
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mt-2">
                      {TRANSPORT_OPTIONS.map(({ value, label, icon: Icon, description }) => (
                        <button
                          key={value}
                          type="button"
                          onClick={() => handleChange('transport', value as any)}
                          className={`relative p-4 border-2 rounded-lg text-left transition-all ${
                            formData.transport === value
                              ? 'border-primary bg-primary/5'
                              : 'border-border hover:border-primary/50'
                          }`}
                        >
                          <div className="flex items-center gap-3">
                            <Icon className="h-6 w-6 text-primary" />
                            <div>
                              <div className="font-medium">{label}</div>
                              <div className="text-sm text-muted-foreground">{description}</div>
                            </div>
                          </div>
                          {formData.transport === value && (
                            <div className="absolute -top-2 -right-2 h-5 w-5 bg-primary text-primary-foreground rounded-full flex items-center justify-center text-xs">
                              <CheckCircle2Icon className="h-4 w-4" />
                            </div>
                          )}
                        </button>
                      ))}
                    </div>
                  </div>

                  {formData.transport === 'streamable_http' || formData.transport === 'sse' ? (
                    <div className="space-y-4">
                      <div>
                        <Label htmlFor="endpoint">Endpoint URL *</Label>
                        <Input
                          id="endpoint"
                          value={formData.endpoint || ''}
                          onChange={(e) => handleChange('endpoint', e.target.value)}
                          placeholder="https://api.example.com/mcp"
                          error={errors.endpoint}
                        />
                      </div>
                      <div>
                        <Label htmlFor="credential_id">Credential (Optional)</Label>
                        <Select value={formData.credential_id || ''} onValueChange={(v) => handleChange('credential_id', v || undefined)}>
                          <SelectTrigger>
                            <SelectValue placeholder="Select credential" />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="">None</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                    </div>
                  ) : (
                    <div className="space-y-4">
                      <div>
                        <Label htmlFor="command">Command *</Label>
                        <Input
                          id="command"
                          value={formData.command || ''}
                          onChange={(e) => handleChange('command', e.target.value)}
                          placeholder="npx @modelcontextprotocol/server-github"
                          error={errors.command}
                        />
                      </div>
                      <div>
                        <Label htmlFor="args">Arguments (one per line)</Label>
                        <textarea
                          id="args"
                          value={formData.args.join('\n')}
                          onChange={(e) => handleChange('args', e.target.value.split('\n').filter(a => a.trim()))}
                          placeholder="--token\nenv.GITHUB_TOKEN"
                          className="w-full min-h-[80px] p-3 border rounded-md bg-background text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring font-mono text-sm"
                          rows={3}
                        />
                        <p className="text-sm text-muted-foreground">Each line becomes a separate argument</p>
                      </div>
                      <div>
                        <Label htmlFor="working_directory">Working Directory (Optional)</Label>
                        <Input
                          id="working_directory"
                          value={formData.working_directory || ''}
                          onChange={(e) => handleChange('working_directory', e.target.value)}
                          placeholder="/path/to/working/dir"
                        />
                      </div>
                      <div>
                        <Label htmlFor="env">Environment Variables (JSON)</Label>
                        <textarea
                          id="env"
                          value={JSON.stringify(formData.env, null, 2)}
                          onChange={(e) => {
                            try { handleChange('env', JSON.parse(e.target.value)); }
                            catch { handleChange('env', {}); }
                          }}
                          placeholder='{"GITHUB_TOKEN": "secret_ref"}'
                          className="w-full min-h-[80px] p-3 border rounded-md bg-background text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring font-mono text-sm"
                          rows={4}
                        />
                        <p className="text-sm text-muted-foreground">Reference credentials using secret_ref syntax</p>
                      </div>
                    </div>
                  )}

                  {testResult && (
                    <Alert variant={testResult.success ? 'default' : 'destructive'} className="mt-4">
                      <CheckCircle2 className="h-4 w-4" />
                      <AlertDescription>{testResult.message}</AlertDescription>
                    </Alert>
                  )}

                  <div className="flex gap-2 pt-4">
                    <Button variant="outline" onClick={handleTestConnection} disabled={isTesting}>
                      <Link2 className="h-4 w-4 mr-2" />
                      {isTesting ? 'Testing...' : 'Test Connection'}
                    </Button>
                  </div>
                </div>
              )}

              {step === 3 && (
                <div className="space-y-6">
                  <div>
                    <Label>Trust Level *</Label>
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3 mt-2">
                      {TRUST_LEVELS.map(({ value, label, description, color }) => (
                        <button
                          key={value}
                          type="button"
                          onClick={() => handleChange('trust_level', value as any)}
                          className={`p-4 border-2 rounded-lg text-left transition-all ${
                            formData.trust_level === value
                              ? `border-primary bg-primary/5 ${color.replace('100', '50').replace('700', '600')}`
                              : 'border-border hover:border-primary/50'
                          }`}
                        >
                          <div className="flex items-center gap-2 mb-1">
                            <span className={`inline-flex px-2 py-0.5 text-xs font-medium rounded-full ${color}`}>
                              {label}
                            </span>
                          </div>
                          <p className="text-sm text-muted-foreground">{description}</p>
                        </button>
                      ))}
                    </div>
                  </div>

                  <div>
                    <Label>Organization Scope</Label>
                    <Select value={formData.scope} onValueChange={(v) => handleChange('scope', v as any)}>
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {SCOPE_OPTIONS.map(({ value, label, description }) => (
                          <SelectItem key={value} value={value}>
                            <div>
                              <div className="font-medium">{label}</div>
                              <div className="text-sm text-muted-foreground">{description}</div>
                            </div>
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>

                  <Alert>
                    <Shield className="h-4 w-4" />
                    <AlertDescription>
                      <strong>Security Notice:</strong> MCP servers can execute arbitrary code and access external systems.
                      Only install servers from trusted sources. Review the server's capabilities and permissions before activating.
                    </AlertDescription>
                  </Alert>
                </div>
              )}

              {step === 4 && (
                <div className="space-y-6">
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <Card>
                      <CardHeader className="pb-2">
                        <CardTitle className="flex items-center gap-2">
                          <Info className="h-5 w-5" />
                          Server Info
                        </CardTitle>
                      </CardHeader>
                      <CardContent className="space-y-2">
                        <div className="flex justify-between"><span className="text-muted-foreground">Name</span><span className="font-medium">{formData.name}</span></div>
                        <div className="flex justify-between"><span className="text-muted-foreground">Display Name</span><span>{formData.display_name || '—'}</span></div>
                        <div className="flex justify-between"><span className="text-muted-foreground">Transport</span><span className="font-medium capitalize">{formData.transport.replace('_', ' ')}</span></div>
                        {formData.endpoint && <div className="flex justify-between"><span className="text-muted-foreground">Endpoint</span><span className="font-medium text-sm truncate max-w-[200px]">{formData.endpoint}</span></div>}
                        {formData.command && <div className="flex justify-between"><span className="text-muted-foreground">Command</span><span className="font-medium text-sm truncate max-w-[200px] font-mono">{formData.command}</span></div>}
                        <div className="flex justify-between"><span className="text-muted-foreground">Trust Level</span><span className="font-medium">{formData.trust_level}</span></div>
                        <div className="flex justify-between"><span className="text-muted-foreground">Scope</span><span className="font-medium">{formData.scope}</span></div>
                      </CardContent>
                    </Card>

                    <Card>
                      <CardHeader className="pb-2">
                        <CardTitle className="flex items-center gap-2">
                          <Shield className="h-5 w-5" />
                          Security & Scope
                        </CardTitle>
                      </CardHeader>
                      <CardContent className="space-y-2">
                        <div className="flex justify-between"><span className="text-muted-foreground">Trust Level</span><span className="font-medium">{formData.trust_level}</span></div>
                        <div className="flex justify-between"><span className="text-muted-foreground">Scope</span><span className="font-medium">{formData.scope}</span></div>
                        <div className="flex justify-between"><span className="text-muted-foreground">Credential</span><span>{formData.credential_id ? 'Configured' : 'None'}</span></div>
                        <div className="flex justify-between"><span className="text-muted-foreground">Arguments</span><span>{formData.args.length} args</span></div>
                        <div className="flex justify-between"><span className="text-muted-foreground">Env Vars</span><span>{Object.keys(formData.env).length} configured</span></div>
                      </CardContent>
                    </Card>
                  </div>

                  <Alert variant="destructive">
                    <AlertCircleIcon className="h-4 w-4" />
                    <AlertDescription>
                      <strong>Final Security Review:</strong> By installing this server, you are granting it access to execute tools and potentially access external systems.
                      Ensure you trust the server source and understand its capabilities before proceeding.
                    </AlertDescription>
                  </Alert>
                </div>
              )}
            </CardContent>
          </Card>

          {/* Navigation */}
          <div className="flex justify-between">
            <Button variant="outline" onClick={handleBack} disabled={step === 1}>
              <ChevronLeft className="h-4 w-4 mr-2" />
              Back
            </Button>
            <div className="flex gap-2">
              {step < STEPS.length ? (
                <Button onClick={handleNext} disabled={isSubmitting || isTesting}>
                  Next
                  <ChevronRight className="h-4 w-4 ml-2" />
                </Button>
              ) : (
                <Button onClick={handleSubmit} disabled={isSubmitting || isInstalling}>
                  {isInstalling ? 'Installing...' : 'Install Server'}
                </Button>
              )}
            </div>
          </div>

          {errors.submit && (
            <Alert variant="destructive" className="mt-4">
              <AlertCircleIcon className="h-4 w-4" />
              <AlertDescription>{errors.submit}</AlertDescription>
            </Alert>
          )}
        </div>
      </Layout>
    </Protected>
  );
}