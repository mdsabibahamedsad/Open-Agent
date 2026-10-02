// Workflow definition contract (v1) — mirrors the backend
// `openagent.services.workflow_definition` validator and the versioned
// `definition` JSON stored on workflow versions.

export const SCHEMA_VERSION = '1.0' as const;

export type TriggerType = 'manual' | 'webhook' | 'schedule' | 'event';

export type WorkflowNodeType =
  | 'agent'
  | 'prompt'
  | 'condition'
  | 'switch'
  | 'merge'
  | 'loop'
  | 'set'
  | 'transform'
  | 'filter'
  | 'map'
  | 'variable'
  | 'approval'
  | 'webhook'
  | 'tool'
  | 'connector_action'
  | 'connector_trigger'
  | 'connector_search'
  | 'connector_resource'
  | 'delay'
  | 'subworkflow'
  | 'code_agent'
  | 'code_search'
  | 'code_read'
  | 'code_patch'
  | 'code_test'
  | 'code_lint'
  | 'code_review'
  | 'git_commit'
  | 'create_pr'
  | 'verify'
  | 'evaluate'
  | 'assert'
  | 'quality_gate'
  | 'retry'
  | 'correct';

export type EdgeWhen = 'always' | 'success' | 'failure';

export type VariableType = 'string' | 'number' | 'boolean' | 'json';

export type WorkflowStatus = 'draft' | 'active' | 'archived' | 'deprecated';

export interface Position {
  x: number;
  y: number;
}

export interface WorkflowTrigger {
  id: string;
  type: TriggerType;
  name: string;
  config: Record<string, unknown>;
  /** Canvas-only layout hint; ignored by the backend validator. */
  position?: Position;
}

export interface RetryPolicy {
  max_attempts: number;
}

export interface WorkflowNode {
  id: string;
  type: WorkflowNodeType;
  /** Registry version of the node definition (migration foundation). */
  type_version?: number;
  name: string;
  position?: Position;
  config: Record<string, unknown>;
  retry_policy?: RetryPolicy;
  timeout_seconds?: number;
  approval_required?: boolean;
  /** Excluded from validation errors and future execution when true. */
  disabled?: boolean;
  /** Free-form author note (metadata, never executed). */
  notes?: string;
  /** Grouping foundation (future canvas groups). */
  group_id?: string;
}

export interface EdgeCondition {
  when: EdgeWhen;
  expression?: string;
}

export interface WorkflowEdge {
  id: string;
  from: string;
  to: string;
  label?: string;
  condition?: EdgeCondition;
}

export interface WorkflowVariable {
  name: string;
  type: VariableType;
  default?: unknown;
  required?: boolean;
  description?: string;
}

export interface WorkflowSettings {
  timezone?: string;
  max_concurrency?: number;
}

export interface WorkflowDefinition {
  schema_version: string;
  triggers: WorkflowTrigger[];
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  variables: WorkflowVariable[];
  settings: WorkflowSettings;
}

/** Clipboard payload for copy/paste/duplicate (sensitive values stripped). */
export interface Clipboard {
  triggers: WorkflowTrigger[];
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
}

export interface ValidationIssue {
  code: string;
  message: string;
  severity: 'error' | 'warning';
  node_id?: string;
  field?: string;
  edge_id?: string;
}

export interface ValidationResult {
  valid: boolean;
  errors: ValidationIssue[];
  warnings: ValidationIssue[];
}

// API shapes ---------------------------------------------------------------

export interface WorkflowRecord {
  id: string;
  organization_id: string;
  name: string;
  slug: string;
  description?: string | null;
  tags?: string[];
  status: WorkflowStatus;
  metadata: Record<string, unknown>;
  version_count: number;
  created_at: string;
  updated_at: string;
}

export interface WorkflowVersionRecord {
  id: string;
  workflow_id: string;
  version: string;
  definition: WorkflowDefinition;
  status: string;
  created_by?: string | null;
  created_at: string;
}

export interface WorkflowExecutionRecord {
  id: string;
  organization_id: string;
  workflow_id: string;
  workflow_version_id?: string | null;
  status: string;
  trigger_type: string;
  started_at?: string | null;
  completed_at?: string | null;
  error_code?: string | null;
  error_message?: string | null;
  created_at: string;
}

export interface WorkflowDetail extends WorkflowRecord {
  latest_version?: WorkflowVersionRecord | null;
  last_execution?: {
    id: string;
    status: string;
    trigger_type: string;
    started_at?: string | null;
    completed_at?: string | null;
  } | null;
}

export function emptyDefinition(): WorkflowDefinition {
  return {
    schema_version: SCHEMA_VERSION,
    triggers: [],
    nodes: [],
    edges: [],
    variables: [],
    settings: {},
  };
}
