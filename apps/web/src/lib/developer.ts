// Typed client for the org-scoped developer + extension API (MP28).
// All org-scoped calls take orgId explicitly and map ApiError through.

import { api, ApiError } from '@/lib/api';

export { ApiError };

function org(base: string, orgId: string): string {
  return base.replace('{orgId}', orgId);
}

const P = {
  projects: '/organizations/{orgId}/developer/projects',
  project: (id: string) => `/organizations/{orgId}/developer/projects/${id}`,
  env: (pid: string, env: string) =>
    `/organizations/{orgId}/developer/projects/${pid}/environments/${env}`,
  extensions: '/organizations/{orgId}/extensions',
  extension: (id: string) => `/organizations/{orgId}/extensions/${id}`,
  extAction: (id: string, action: string) => `/organizations/{orgId}/extensions/${id}/${action}`,
  webhooks: '/organizations/{orgId}/developer/webhooks',
  devEvents: '/organizations/{orgId}/developer/events',
  usage: '/organizations/{orgId}/developer/usage',
  deployments: '/organizations/{orgId}/developer/deployments',
};

function pickArray<T>(data: unknown, keys: string[]): T[] {
  if (Array.isArray(data)) return data as T[];
  if (data && typeof data === 'object') {
    const obj = data as Record<string, unknown>;
    for (const k of keys) {
      if (Array.isArray(obj[k])) return obj[k] as T[];
    }
    if (Array.isArray(obj.data)) return obj.data as T[];
    if (Array.isArray(obj.items)) return obj.items as T[];
  }
  return [];
}

function pickOne<T>(data: unknown, keys: string[], fallback: T): T {
  if (data && typeof data === 'object') {
    const obj = data as Record<string, unknown>;
    for (const k of keys) {
      if (obj[k] !== undefined) return obj[k] as T;
    }
  }
  return fallback;
}

// ---------------------------------------------------------------- types

export interface DevProject {
  id: string;
  slug: string;
  name: string;
  status?: string;
  description?: string;
}

export interface ProjectDetail extends DevProject {
  environments: { name: string; endpoint?: string }[];
  extensions: string[];
}

export interface DevExtension {
  id: string;
  slug: string;
  type: string;
  lifecycle: string;
  trust?: string;
}

export interface ExtVersion {
  id: string;
  version: string;
  digest?: string;
}

export interface ExtensionDetail {
  id: string;
  slug: string;
  type: string;
  lifecycle: string;
  trust?: string;
  quarantine: { at: string | null; reason?: string | null };
  versions: ExtVersion[];
}

export interface DevWebhook {
  id: string;
  url: string;
  events: string[];
  enabled?: boolean;
}

export interface DevEventSchema {
  name: string;
  version: string;
  schema?: unknown;
}

export interface UsageRow {
  extension: string;
  day: string;
  installs: number;
  invocations: number;
  errors: number;
  avg_latency_ms?: number | null;
}

export interface DeploymentRow {
  id: string;
  extension: string;
  environment: string;
  status: string;
  stages?: string[];
}

export interface PermissionEntry {
  description: string;
  risk: 'low' | 'medium' | 'high' | 'critical';
  requires_approval: boolean;
}

export interface SdkMeta {
  sdk: { typescript: string; python: string };
  api_version: string;
  extension_api: string;
  manifest_version: string;
  extension_types: string[];
  permissions: Record<string, PermissionEntry>;
  deprecations: { name?: string; message?: string; [k: string]: unknown }[];
  install: { typescript: string; python: string; cli: string };
}

export interface LocalRegistry {
  packages: { artifact: string }[];
  registry: string;
}

export interface ValidationReport {
  ok: boolean;
  manifest?: unknown;
  errors?: unknown[];
  warnings?: unknown[];
  [k: string]: unknown;
}

export interface TestReport {
  passed: boolean;
  checks: { name: string; passed: boolean; detail?: string }[];
}

export interface PackageResult {
  filename: string;
  digest: string;
  size_bytes: number;
  checksums?: Record<string, string>;
  provenance?: unknown;
  sbom?: unknown;
}

