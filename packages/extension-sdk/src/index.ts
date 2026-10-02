// @openagent/extension-sdk — official authoring SDK (§14-20).
// define* builders compile into canonical OpenAgent definitions.
// Runtime enforcement (RBAC, policy, sandbox, approvals) always happens
// server-side; these builders only DECLARE intent + permissions.

import type {
  ExtensionManifest,
  ExtensionPermission,
} from '@openagent/sdk-types';

export const EXTENSION_SDK_VERSION = '1.0.0';
export const EXTENSION_API_VERSION = '1.x';

export type {
  ExtensionManifest,
  ExtensionPermission,
  ExtensionType,
} from '@openagent/sdk-types';

// ------------------------------------------------------------------ agent --

export interface AgentModelRef {
  alias?: string;
  provider?: string;
  model?: string;
  routing?: Record<string, unknown>;
}

export interface AgentLimits {
  maxSteps?: number;
  maxDurationSeconds?: number;
  budget?: Record<string, unknown>;
}

export interface AgentDefinition {
  kind: 'agent';
  name: string;
  instructions: string;
  model?: AgentModelRef;
  tools?: Array<string | { name: string; config?: Record<string, unknown> }>;
  skills?: string[];
  memory?: { enabled: boolean; scope?: string };
  policies?: string[];
  permissions?: string[];
  limits?: { maxSteps?: number; maxDurationSeconds?: number; budget?: Record<string, unknown> };
  outputSchema?: Record<string, unknown>;
  evaluation?: Record<string, unknown>;
  lifecycle?: Record<string, unknown>;
}

export function defineAgent(def: {
  name: string;
  instructions: string;
  model?: AgentModelRef;
  tools?: AgentDefinition['tools'];
  skills?: string[];
  memory?: AgentDefinition['memory'];
  policies?: string[];
  permissions?: string[];
  limits?: AgentDefinition['limits'];
  outputSchema?: Record<string, unknown>;
  evaluation?: Record<string, unknown>;
  onStart?: unknown;
  onComplete?: unknown;
  onError?: unknown;
}): AgentDefinition {
  if (!def.name) throw new Error('defineAgent requires a name');
  if (!def.instructions || !def.instructions.trim()) {
    throw new Error('defineAgent requires non-empty instructions');
  }
  const { onStart, onComplete, onError, ...rest } = def;
  void onStart; void onComplete; void onError;
  return {
    kind: 'agent',
    model: { alias: 'smart' },
    memory: { enabled: false },
    ...rest,
    tools: def.tools ?? [],
    skills: def.skills ?? [],
  };
}

// ------------------------------------------------------------------- tool --

export interface ToolContext {
  agentId?: string;
  runId?: string;
  organizationId?: string;
  approved: boolean;
  timeoutMs: number;
  signal?: AbortSignal;
  log: (message: string, fields?: Record<string, unknown>) => void;
  artifact: (name: string, content: Uint8Array | string) => Promise<void>;
}

export interface ToolDefinition<TInput = unknown, TOutput = unknown> {
  kind: 'tool';
  name: string;
  description: string;
  inputSchema: Record<string, unknown>;
  outputSchema?: Record<string, unknown>;
  riskLevel: 'low' | 'medium' | 'high' | 'critical';
  timeoutMs?: number;
  retries?: { maxAttempts?: number };
  credentials?: string[];
  execute: (input: TInput, context: ToolContext) => Promise<TOutput>;
}

export function defineTool<TInput = unknown, TOutput = unknown>(def: {
  name: string;
  description: string;
  inputSchema: Record<string, unknown>;
  outputSchema?: Record<string, unknown>;
  riskLevel?: ToolDefinition['riskLevel'];
  timeoutMs?: number;
  retries?: { maxAttempts?: number };
  credentials?: string[];
  execute: (input: TInput, context: ToolContext) => Promise<TOutput>;
}): ToolDefinition<TInput, TOutput> {
  if (!def.name) throw new Error('defineTool requires a name');
  if (!def.description) throw new Error('defineTool requires a description');
  if (!def.inputSchema || typeof def.inputSchema !== 'object') {
    throw new Error('defineTool requires an inputSchema object');
  }
  if (typeof def.execute !== 'function') throw new Error('defineTool requires an execute function');
  return { kind: 'tool', riskLevel: 'low', ...def };
}

