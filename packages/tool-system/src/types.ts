import { JSONSchema } from "@openagent/types";

export type { JSONSchema } from "@openagent/types";

export type ToolCategory =
  | "communication"
  | "web"
  | "browser"
  | "http"
  | "database"
  | "filesystem"
  | "code"
  | "shell"
  | "search"
  | "documents"
  | "media"
  | "calendar"
  | "email"
  | "messaging"
  | "crm"
  | "analytics"
  | "finance"
  | "developer"
  | "system"
  | "ai"
  | "utility"
  | "custom";

export const ToolCategoryValues: ToolCategory[] = [
  "communication",
  "web",
  "browser",
  "http",
  "database",
  "filesystem",
  "code",
  "shell",
  "search",
  "documents",
  "media",
  "calendar",
  "email",
  "messaging",
  "crm",
  "analytics",
  "finance",
  "developer",
  "system",
  "ai",
  "utility",
  "custom",
];

export type ToolCapability =
  | "read"
  | "write"
  | "delete"
  | "network"
  | "filesystem"
  | "process_execution"
  | "browser_control"
  | "database_access"
  | "credential_access"
  | "external_api"
  | "message_send"
  | "email_send"
  | "code_execution"
  | "system_control"
  | "financial_action";

export const ToolCapabilityValues: ToolCapability[] = [
  "read",
  "write",
  "delete",
  "network",
  "filesystem",
  "process_execution",
  "browser_control",
  "database_access",
  "credential_access",
  "external_api",
  "message_send",
  "email_send",
  "code_execution",
  "system_control",
  "financial_action",
];

export type ToolRiskLevel = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";

export type ToolExecutionMode =
  "SYNC" | "ASYNC" | "STREAMING" | "BACKGROUND" | "WAITING";

export type ToolLifecycleStatus =
  "DRAFT" | "ACTIVE" | "DISABLED" | "DEPRECATED" | "REVOKED";

export type ToolTrustLevel =
  "CORE" | "VERIFIED" | "ORGANIZATION" | "COMMUNITY" | "UNTRUSTED";

export type ToolProviderType =
  | "BUILTIN"
  | "HTTP_API"
  | "PYTHON_PACKAGE"
  | "JAVASCRIPT_PACKAGE"
  | "EXTERNAL_SERVICE"
  | "MCP"
  | "MARKETPLACE"
  | "BROWSER"
  | "CODING_RUNTIME"
  | "CUSTOM";

export interface ToolMetadata {
  name: string;
  display_name: string;
  description: string;
  icon?: string;
  category: ToolCategory;
  tags: string[];
  documentation_url?: string;
  provider: string;
  version: string;
  capabilities: ToolCapability[];
  risk_level: ToolRiskLevel;
  execution_mode: ToolExecutionMode;
  timeout: number;
  retry_policy?: RetryPolicy;
  supports_streaming: boolean;
  supports_cancellation: boolean;
  supports_idempotency: boolean;
  trust_level: ToolTrustLevel;
}

export interface RetryPolicy {
  max_attempts: number;
  backoff: number;
  jitter: number;
  retryable_errors: string[];
}

export interface ToolDefinition {
  id: string;
  organization_id?: string;
  slug: string;
  metadata: ToolMetadata;
  input_schema: JSONSchema;
  output_schema?: JSONSchema;
  status: ToolLifecycleStatus;
  configuration: Record<string, unknown>;
  created_at: Date;
  updated_at: Date;
  deleted_at?: Date;
}

export interface ToolVersion {
  id: string;
  tool_id: string;
  version: string;
  metadata: ToolMetadata;
  input_schema: JSONSchema;
  output_schema?: JSONSchema;
  configuration: Record<string, unknown>;
  status: ToolLifecycleStatus;
  checksum: string;
  created_at: Date;
  published_at?: Date;
  deprecated_at?: Date;
}

export interface ToolProvider {
  id: string;
  name: string;
  provider_type: ToolProviderType;
  configuration: Record<string, unknown>;
  supported_tool_types: string[];
  health_status: "HEALTHY" | "DEGRADED" | "UNAVAILABLE" | "UNKNOWN";
  last_health_check?: Date;
  created_at: Date;
  updated_at: Date;
}

export interface ToolExecutionContext {
  execution_id: string;
  tool_execution_id: string;
  organization_id: string;
  user_id?: string;
  agent_id?: string;
  workflow_id?: string;
  task_id?: string;
  node_execution_id?: string;
  permissions: string[];
  policy: ToolPolicy;
  credentials: Record<string, unknown>;
  deadline: Date;
  cancellation_token: CancellationToken;
  metadata: Record<string, unknown>;
}

export interface CancellationToken {
  cancelled: boolean;
  reason?: string;
  on_cancelled: (callback: () => void) => void;
}

export interface ToolInvocation {
  tool_id: string;
  tool_version: string;
  input: Record<string, unknown>;
  execution_context: ToolExecutionContext;
  timeout?: number;
  idempotency_key?: string;
}

export interface ToolResult {
  success: boolean;
  output?: Record<string, unknown>;
  error?: ToolError;
  metadata: Record<string, unknown>;
  duration_ms: number;
  usage?: ToolUsage;
  retryable: boolean;
  truncated: boolean;
  artifacts: ToolArtifact[];
}

export interface ToolError {
  code: ToolErrorCode;
  message: string;
  details?: Record<string, unknown>;
  retryable: boolean;
}