// ------------------------------------------------------- projects

export async function listProjects(orgId: string): Promise<DevProject[]> {
  const data = await api.get<unknown>(org(P.projects, orgId));
  return pickArray<DevProject>(data, ['projects']);
}

export async function createProject(
  orgId: string,
  body: { slug: string; name: string; description?: string },
): Promise<{ id: string; slug: string; name: string }> {
  return api.post(org(P.projects, orgId), body);
}

export async function getProject(orgId: string, projectId: string): Promise<ProjectDetail> {
  const data = await api.get<Record<string, unknown>>(org(P.project(projectId), orgId));
  return {
    id: String(data.id ?? projectId),
    slug: String(data.slug ?? ''),
    name: String(data.name ?? ''),
    status: data.status ? String(data.status) : undefined,
    description: data.description ? String(data.description) : undefined,
    environments: pickArray<{ name: string; endpoint?: string }>(data, ['environments']),
    extensions: pickArray<string>(data, ['extensions']),
  };
}

export async function updateEnvironment(
  orgId: string,
  projectId: string,
  env: string,
  body: { api_endpoint?: string; config?: Record<string, unknown> },
): Promise<unknown> {
  return api.put(org(P.env(projectId, env), orgId), body);
}

// ------------------------------------------------------- extensions

export async function listExtensions(
  orgId: string,
  filters?: { extension_type?: string; lifecycle?: string },
): Promise<DevExtension[]> {
  const data = await api.get<unknown>(org(P.extensions, orgId), {
    extension_type: filters?.extension_type || undefined,
    lifecycle: filters?.lifecycle || undefined,
  });
  return pickArray<DevExtension>(data, ['extensions']);
}

export async function createExtension(
  orgId: string,
  body: {
    slug: string;
    extension_type: string;
    display_name?: string;
    description?: string;
    project_id?: string;
    license?: string;
    repository?: string;
  },
): Promise<{ id: string; slug: string; lifecycle: string }> {
  return api.post(org(P.extensions, orgId), body);
}

export async function getExtension(orgId: string, id: string): Promise<ExtensionDetail> {
  const data = await api.get<Record<string, unknown>>(org(P.extension(id), orgId));
  const q = (data.quarantine as { at?: string | null; reason?: string | null }) ?? { at: null };
  return {
    id: String(data.id ?? id),
    slug: String(data.slug ?? ''),
    type: String((data.type as string) ?? (data.extension_type as string) ?? ''),
    lifecycle: String(data.lifecycle ?? 'DRAFT'),
    trust: data.trust ? String(data.trust) : undefined,
    quarantine: { at: q.at ?? null, reason: q.reason ?? null },
    versions: pickArray<ExtVersion>(data, ['versions']),
  };
}

export async function createVersion(
  orgId: string,
  extId: string,
  body: { version: string; manifest: Record<string, unknown>; changelog?: string },
): Promise<{ id: string; version: string }> {
  return api.post(org(P.extAction(extId, 'versions'), orgId), body);
}

export async function validateExtension(
  orgId: string,
  extId: string,
  body: { files?: Record<string, string>; openagent_version?: string },
): Promise<ValidationReport> {
  return api.post(org(P.extAction(extId, 'validate'), orgId), body);
}

export async function testExtension(
  orgId: string,
  extId: string,
  body: { files?: Record<string, string>; suite?: string },
): Promise<TestReport> {
  return api.post(org(P.extAction(extId, 'test'), orgId), body);
}

export async function packageExtension(
  orgId: string,
  extId: string,
  body: { files?: Record<string, string>; openagent_version?: string },
): Promise<PackageResult> {
  return api.post(org(P.extAction(extId, 'package'), orgId), body);
}

export async function publishExtension(
  orgId: string,
  extId: string,
  body: { files?: Record<string, string>; allow_secret_override?: boolean; override_reason?: string },
): Promise<unknown> {
  return api.post(org(P.extAction(extId, 'publish'), orgId), body);
}

