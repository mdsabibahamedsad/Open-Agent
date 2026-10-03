export type MCPTransportType = "stdio" | "streamable_http" | "sse";

export type MCPServerScope = "PLATFORM" | "ORGANIZATION" | "TEAM" | "USER";

export type MCPTrustLevel =
  "CORE" | "VERIFIED" | "ORGANIZATION" | "COMMUNITY" | "UNTRUSTED";

export type MCPServerStatus =
  | "DISCONNECTED"
  | "CONNECTING"
  | "CONNECTED"
  | "DEGRADED"
  | "ERROR"
  | "DISABLED";

export type MCPConnectionState =
  "CONNECTING" | "CONNECTED" | "DEGRADED" | "DISCONNECTED" | "FAILED";

export type MCPCapabilityType = "tools" | "resources" | "prompts";

export interface MCPServerConfig {
  id: string;
  name: string;
  display_name?: string;
  description?: string;
  organization_id: string;
  scope: MCPServerScope;
  transport: MCPTransportType;
  endpoint?: string;
  command?: string;
  args?: string[];
  env?: Record<string, string>;
  credential_id?: string;
  trust_level: MCPTrustLevel;
  enabled: boolean;
  metadata?: Record<string, unknown>;
  // Transport-specific runtime settings (working directory, allowlists,
  // injected auth headers). Written by the client, read by transports.
  configuration?: Record<string, unknown>;
  created_at: Date;
  updated_at: Date;
}

export type MCPCredentialType =
  "api_key" | "bearer_token" | "basic_auth" | "oauth_token";

export interface MCPCredentialData {
  api_key?: string;
  token?: string;
  username?: string;
  password?: string;
  access_token?: string;
}

export interface MCPCredential {
  type: MCPCredentialType;
  data: MCPCredentialData;
}

export interface MCPServerVersion {
  id: string;
  server_id: string;
  transport: MCPTransportType;
  endpoint?: string;
  command?: string;
  args?: string[];
  env?: Record<string, string>;
  credential_id?: string;
  configuration: Record<string, unknown>;
  policy: Record<string, unknown>;
  protocol_preferences?: Record<string, unknown>;
  created_at: Date;
}

export interface MCPConnection {
  id: string;
  server_id: string;
  session_id?: string;
  protocol_version?: string;
  state: MCPConnectionState;
  capabilities: MCPCapabilities;
  server_info?: MCPServerInfo;
  created_at: Date;
  last_activity: Date;
  expires_at?: Date;
}

export interface MCPServerInfo {
  name: string;
  version: string;
  protocol_version: string;
  capabilities: MCPCapabilities;
}

export interface MCPCapabilities {
  tools?: MCPToolsCapability;
  resources?: MCPResourcesCapability;
  prompts?: MCPPromptsCapability;
}

export interface MCPToolsCapability {
  list_changed?: boolean;
}

export interface MCPResourcesCapability {
  subscribe?: boolean;
  list_changed?: boolean;
}

export interface MCPPromptsCapability {
  list_changed?: boolean;
}

export interface MCPTool {
  name: string;
  title?: string;
  description?: string;
  inputSchema: MCPToolSchema;
  outputSchema?: MCPToolSchema;
  annotations?: MCPToolAnnotations;
}

export interface MCPToolAnnotations {
  title?: string;
  readOnlyHint?: boolean;
  destructiveHint?: boolean;
  idempotentHint?: boolean;
  openWorldHint?: boolean;
}

export interface MCPToolSchema {
  type: "object";
  properties: Record<string, MCPPropertySchema>;
  required?: string[];
  additionalProperties?: boolean | MCPPropertySchema;
}

export interface MCPPropertySchema {
  type?: string | string[];
  description?: string;
  default?: unknown;
  enum?: unknown[];
  format?: string;
  minimum?: number;
  maximum?: number;
  minLength?: number;
  maxLength?: number;
  pattern?: string;
  items?: MCPPropertySchema;
  properties?: Record<string, MCPPropertySchema>;
  required?: string[];
  additionalProperties?: boolean | MCPPropertySchema;
}

export interface MCPResource {
  uri: string;
  name: string;
  title?: string;
  description?: string;
  mimeType?: string;
  size?: number;
  metadata?: Record<string, unknown>;
}

export interface MCPResourceContent {
  uri: string;
  mimeType?: string;
  text?: string;
  blob?: string;
}

export interface MCPPrompt {
  name: string;
  title?: string;
  description?: string;
  arguments?: MCPPromptArgument[];
}

export interface MCPPromptArgument {
  name: string;
  title?: string;
  description?: string;
  required?: boolean;
}

export interface MCPPromptMessage {
  role: "user" | "assistant" | "system";
  content: MCPPromptContent;
}

export interface MCPPromptContent {
  type: "text";
  text: string;
}

export interface MCPToolCall {
  name: string;
  arguments: Record<string, unknown>;
}

export interface MCPToolResult {
  content: MCPContent[];
  isError?: boolean;
}

export interface MCPContent {
  type: "text" | "image" | "resource";
  text?: string;
  data?: string;
  mimeType?: string;
  resource?: MCPResource;
}

export interface MCPInitializeRequest {
  protocolVersion: string;
  capabilities: MCPClientCapabilities;
  clientInfo: MCPClientInfo;
}

export interface MCPClientCapabilities {
  sampling?: Record<string, unknown>;
  roots?: MCPRootsCapability;
  elicitation?: Record<string, unknown>;
}

export interface MCPRootsCapability {
  listChanged?: boolean;
}

