'use client';

export interface OrchestrationSummary {
  id: string;
  organization_id: string;
  objective: string;
  status: string;
  root_agent_id?: string | null;
  budget: Record<string, unknown>;
  usage: Record<string, unknown>;
  final_result?: Record<string, unknown> | null;
  error?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface OrchestrationTask {
  id: string;
  orchestration_run_id: string;
  external_task_id: string;
  title: string;
  status: string;
  priority: string;
  assigned_agent_id?: string | null;
  required_capabilities: string[];
  risk_level: string;
  output?: Record<string, unknown> | null;
  error?: string | null;
  retry_count: number;
  depth: number;
  created_at: string;
}

export interface AgentMessage {
  id: string;
  sender_agent_id?: string | null;
  recipient_agent_id?: string | null;
  task_id?: string | null;
  message_type: string;
  payload: Record<string, unknown>;
  correlation_id?: string | null;
  created_at: string;
}

export interface OrchestrationEvent {
  id: string;
  task_id?: string | null;
  agent_id?: string | null;
  event_type: string;
  payload: Record<string, unknown>;
  trace_id?: string | null;
  created_at: string;
}

export interface RunAgentGroup {
  agent_id: string;
  tasks: string[];
  status: string;
}

export const TERMINAL_RUN_STATUSES = [
  'succeeded',
  'partially_succeeded',
  'failed',
  'cancelled',
  'timed_out',
];

export const TERMINAL_TASK_STATUSES = [
  'succeeded',
  'failed',
  'skipped',
  'cancelled',
  'timed_out',
];