export async function signExtension(
  orgId: string,
  extId: string,
  body: { key_id?: string; public_key: string },
): Promise<{ digest_sha256: string; key_id: string; algorithm: string; note?: string }> {
  return api.post(org(P.extAction(extId, 'sign'), orgId), body);
}

export async function signComplete(
  orgId: string,
  extId: string,
  body: { key_id: string; signature_b64: string },
): Promise<unknown> {
  return api.post(org(P.extAction(extId, 'sign/complete'), orgId), body);
}

export async function installExtension(
  orgId: string,
  extId: string,
  body: { version: string; environment?: string; granted_permissions?: string[]; config_values?: Record<string, unknown> },
): Promise<unknown> {
  return api.post(org(P.extAction(extId, 'install'), orgId), body);
}

export async function disableExtension(orgId: string, extId: string): Promise<unknown> {
  return api.post(org(P.extAction(extId, 'disable'), orgId), {});
}

export async function quarantineExtension(
  orgId: string,
  extId: string,
  reason: string,
): Promise<unknown> {
  return api.post(org(P.extAction(extId, 'quarantine'), orgId), { reason });
}

export async function rollbackExtension(
  orgId: string,
  extId: string,
  installationId: string,
): Promise<unknown> {
  const base = org(P.extAction(extId, 'rollback'), orgId);
  return api.post<unknown>(`${base}?installation_id=${encodeURIComponent(installationId)}`, {});
}

export async function deployExtension(
  orgId: string,
  extId: string,
  body: { version: string; environment?: string },
): Promise<{ id: string; status: string; stages?: string[] }> {
  return api.post(org(P.extAction(extId, 'deploy'), orgId), body);
}

export async function artifactMeta(
  orgId: string,
  extId: string,
): Promise<{ digest: string; size_bytes: number; version: string }> {
  return api.get(org(P.extAction(extId, 'artifact'), orgId));
}

// ------------------------------------------------------- webhooks/events/usage/deployments

export async function listWebhooks(orgId: string): Promise<DevWebhook[]> {
  const data = await api.get<unknown>(org(P.webhooks, orgId));
  return pickArray<DevWebhook>(data, ['webhooks']);
}

export async function createWebhook(
  orgId: string,
  body: { url: string; events: string[]; project_id?: string },
): Promise<{ id: string; url: string; events: string[]; signing_secret_once: string }> {
  return api.post(org(P.webhooks, orgId), body);
}

export async function listDevEvents(orgId: string): Promise<DevEventSchema[]> {
  const data = await api.get<unknown>(org(P.devEvents, orgId));
  return pickArray<DevEventSchema>(data, ['events']);
}

export async function listUsage(orgId: string, days = 30): Promise<UsageRow[]> {
  const data = await api.get<unknown>(org(P.usage, orgId), { days });
  return pickArray<UsageRow>(data, ['usage']);
}

export async function listDeployments(orgId: string): Promise<DeploymentRow[]> {
  const data = await api.get<unknown>(org(P.deployments, orgId));
  return pickArray<DeploymentRow>(data, ['deployments']);
}

// ------------------------------------------------------- public + registry

export async function getSdkMeta(): Promise<SdkMeta> {
  return api.get<SdkMeta>('/developer/sdk');
}

export async function getPublicEvents(): Promise<string[]> {
  const data = await api.get<{ events?: string[] } | string[]>('/developer/events');
  if (Array.isArray(data)) return data;
  return data.events ?? [];
}

export async function listLocalPackages(): Promise<LocalRegistry> {
  const data = await api.get<LocalRegistry>('/registry/local/packages');
  return { packages: data.packages ?? [], registry: data.registry ?? '' };
}

// ------------------------------------------------------- permission metadata

export interface PermissionHint {
  implication: string;
  review: string;
  sandbox: string;
}