export type ToolErrorCode =
  | "TOOL_NOT_FOUND"
  | "TOOL_DISABLED"
  | "TOOL_VERSION_NOT_FOUND"
  | "TOOL_NOT_AUTHORIZED"
  | "TOOL_POLICY_BLOCKED"
  | "INVALID_TOOL_INPUT"
  | "TOOL_TIMEOUT"
  | "TOOL_CANCELLED"
  | "TOOL_RATE_LIMITED"
  | "TOOL_UNAVAILABLE"
  | "TOOL_EXECUTION_FAILED"
  | "TOOL_OUTPUT_INVALID"
  | "CREDENTIAL_UNAVAILABLE"
  | "APPROVAL_REQUIRED"
  | "SCHEMA_VALIDATION_FAILED"
  | "PROVIDER_ERROR"
  | "RESOURCE_LIMIT_EXCEEDED";

export interface ToolUsage {
  estimated_cost?: number;
  actual_cost?: number;
  tokens_used?: number;
  api_calls?: number;
}

export interface ToolArtifact {
  id: string;
  type: string;
  name: string;
  size: number;
  url: string;
  metadata: Record<string, unknown>;
}

export interface ToolPolicy {
  allowed_tools: string[];
  blocked_tools: string[];
  allowed_categories: ToolCategory[];
  blocked_categories: ToolCategory[];
  allowed_risk_levels: ToolRiskLevel[];
  max_risk_level?: ToolRiskLevel;
  allowed_capabilities: ToolCapability[];
  blocked_capabilities: ToolCapability[];
  allowed_domains: string[];
  blocked_domains: string[];
  allowed_organizations: string[];
  approval_required: Record<string, boolean>;
  execution_limits: ExecutionLimits;
}

export interface ExecutionLimits {
  max_concurrent_executions: number;
  max_execution_time_seconds: number;
  max_output_size_bytes: number;
  max_input_size_bytes: number;
  daily_execution_limit: number;
}

export interface ToolExecutionRecord {
  id: string;
  tool_id: string;
  tool_version_id: string;
  organization_id: string;
  agent_id?: string;
  workflow_id?: string;
  user_id?: string;
  status: ToolExecutionStatus;
  input: Record<string, unknown>;
  output?: Record<string, unknown>;
  error?: ToolError;
  started_at: Date;
  completed_at?: Date;
  duration_ms: number;
  retry_count: number;
  estimated_cost?: number;
  actual_cost?: number;
  metadata: Record<string, unknown>;
}

export type ToolExecutionStatus =
  | "QUEUED"
  | "RUNNING"
  | "WAITING"
  | "SUCCEEDED"
  | "FAILED"
  | "CANCELLED"
  | "TIMED_OUT"
  | "REQUIRES_APPROVAL";

export interface ToolHealthRecord {
  tool_id: string;
  status: "HEALTHY" | "DEGRADED" | "UNAVAILABLE" | "UNKNOWN";
  last_check: Date;
  success_count: number;
  failure_count: number;
  avg_latency_ms: number;
  last_success?: Date;
  last_failure?: Date;
  error_rate: number;
}

export interface ToolPromptRepresentation {
  name: string;
  description: string;
  input_schema: JSONSchema;
  capabilities: ToolCapability[];
  risk_level: ToolRiskLevel;
}

export interface ToolSearchFilters {
  name?: string;
  category?: ToolCategory;
  capability?: ToolCapability;
  risk_level?: ToolRiskLevel;
  organization_id?: string;
  agent_id?: string;
  workflow_id?: string;
  tags?: string[];
  provider?: string;
  status?: ToolLifecycleStatus;
  trust_level?: ToolTrustLevel;
}

export interface ToolResolverResult {
  tools: ToolDefinition[];
  filtered_count: number;
  policy_applied: boolean;
}

export interface ToolAdapter {
  readonly adapter_id: string;
  readonly supported_tool_types: string[];
  validate(
    tool_definition: ToolDefinition,
    input: Record<string, unknown>,
  ): Promise<ValidationResult>;
  execute(
    context: ToolExecutionContext,
    input: Record<string, unknown>,
  ): Promise<ToolResult>;
  cancel?(execution_id: string): Promise<void>;
  health_check?(tool_id: string): Promise<HealthCheckResult>;
  get_schema?(tool_id: string): Promise<JSONSchema>;
}

export interface ValidationResult {
  valid: boolean;
  errors: ValidationError[];
}

export interface ValidationError {
  field: string;
  message: string;
  code: string;
}

export interface HealthCheckResult {
  status: "HEALTHY" | "DEGRADED" | "UNAVAILABLE";
  latency_ms: number;
  details?: Record<string, unknown>;
}

export interface ToolExecutionEvent {
  type: ToolEventType;
  timestamp: Date;
  execution_id: string;
  tool_id: string;
  tool_version: string;
  organization_id: string;
  payload: Record<string, unknown>;
}

export type ToolEventType =
  | "TOOL_RESOLVED"
  | "TOOL_AUTHORIZED"
  | "TOOL_STARTED"
  | "TOOL_PROGRESS"
  | "TOOL_COMPLETED"
  | "TOOL_FAILED"
  | "TOOL_RETRIED"
  | "TOOL_CANCELLED"
  | "TOOL_TIMEOUT"
  | "TOOL_BLOCKED"
  | "APPROVAL_REQUIRED";

export interface ToolRateLimitConfig {
  requests_per_minute: number;
  concurrent_executions: number;
  daily_execution_limit: number;
  organization_quota?: number;
  agent_quota?: number;
  user_quota?: number;
}

export interface ToolResourceLimits {
  execution_timeout_ms: number;
  memory_limit_mb: number;
  output_size_limit_bytes: number;
  input_size_limit_bytes: number;
  max_network_requests: number;
  max_subprocesses: number;
  max_concurrency: number;
}
