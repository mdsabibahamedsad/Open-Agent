'use client';

export interface ManagerProfile {
  id: string;
  organization_id: string;
  agent_id: string;
  label: string;
  status: string;
  delegation_policy: string;
  review_required: boolean;
  scope: string;
  max_workers: number;
  max_team_size: number;
  allowed_actions: string[];
  created_at: string;
}

export interface AgentContract {
  id: string;
  task_id?: string | null;
  agent_id?: string | null;
  manager_agent_id?: string | null;
  objective: string;
  responsibilities: string[];
  expected_outputs: Record<string, unknown>;
  acceptance_criteria: Array<{ description: string; verification: string; satisfied?: boolean | null }>;
  max_revisions: number;
  created_at: string;
}

export interface Delegation {
  id: string;
  task_id?: string | null;
  source_agent_id?: string | null;
  target_agent_id?: string | null;
  reason: string;
  required_capabilities: string[];
  policy: string;
  status: string;
  decision_reason?: string | null;
  created_at: string;
}

export interface Handoff {
  id: string;
  task_id: string;
  source_agent_id?: string | null;
  target_agent_id?: string | null;
  mode: string;
  package: Record<string, unknown>;
  context_manifest: {
    included_items: string[];
    excluded_items: string[];
    redacted_items: string[];
    policy: string;
  };
  status: string;
  created_at: string;
}

export interface Review {
  id: string;
  task_id: string;
  reviewer_agent_id?: string | null;
  status: string;
  issues: string[];
  required_changes: string[];
  evidence: string[];
  revision_number: number;
  gate_result?: string | null;
  created_at: string;
}

export interface Escalation {
  id: string;
  task_id?: string | null;
  source_agent_id?: string | null;
  current_holder_agent_id?: string | null;
  trigger: string;
  reason: string;
  severity: string;
  status: string;
  chain: string[];
  chain_level: number;
  recommended_action: string;
  history: Array<Record<string, unknown>>;
  created_at: string;
}

export interface DynamicTeam {
  id: string;
  name: string;
  team_type: string;
  status: string;
  manager_agent_id?: string | null;
  members?: Array<{ agent_id: string; role: string; status: string }>;
  charter?: {
    objective: string;
    scope: string;
    completion_criteria: string[];
  } | null;
  created_at: string;
}

export interface OrgChart {
  agents: Array<{ id: string; name: string; status: string }>;
  managers: Array<{ agent_id: string; label: string; scope: string }>;
  relationships: Array<{ source: string; target: string; type: string }>;
  team_memberships: Array<{ team_id: string; agent_id: string; role: string }>;
  departments: Array<{ id: string; name: string; slug: string }>;
}

export interface ManagerConsole {
  active_teams: number;
  teams: Array<{ id: string; name: string; status: string }>;
  active_tasks: number;
  blocked_tasks: number;
  failed_tasks: number;
  pending_delegations: number;
  delegations: Array<{ id: string; status: string }>;
  open_escalations: number;
  escalations: Array<{ id: string; severity: string; status: string }>;
}