export const PERMISSION_HINTS: Record<string, PermissionHint> = {
  'network:outbound': {
    implication: 'Can call declared HTTPS hosts only. Declare an allowlist; no raw sockets.',
    review: 'Review host allowlist for exfiltration risk.',
    sandbox: 'Egress is proxied and logged.',
  },
  'network:restricted': {
    implication: 'Can reach private/internal networks. High SSRF risk — metadata endpoints blocked by policy.',
    review: 'Requires human approval. Never grant to COMMUNITY/UNTRUSTED without review.',
    sandbox: 'Confined egress + mandatory audit trail.',
  },
  'filesystem:workspace': {
    implication: 'Read/write inside its own workspace directory only.',
    review: 'No review needed; safest storage scope.',
    sandbox: 'Path-sandboxed to workspace.',
  },
  'filesystem:artifact': {
    implication: 'Read/write declared artifacts only.',
    review: 'Check artifact paths for overlap with other extensions.',
    sandbox: 'Artifact-scoped mounts.',
  },
  'tool:execute': {
    implication: 'Can invoke other tools through the Tool Runtime (policy-checked).',
    review: 'Check for privilege-escalation chains (tool calling privileged tools).',
    sandbox: 'All invocations logged with caller identity.',
  },
  'connector:use': {
    implication: 'Can use declared connector connections with stored credentials.',
    review: 'Verify connection scopes are least-privilege.',
    sandbox: 'Credential values never exposed; references only.',
  },
  'memory:read': {
    implication: 'Can read scoped memory partitions.',
    review: 'Check scope does not cross tenant/owner boundary.',
    sandbox: 'Scope-enforced reads.',
  },
  'memory:write': {
    implication: 'Can write scoped memory partitions.',
    review: 'Check for prompt-injection persistence risk.',
    sandbox: 'Scope-enforced writes, versioned.',
  },
  'browser:use': {
    implication: 'Can drive browser sessions; can see page content including PII.',
    review: 'Requires human approval. Define URL allowlist.',
    sandbox: 'Runs under browser policy with session recording.',
  },
  'sandbox:execute': {
    implication: 'Can run code inside the Sandbox boundary (no host access).',
    review: 'Check resource limits (CPU/mem/timeout).',
    sandbox: 'gVisor/Firecracker-isolated execution.',
  },
  'mcp:connect': {
    implication: 'Can connect to declared MCP servers.',
    review: 'Verify server URLs are allowlisted.',
    sandbox: 'Connection proxied and schema-validated.',
  },
  'secret:access': {
    implication: 'Can reference declared secrets. Values are injected at runtime, never stored in code.',
    review: 'Requires human approval. Never log or echo secret values.',
    sandbox: 'Secret references only; values redacted in logs.',
  },
  'workflow:execute': {
    implication: 'Can start workflow executions (cost + side effects).',
    review: 'Check for runaway-loop guards.',
    sandbox: 'Quota-enforced execution.',
  },
  'agent:invoke': {
    implication: 'Can invoke sub-agents under policy.',
    review: 'Check delegation depth limits.',
    sandbox: 'Policy-checked invocation.',
  },
  'model:invoke': {
    implication: 'Can call models via the Model Router (billed).',
    review: 'Check model allowlist and budget.',
    sandbox: 'Routed + metered.',
  },
  'evaluation:run': {
    implication: 'Can run evaluators on observable outputs only.',
    review: 'No production data access implied.',
    sandbox: 'Read-only evaluation context.',
  },
  'webhook:receive': {
    implication: 'Receives inbound webhooks; must verify signatures.',
    review: 'Verify HMAC signature handling.',
    sandbox: 'Signature-verified delivery.',
  },
  'storage:use': {
    implication: 'Object storage within quota.',
    review: 'Check quota and retention.',
    sandbox: 'Quota-enforced buckets.',
  },
  'billing:read': {
    implication: 'Read-only view of own usage/entitlements.',
    review: 'No risk; read-only.',
    sandbox: 'No sandbox impact.',
  },
};

export function permissionHint(name: string, entry?: PermissionEntry): PermissionHint & { risk: string; requiresApproval: boolean } {
  const hint = PERMISSION_HINTS[name] ?? {
    implication: entry?.description ?? 'Custom permission — review its scope before granting.',
    review: 'Unknown permission: require manual review.',
    sandbox: 'Treated as untrusted until allowlisted.',
  };
  return {
    ...hint,
    risk: entry?.risk ?? 'medium',
    requiresApproval: entry?.requires_approval ?? true,
  };
}

