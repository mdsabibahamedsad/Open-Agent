// @openagent/sdk-types — canonical public developer API types (v1).
// Strongly typed, documented, serializable, versioned. These are the
// stable boundary: internal backend shapes are mapped INTO these types,
// never leaked through them.

export const SDK_TYPES_VERSION = '1.0.0';
export const API_VERSION = 'v1';
export const EXTENSION_API_VERSION = '1.x';
export const MANIFEST_VERSION = '1';

export type ID = string;
export type ISODateTime = string;

export interface Paginated<T> {
  items: T[];
  page: number;
  page_size: number;
  total: number;
  has_more: boolean;
}

export interface PaginationParams {
  page?: number;
  page_size?: number;
  cursor?: string;
}

export type ExtensionType =
  | 'agent' | 'skill' | 'tool' | 'workflow-node' | 'connector'
  | 'mcp-server' | 'mcp-tool' | 'mcp-resource' | 'mcp-prompt'
  | 'workflow-template' | 'evaluator' | 'memory-provider'
  | 'model-provider' | 'model-adapter' | 'browser-extension'
  | 'sandbox-profile' | 'integration' | 'ui-extension'
  | 'automation-pack' | 'agent-team';

export type TrustLevel = 'CORE' | 'VERIFIED' | 'ORGANIZATION' | 'COMMUNITY' | 'UNTRUSTED';

export type LifecycleStatus =
  | 'DRAFT' | 'VALIDATED' | 'PACKAGED' | 'SIGNED' | 'PUBLISHED'
  | 'ACTIVE' | 'DISABLED' | 'DEPRECATED' | 'QUARANTINED'
  | 'REVOKED' | 'UNPUBLISHED';

export type EnvironmentName = 'development' | 'staging' | 'production';

export type ExtensionPermission =
  | 'network:outbound' | 'network:restricted' | 'filesystem:workspace'
  | 'filesystem:artifact' | 'tool:execute' | 'connector:use'
  | 'memory:read' | 'memory:write' | 'browser:use' | 'sandbox:execute'
  | 'mcp:connect' | 'secret:access' | 'workflow:execute' | 'agent:invoke'
  | 'model:invoke' | 'evaluation:run' | 'webhook:receive'
  | 'storage:use' | 'billing:read';

export interface Agent {
  id: ID; name: string; description?: string; model?: string;
  instructions?: string; status?: string;
  created_at?: ISODateTime; updated_at?: ISODateTime;
}

export interface AgentVersion {
  id: ID; agent_id: ID; version: string; definition?: Record<string, unknown>;
  created_at?: ISODateTime;
}

export interface AgentRun {
  id: ID; agent_id: ID; status: string;
  output?: unknown; error?: string;
  created_at?: ISODateTime; updated_at?: ISODateTime;
}

export interface Tool {
  id: ID; name: string; slug?: string; description?: string;
  category?: string; risk_level?: string; trust_level?: TrustLevel;
  input_schema?: Record<string, unknown>;
  status?: string;
}

export interface ToolVersion {
  id: ID; tool_id: ID; version: string; input_schema?: Record<string, unknown>;
}

export interface ToolInvocation {
  tool_id: ID; input?: unknown; idempotency_key?: string; approved?: boolean;
}

export interface ToolResult {
  execution_id: ID; status: string; output?: unknown; error?: string;
}

export interface Workflow {
  id: ID; name: string; description?: string; status?: string;
  created_at?: ISODateTime; updated_at?: ISODateTime;
}

export interface WorkflowVersion {
  id: ID; workflow_id: ID; version: string; definition?: Record<string, unknown>;
}

export interface WorkflowNode {
  id?: string; type: string; config?: Record<string, unknown>;
  inputs?: unknown[]; outputs?: unknown[];
}

export interface WorkflowExecution {
  id: ID; workflow_id: ID; status: string; outputs?: unknown;
  created_at?: ISODateTime;
}

export interface Connector {
  id: ID; slug: string; name: string; category?: string; trust?: string;
}

export interface ConnectorVersion {
  id: ID; connector_id: ID; version: string;
}

export interface ConnectorAction {
  id: string; name: string; description?: string;
  input_schema?: Record<string, unknown>;
}

export interface ConnectorTrigger {
  id: string; name: string; event_types?: string[];
}

export interface MCPServer {
  id: ID; name: string; transport?: string; status?: string; trust?: string;
}

export interface MCPTool {
  name: string; description?: string; input_schema?: Record<string, unknown>;
}

export interface MCPResource {
  uri: string; name: string; mime_type?: string;
}

export interface MCPPrompt {
  name: string; description?: string; arguments?: unknown[];
}

export interface Skill {
  id: ID; name: string; slug?: string; description?: string; version?: string;
}

export interface SkillVersion {
  id: ID; skill_id: ID; version: string;
}

export interface Memory {
  id: ID; key?: string; value?: unknown; scope?: string;
}

export interface Evaluation {
  id: ID; status: string; decision?: string; score?: number;
}

export interface Sandbox {
  id: ID; status: string; profile?: string;
}

export interface ApprovalRequest {
  id: ID; action_type: string; status: string; risk_level?: string;
}

export interface Model {
  id: string; provider?: string; capabilities?: string[];
}

export interface ModelProvider {
  id: string; name: string; models?: Model[];
}

export interface RegistryPackage {
  name: string; version: string; digest?: string; registry?: string;
}

export interface ExtensionManifest {
  manifest_version?: string;
  name: string;
  namespace?: string;
  version: string;
  displayName?: string;
  description: string;
  author: { name: string; email?: string; url?: string };
  license: string;
  repository?: string;
  documentation?: string;
  type: ExtensionType;
  runtime: { language: string; entrypoint: string; version?: string };
  permissions?: ExtensionPermission[];
  capabilities?: string[];
  required_services?: string[];
  config_schema?: Record<string, unknown>;
  secrets?: string[];
  network?: Record<string, unknown>;
  storage?: Record<string, unknown>;
  compatibility?: Record<string, string>;
  dependencies?: Array<{ name: string; version?: string; optional?: boolean }>;
  metadata?: Record<string, unknown>;
  security?: Record<string, unknown>;
}

export interface Extension {
  id: ID; slug: string; type: ExtensionType;
  lifecycle: LifecycleStatus; trust: TrustLevel;
}

export interface DeveloperProject {
  id: ID; slug: string; name: string; description?: string; status?: string;
}

export interface Deployment {
  id: ID; extension?: string; environment?: string; status: string;
  stages?: string[];
}

export interface Artifact {
  digest: string; size_bytes: number; filename?: string;
}

export interface Version {
  version: string; changelog?: string; deprecated?: boolean;
}

export interface Capability {
  name: string; description?: string;
}

export interface Policy {
  id: ID; name: string; rules?: unknown[];
}

export interface DeveloperEvent {
  event: string;
  delivery_id: string;
  timestamp: number;
  payload?: Record<string, unknown>;
}
