// OpenAgent Connector SDK — build connectors without modifying core.
// Target: Core → SDK → Connector Package. Version: 0.1.0.

export const CONNECTOR_SDK_VERSION = '0.1.0';

export type ConnectorType =
  | 'OFFICIAL' | 'COMMUNITY' | 'CUSTOM' | 'INTERNAL'
  | 'MCP_BACKED' | 'HTTP_GENERIC' | 'DATABASE' | 'WEBHOOK_ONLY';

export type TrustTier =
  | 'CORE' | 'VERIFIED' | 'ORGANIZATION' | 'COMMUNITY' | 'CUSTOM' | 'UNTRUSTED';

export type AuthType =
  | 'oauth2' | 'api_key' | 'basic' | 'jwt'
  | 'service_account' | 'custom_header' | 'none';

export type RiskLevel = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
export type TriggerKind = 'webhook' | 'polling' | 'schedule' | 'event' | 'manual';

export interface JsonSchema {
  type: string;
  properties?: Record<string, JsonSchema & { enum?: unknown[] }>;
  required?: string[];
  items?: JsonSchema;
  additionalProperties?: boolean;
  enum?: unknown[];
  minimum?: number;
  maximum?: number;
  minLength?: number;
  maxLength?: number;
  [key: string]: unknown;
}

export interface CapabilityDef {
  id: string;
  description?: string;
  risk_level?: RiskLevel;
}

export interface ActionDef {
  id: string;
  name: string;
  description?: string;
  input_schema: JsonSchema;
  output_schema?: JsonSchema;
  required_capabilities: string[];
  risk_level?: RiskLevel;
  supports_idempotency?: boolean;
  idempotency_strategy?: string;
  supports_async?: boolean;
  timeout_seconds?: number;
  rate_limit_per_minute?: number;
  verification?: Record<string, unknown>;
  mutation?: boolean;
}

export interface TriggerDef {
  id: string;
  name: string;
  kind?: TriggerKind;
  description?: string;
  event_types?: string[];
  payload_schema?: JsonSchema;
  poll_config?: Record<string, unknown>;
}

export interface ResourceDef {
  kind: string;
  provider_kind?: string;
  schema?: JsonSchema;
}

export interface ConnectorManifest {
  id: string;
  name: string;
  version: string;
  category?: string;
  type?: ConnectorType;
  trust?: TrustTier;
  description?: string;
  publisher?: string;
  license?: string;
  documentation_url?: string;
  auth?: Record<string, unknown>;
  capabilities: CapabilityDef[];
  actions: ActionDef[];
  triggers?: TriggerDef[];
  resources?: ResourceDef[];
  scopes?: string[];
  rate_limits?: Record<string, unknown>;
  supported_environments?: string[];
  signature?: string;
}

const SLUG = /^[a-z0-9][a-z0-9_.-]{1,63}$/;
const VERSION = /^\d+\.\d+\.\d+([-.+][0-9A-Za-z.-]+)?$/;
const KNOWN_AUTH: AuthType[] = ['oauth2', 'api_key', 'basic', 'jwt', 'service_account', 'custom_header', 'none'];
const KNOWN_RISK: RiskLevel[] = ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL'];

export class ManifestError extends Error {
  code = 'MANIFEST_INVALID';
}

/** Client-side manifest validation (server re-validates authoritatively). */
export function validateManifest(raw: unknown): ConnectorManifest {
  if (!raw || typeof raw !== 'object') throw new ManifestError('Manifest must be an object');
  const m = raw as Record<string, unknown>;
  const id = String(m.id ?? '').toLowerCase();
  if (!SLUG.test(id)) throw new ManifestError(`Invalid connector id '${m.id}'`);
  if (typeof m.version !== 'string' || !VERSION.test(m.version)) {
    throw new ManifestError(`Invalid semantic version '${m.version}'`);
  }
  const auth = (m.auth ?? {}) as Record<string, unknown>;
  if (!KNOWN_AUTH.includes(String(auth.type ?? 'none') as AuthType)) {
    throw new ManifestError(`Unknown auth type '${auth.type}'`);
  }
  const capabilities = (m.capabilities ?? []) as CapabilityDef[];
  if (!Array.isArray(capabilities) || capabilities.length === 0) {
    throw new ManifestError('Manifest must declare at least one capability');
  }
  for (const c of capabilities) {
    if (!String(c.id ?? '').startsWith(`${id}.`)) {
      throw new ManifestError(`Capability '${c.id}' must be namespaced '${id}.*'`);
    }
    if (c.risk_level && !KNOWN_RISK.includes(c.risk_level)) {
      throw new ManifestError(`Unknown risk_level '${c.risk_level}'`);
    }
  }
  const known = new Set(capabilities.map((c) => c.id));
  const actions = (m.actions ?? []) as ActionDef[];
  for (const a of actions) {
    if (!String(a.id ?? '').startsWith(`${id}.`)) {
      throw new ManifestError(`Action '${a.id}' must be namespaced '${id}.*'`);
    }
    if (!a.input_schema || a.input_schema.type !== 'object') {
      throw new ManifestError(`Action '${a.id}' input_schema must be a JSON object schema`);
    }
    for (const cap of a.required_capabilities ?? []) {
      if (!known.has(cap)) throw new ManifestError(`Action '${a.id}' requires unknown capability '${cap}'`);
    }
  }
  if (!String(m.name ?? '').trim()) throw new ManifestError('Connector requires a name');
  const scopes = (m.scopes ?? []) as string[];
  if (scopes.length > 64) throw new ManifestError('Excessive scope request (>64) rejected');
  return m as unknown as ConnectorManifest;
}

/** Scaffold a new connector package (mirrors scripts/connector-new.py output). */
export function scaffoldConnector(id: string, name: string): Record<string, string> {
  const slug = id.toLowerCase().replace(/[^a-z0-9_.-]/g, '_');
  const manifest: ConnectorManifest = {
    id: slug,
    name,
    version: '1.0.0',
    category: 'automation',
    type: 'CUSTOM',
    trust: 'CUSTOM',
    description: `${name} connector.`,
    publisher: '',
    license: '',
    auth: { type: 'api_key' },
    capabilities: [{ id: `${slug}.items.read`, description: 'Read items', risk_level: 'LOW' }],
    actions: [
      {
        id: `${slug}.list_items`,
        name: 'List items',
        description: 'List items.',
        input_schema: { type: 'object', properties: {}, required: [] },
        required_capabilities: [`${slug}.items.read`],
        risk_level: 'LOW',
        mutation: false,
      },
    ],
    triggers: [],
    resources: [],
    scopes: [],
  };
  return {
    'manifest.json': JSON.stringify(manifest, null, 2),
    'README.md': `# ${name} connector\n\nFill in authentication, actions, and tests.\n`,
  };
}

/** Compact action descriptor for agent context (never full docs). */
export function compactAction(action: ActionDef, trust: string): string {
  return `${action.id} — ${(action.description || action.name).slice(0, 120)} [${trust}]`;
}