export const EXTENSION_TYPE_DESCRIPTIONS: Record<string, string> = {
  agent: 'Autonomous agent with tools + memory.',
  skill: 'Reusable capability bundle.',
  tool: 'Single callable tool via Tool Runtime.',
  'workflow-node': 'Custom node for workflow graphs.',
  connector: 'Third-party API integration.',
  'mcp-server': 'Full MCP server endpoint.',
  'mcp-tool': 'Single MCP-exposed tool.',
  'mcp-resource': 'MCP resource provider.',
  'mcp-prompt': 'MCP prompt template.',
  'workflow-template': 'Shareable workflow blueprint.',
  evaluator: 'Quality/safety evaluator.',
  'memory-provider': 'Custom memory backend.',
  'model-provider': 'Custom model provider.',
  'model-adapter': 'Adapter over an existing provider.',
  'browser-extension': 'Browser automation capability.',
  'sandbox-profile': 'Sandbox execution profile.',
  integration: 'Prebuilt third-party integration.',
  'ui-extension': 'Custom UI panel/widget.',
  'automation-pack': 'Bundle of automations.',
  'agent-team': 'Multi-agent team definition.',
};

export const DEFAULT_PERMISSIONS = ['tool:execute', 'filesystem:workspace'];

// ------------------------------------------------------- endpoint catalog + snippets

export interface EndpointDef {
  method: 'GET' | 'POST' | 'PUT' | 'DELETE';
  path: string;
  description: string;
  body?: string;
}

export const DEVELOPER_ENDPOINTS: EndpointDef[] = [
  { method: 'GET', path: '/organizations/{orgId}/developer/projects', description: 'List developer projects' },
  { method: 'POST', path: '/organizations/{orgId}/developer/projects', description: 'Create a developer project', body: '{\n  "slug": "my-project",\n  "name": "My Project",\n  "description": ""\n}' },
  { method: 'GET', path: '/organizations/{orgId}/developer/projects/{projectId}', description: 'Get project with environments' },
  { method: 'PUT', path: '/organizations/{orgId}/developer/projects/{projectId}/environments/{env}', description: 'Update environment config', body: '{\n  "api_endpoint": "https://api.example.com",\n  "config": {}\n}' },
  { method: 'GET', path: '/organizations/{orgId}/extensions?extension_type=&lifecycle=', description: 'List extensions (filter by type/lifecycle)' },
  { method: 'POST', path: '/organizations/{orgId}/extensions', description: 'Create extension definition', body: '{\n  "slug": "my-extension",\n  "extension_type": "tool",\n  "display_name": "My Extension",\n  "license": "MIT"\n}' },
  { method: 'GET', path: '/organizations/{orgId}/extensions/{extensionId}', description: 'Get extension with versions' },
  { method: 'POST', path: '/organizations/{orgId}/extensions/{extensionId}/versions', description: 'Create extension version', body: '{\n  "version": "1.0.0",\n  "manifest": {"name": "my-extension", "version": "1.0.0"},\n  "changelog": "Initial release"\n}' },
  { method: 'POST', path: '/organizations/{orgId}/extensions/{extensionId}/validate', description: 'Validate manifest + sources (no exec)', body: '{\n  "files": {},\n  "openagent_version": "1.0.0"\n}' },
  { method: 'POST', path: '/organizations/{orgId}/extensions/{extensionId}/test', description: 'Run sandboxed test harness', body: '{\n  "files": {},\n  "suite": "contract"\n}' },
  { method: 'POST', path: '/organizations/{orgId}/extensions/{extensionId}/package', description: 'Build deterministic .oaext package', body: '{\n  "files": {}\n}' },
  { method: 'POST', path: '/organizations/{orgId}/extensions/{extensionId}/publish', description: 'Security-gated publish', body: '{\n  "files": {}\n}' },
  { method: 'POST', path: '/organizations/{orgId}/extensions/{extensionId}/sign', description: 'Register signing key, get digest to sign offline', body: '{\n  "public_key": "<ed25519-pubkey>"\n}' },
  { method: 'POST', path: '/organizations/{orgId}/extensions/{extensionId}/sign/complete', description: 'Submit offline signature', body: '{\n  "key_id": "<key-id>",\n  "signature_b64": "<sig>"\n}' },
  { method: 'POST', path: '/organizations/{orgId}/extensions/{extensionId}/install', description: 'Install into an environment', body: '{\n  "version": "1.0.0",\n  "environment": "production",\n  "granted_permissions": []\n}' },
  { method: 'POST', path: '/organizations/{orgId}/extensions/{extensionId}/disable', description: 'Disable extension' },
  { method: 'POST', path: '/organizations/{orgId}/extensions/{extensionId}/quarantine', description: 'Emergency quarantine (dangerous)', body: '{\n  "reason": "malicious behavior observed"\n}' },
  { method: 'POST', path: '/organizations/{orgId}/extensions/{extensionId}/rollback?installation_id=', description: 'Rollback installation to known-good' },
  { method: 'POST', path: '/organizations/{orgId}/extensions/{extensionId}/deploy', description: 'Deploy through the pipeline', body: '{\n  "version": "1.0.0",\n  "environment": "staging"\n}' },
  { method: 'GET', path: '/organizations/{orgId}/developer/webhooks', description: 'List developer webhooks' },
  { method: 'POST', path: '/organizations/{orgId}/developer/webhooks', description: 'Register webhook (HTTPS only)', body: '{\n  "url": "https://example.com/hook",\n  "events": ["deployment.completed.v1"]\n}' },
  { method: 'GET', path: '/organizations/{orgId}/developer/events', description: 'Versioned developer event schemas' },
  { method: 'GET', path: '/organizations/{orgId}/developer/usage?days=30', description: 'Aggregated analytics (no PII)' },
  { method: 'GET', path: '/organizations/{orgId}/developer/deployments', description: 'List extension deployments' },
  { method: 'GET', path: '/developer/sdk', description: 'Public SDK metadata (no auth)' },
  { method: 'GET', path: '/registry/local/packages', description: 'Local offline registry packages' },
];