// ---------------------------------------------------------- workflow node --

export interface NodePort {
  name: string;
  schema?: Record<string, unknown>;
  required?: boolean;
}

export interface NodeContext {
  inputs: Record<string, unknown>;
  config: Record<string, unknown>;
  runId?: string;
  signal?: AbortSignal;
  log: (message: string) => void;
}

export interface WorkflowNodeDefinition {
  kind: 'workflow-node';
  type: string;
  displayName?: string;
  description?: string;
  inputs: NodePort[];
  outputs: NodePort[];
  configSchema?: Record<string, unknown>;
  credentials?: string[];
  ui?: Record<string, unknown>;
  execute: (context: NodeContext) => Promise<Record<string, unknown>>;
}

export function defineWorkflowNode(def: {
  type: string;
  displayName?: string;
  description?: string;
  inputs?: NodePort[];
  outputs?: NodePort[];
  configSchema?: Record<string, unknown>;
  credentials?: string[];
  ui?: Record<string, unknown>;
  execute: (context: NodeContext) => Promise<Record<string, unknown>>;
}): WorkflowNodeDefinition {
  if (!def.type) throw new Error('defineWorkflowNode requires a type (e.g. "example.transform")');
  if (typeof def.execute !== 'function') throw new Error('defineWorkflowNode requires an execute function');
  return { kind: 'workflow-node', inputs: [], outputs: [], ...def };
}

// --------------------------------------------------------------- connector --

export interface ConnectorActionDef {
  id: string;
  name: string;
  description?: string;
  inputSchema?: Record<string, unknown>;
  run: (input: unknown, ctx: { connectionId: string; signal?: AbortSignal }) => Promise<unknown>;
}

export interface ConnectorDefinition {
  kind: 'connector';
  slug: string;
  displayName: string;
  auth: { kind: 'oauth2' | 'api-key' | 'webhook' | 'none'; scopes?: string[] };
  actions: ConnectorActionDef[];
  triggers?: Array<{ id: string; eventTypes: string[] }>;
  healthCheck?: { action: string };
  rateLimits?: Record<string, unknown>;
}

export function defineConnector(def: {
  slug: string;
  displayName: string;
  auth?: ConnectorDefinition['auth'];
  actions: ConnectorActionDef[];
  triggers?: ConnectorDefinition['triggers'];
  healthCheck?: ConnectorDefinition['healthCheck'];
  rateLimits?: Record<string, unknown>;
}): ConnectorDefinition {
  if (!def.slug) throw new Error('defineConnector requires a slug');
  if (!def.actions || def.actions.length === 0) {
    throw new Error('defineConnector requires at least one action');
  }
  return { kind: 'connector', auth: { kind: 'api-key' }, ...def };
}

// --------------------------------------------------------------------- MCP --

export interface MCPServerDefinition {
  kind: 'mcp-server';
  name: string;
  version?: string;
  transport?: 'stdio' | 'http' | 'websocket';
  tools: Array<{
    name: string;
    description: string;
    inputSchema?: Record<string, unknown>;
    run: (input: unknown) => Promise<unknown>;
  }>;
  resources?: Array<{ uri: string; name: string; mimeType?: string; read: () => Promise<unknown> }>;
  prompts?: Array<{ name: string; description?: string; render: (args: unknown) => Promise<string> }>;
  capabilities?: string[];
}

export function defineMCPServer(def: {
  name: string;
  version?: string;
  transport?: MCPServerDefinition['transport'];
  tools: MCPServerDefinition['tools'];
  resources?: MCPServerDefinition['resources'];
  prompts?: MCPServerDefinition['prompts'];
  capabilities?: string[];
}): MCPServerDefinition {
  if (!def.name) throw new Error('defineMCPServer requires a name');
  return { kind: 'mcp-server', transport: 'http', ...def };
}