export interface MCPClientInfo {
  name: string;
  version: string;
}

export interface MCPInitializeResult {
  protocolVersion: string;
  capabilities: MCPCapabilities;
  serverInfo: MCPServerInfo;
}

export interface MCPListToolsResult {
  tools: MCPTool[];
  nextCursor?: string;
}

export interface MCPCallToolResult {
  content: MCPContent[];
  isError?: boolean;
}

export interface MCPListResourcesResult {
  resources: MCPResource[];
  nextCursor?: string;
}

export interface MCPReadResourceResult {
  contents: MCPResourceContent[];
}

export interface MCPListPromptsResult {
  prompts: MCPPrompt[];
  nextCursor?: string;
}

export interface MCPGetPromptResult {
  description?: string;
  messages: MCPPromptMessage[];
}

export interface MCPError {
  code: number;
  message: string;
  data?: unknown;
}

export interface MCPRequest {
  jsonrpc: "2.0";
  id: string | number;
  method: string;
  params?: unknown;
}

export interface MCPResponse {
  jsonrpc: "2.0";
  id: string | number;
  result?: unknown;
  error?: MCPError;
}

export interface MCPNotification {
  jsonrpc: "2.0";
  method: string;
  params?: unknown;
}

export interface MCPErrorCodes {
  PARSE_ERROR: -32700;
  INVALID_REQUEST: -32600;
  METHOD_NOT_FOUND: -32601;
  INVALID_PARAMS: -32602;
  INTERNAL_ERROR: -32603;
  SERVER_NOT_FOUND: -32000;
  SERVER_UNAVAILABLE: -32001;
  CONNECTION_FAILED: -32002;
  PROTOCOL_ERROR: -32003;
  CAPABILITY_UNAVAILABLE: -32004;
  TOOL_NOT_FOUND: -32010;
  RESOURCE_NOT_FOUND: -32011;
  PROMPT_NOT_FOUND: -32012;
  SCHEMA_INVALID: -32020;
  TIMEOUT: -32030;
  CANCELLED: -32031;
  POLICY_BLOCKED: -32040;
  NOT_AUTHORIZED: -32041;
  CREDENTIAL_ERROR: -32050;
}

export const MCP_ERROR_CODES: MCPErrorCodes = {
  PARSE_ERROR: -32700,
  INVALID_REQUEST: -32600,
  METHOD_NOT_FOUND: -32601,
  INVALID_PARAMS: -32602,
  INTERNAL_ERROR: -32603,
  SERVER_NOT_FOUND: -32000,
  SERVER_UNAVAILABLE: -32001,
  CONNECTION_FAILED: -32002,
  PROTOCOL_ERROR: -32003,
  CAPABILITY_UNAVAILABLE: -32004,
  TOOL_NOT_FOUND: -32010,
  RESOURCE_NOT_FOUND: -32011,
  PROMPT_NOT_FOUND: -32012,
  SCHEMA_INVALID: -32020,
  TIMEOUT: -32030,
  CANCELLED: -32031,
  POLICY_BLOCKED: -32040,
  NOT_AUTHORIZED: -32041,
  CREDENTIAL_ERROR: -32050,
};

export interface MCPHealthRecord {
  server_id: string;
  status: "HEALTHY" | "DEGRADED" | "UNAVAILABLE" | "UNKNOWN" | "DISABLED";
  last_check: Date;
  connection_success: number;
  connection_failure: number;
  tool_success: number;
  tool_failure: number;
  resource_reads: number;
  prompt_reads: number;
  avg_latency_ms: number;
  timeouts: number;
  protocol_errors: number;
  last_success?: Date;
  last_failure?: Date;
}

export interface MCPRateLimitConfig {
  connections_per_minute: number;
  tool_calls_per_minute: number;
  resource_reads_per_minute: number;
  prompt_reads_per_minute: number;
  max_concurrent_connections: number;
  max_concurrent_tool_calls: number;
  max_concurrent_resource_reads: number;
}

export interface MCPPolicy {
  id: string;
  organization_id: string;
  team_id?: string;
  agent_id?: string;
  workflow_id?: string;
  name: string;
  allowed_servers: string[];
  blocked_servers: string[];
  allowed_domains: string[];
  blocked_domains: string[];
  allowed_trust_levels: MCPTrustLevel[];
  max_risk_level?: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
  approval_required: Record<string, boolean>;
  execution_limits: MCPExecutionLimits;
  is_active: boolean;
  created_at: Date;
  updated_at: Date;
}

export interface MCPExecutionLimits {
  max_concurrent_tool_calls: number;
  max_tool_execution_time_ms: number;
  max_output_size_bytes: number;
  max_resource_size_bytes: number;
  daily_tool_call_limit: number;
}

export interface MCPInstallationRequest {
  name: string;
  display_name?: string;
  description?: string;
  transport: MCPTransportType;
  endpoint?: string;
  command?: string;
  args?: string[];
  env?: Record<string, string>;
  credential_id?: string;
  trust_level: MCPTrustLevel;
  scope: MCPServerScope;
}

export interface MCPConnectionTestResult {
  success: boolean;
  server_info?: MCPServerInfo;
  capabilities?: MCPCapabilities;
  tools_count: number;
  resources_count: number;
  prompts_count: number;
  error?: string;
  latency_ms: number;
}

export interface MCPRefreshResult {
  tools_added: string[];
  tools_removed: string[];
  tools_updated: string[];
  resources_added: string[];
  resources_removed: string[];
  resources_updated: string[];
  prompts_added: string[];
  prompts_removed: string[];
  prompts_updated: string[];
}