export function buildTsSnippet(ep: EndpointDef, orgId: string): string {
  const path = ep.path.replace('{orgId}', orgId || '<orgId>');
  const hasBody = ep.method === 'POST' || ep.method === 'PUT';
  const bodyArg = hasBody ? `, ${ep.body ?? '{}'}` : '';
  const fn = ep.method.toLowerCase();
  return `import { api } from '@/lib/api';\n\nconst orgId = '${orgId || '<orgId>'}';\nawait api.${fn}<unknown>('${path}'${bodyArg});`;
}

export function buildPythonSnippet(ep: EndpointDef, orgId: string): string {
  const path = ep.path.replace('{orgId}', orgId || '<orgId>');
  const base = "import os\nimport httpx\n\nBASE = os.environ.get('OPENAGENT_API', 'http://localhost:8000/api/v1')\nTOKEN = os.environ['OPENAGENT_TOKEN']\n";
  if (ep.method === 'GET' || ep.method === 'DELETE') {
    return `${base}\nr = httpx.${ep.method.toLowerCase()}(f"{BASE}${path}", headers={"Authorization": f"Bearer {TOKEN}"})\nr.raise_for_status()\nprint(r.json())`;
  }
  return `${base}\nr = httpx.${ep.method.toLowerCase()}(f"{BASE}${path}", headers={"Authorization": f"Bearer {TOKEN}"}, json=${ep.body ?? '{}'})\nr.raise_for_status()\nprint(r.json())`;
}

export function resolvePath(path: string, orgId: string): string {
  return path.replace('{orgId}', orgId || '<orgId>').replace('{organization_id}', orgId || '<orgId>');
}

export function redactHeaders(h: Record<string, string>): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(h)) {
    if (/authoriz|token|secret|api[-_]?key/i.test(k)) out[k] = '<redacted>';
    else out[k] = v;
  }
  return out;
}
