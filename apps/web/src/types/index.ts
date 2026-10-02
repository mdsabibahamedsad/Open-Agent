// Shared domain types for the web app.

export interface Organization {
  id: string;
  name: string;
  slug: string;
  description?: string | null;
  avatar_url?: string | null;
  status: string;
  role?: string | null;
  member_count?: number;
}

export interface Membership {
  id: string;
  organization_id: string;
  user_id: string;
  role: string;
  status: string;
}

export interface Paginated<T> {
  data: T[];
  meta: { page: number; page_size: number; total: number; total_pages: number };
}

export interface AgentSummary {
  id: string;
  name: string;
  status: string;
  model?: string;
  updated_at?: string;
}

export interface WorkflowSummary {
  id: string;
  name: string;
  status: string;
  updated_at?: string;
  last_run_at?: string | null;
}

export interface RunSummary {
  id: string;
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled' | string;
  workflow_name?: string;
  workflow_id?: string;
  started_at?: string;
  finished_at?: string | null;
}

export interface ExecutionDetail {
  id: string;
  organization_id: string;
  workflow_id: string;
  workflow_version_id?: string | null;
  workflow_name?: string | null;
  status: string;
  trigger_type: string;
  input?: Record<string, unknown>;
  output?: Record<string, unknown>;
  started_at?: string | null;
  completed_at?: string | null;
  error_code?: string | null;
  error_message?: string | null;
  created_at: string;
  metadata?: Record<string, unknown>;
  tags?: string[];
}

export type PermissionString = `${string}:${string}`;

export interface FeatureFlags {
  agent_runtime: boolean;
  workflow_builder: boolean;
  marketplace: boolean;
  browser_agent: boolean;
  coding_agent: boolean;
  mcp: boolean;
  cloud: boolean;
  billing: boolean;
  enterprise: boolean;
  advanced_workflow_groups: boolean;
  workflow_collaboration: boolean;
  workflow_templates: boolean;
  custom_nodes: boolean;
}