// ------------------------------------------------------------------- skill --

export interface SkillDefinition {
  kind: 'skill';
  name: string;
  description: string;
  instructions: string;
  workflows?: string[];
  toolPreferences?: string[];
  templates?: Record<string, unknown>;
  knowledgeRefs?: string[];
  policies?: string[];
  examples?: Array<{ input: string; output: string }>;
  evaluation?: Record<string, unknown>;
}

export function defineSkill(def: {
  name: string;
  description: string;
  instructions: string;
  workflows?: string[];
  toolPreferences?: string[];
  templates?: Record<string, unknown>;
  knowledgeRefs?: string[];
  policies?: string[];
  examples?: Array<{ input: string; output: string }>;
  evaluation?: Record<string, unknown>;
}): SkillDefinition {
  if (!def.name) throw new Error('defineSkill requires a name');
  if (!def.instructions) throw new Error('defineSkill requires instructions');
  // Skills can never override system/security policy — enforced server-side,
  // but reject obviously abusive declarations early.
  for (const policy of def.policies ?? []) {
    if (/bypass|override.+(policy|rbac|approval|sandbox)/i.test(policy)) {
      throw new Error(`skill policy '${policy}' attempts to override platform policy — refused`);
    }
  }
  return { kind: 'skill', ...def };
}

// --------------------------------------------------------------- evaluator --

export interface EvaluatorContext {
  goal?: string;
  input?: unknown;
  output?: unknown;
  evidence?: unknown[];
  signal?: AbortSignal;
}

export interface EvaluationVerdict {
  score: number; // 0..1
  passed: boolean;
  findings?: string[];
  evidence?: unknown[];
}

export interface EvaluatorDefinition {
  kind: 'evaluator';
  name: string;
  description?: string;
  evaluate: (context: EvaluatorContext) => Promise<EvaluationVerdict> | EvaluationVerdict;
}

export function defineEvaluator(def: {
  name: string;
  description?: string;
  evaluate: (context: EvaluatorContext) => Promise<EvaluationVerdict> | EvaluationVerdict;
}): EvaluatorDefinition {
  if (!def.name) throw new Error('defineEvaluator requires a name');
  if (typeof def.evaluate !== 'function') throw new Error('defineEvaluator requires an evaluate function');
  return { kind: 'evaluator', ...def };
}

// ---------------------------------------------------------------- manifest --

export function defineManifest(manifest: ExtensionManifest): ExtensionManifest {
  if (!manifest.name) throw new Error('manifest requires a name');
  if (!manifest.type) throw new Error('manifest requires a type');
  return {
    manifest_version: '1',
    compatibility: { openagent: '>=1.0.0 <2.0.0', sdk: '>=1.0.0 <2.0.0', extension_api: '1.x' },
    ...manifest,
  };
}

/** Build an openagent.yaml-ready object from a definition + metadata. */
export function manifestFor(
  def: AgentDefinition | ToolDefinition | WorkflowNodeDefinition | ConnectorDefinition | MCPServerDefinition | SkillDefinition | EvaluatorDefinition,
  meta: {
    name: string; version: string; description: string;
    author: { name: string; email?: string };
    license?: string; permissions?: ExtensionPermission[];
  },
): ExtensionManifest {
  const typeMap: Record<string, ExtensionManifest['type']> = {
    agent: 'agent', tool: 'tool', 'workflow-node': 'workflow-node',
    connector: 'connector', 'mcp-server': 'mcp-server',
    skill: 'skill', evaluator: 'evaluator',
  };
  const kind = (def as { kind: string }).kind;
  const type = typeMap[kind];
  if (!type) throw new Error(`cannot infer manifest type for kind '${kind}'`);
  return defineManifest({
    name: meta.name,
    version: meta.version,
    description: meta.description,
    author: meta.author,
    license: meta.license ?? 'MIT',
    type,
    runtime: { language: 'typescript', entrypoint: 'src/index.ts' },
    permissions: meta.permissions ?? ['tool:execute'],
  });
}
