'use client';

export interface ApprovalRecord {
  id: string;
  organization_id: string;
  status: string;
  approval_type: string;
  action_type: string | null;
  action_category: string | null;
  action_description: string | null;
  risk_level: string | null;
  risk_score: number | null;
  risk_reasons: string[];
  policy_decision: string | null;
  policy_version: string | null;
  approval_kind: string;
  required_approvals: number;
  required_role: string | null;
  target_type: string | null;
  target_id: string | null;
  target_reference: string | null;
  requested_parameters: Record<string, unknown>;
  impact_summary: string;
  requester_type: string | null;
  requester_id: string | null;
  agent_id: string | null;
  agent_run_id: string | null;
  workflow_id: string | null;
  workflow_execution_id: string | null;
  task_id: string | null;
  approved_by: string | null;
  approval_reason: string | null;
  rejection_reason: string | null;
  escalation_chain: Array<{ by: string | null; to: string; reason: string; at: string }>;
  use_count: number;
  max_uses: number;
  requested_at: string | null;
  expires_at: string | null;
  resolved_at: string | null;
  audit_timeline?: Array<{
    type: string;
    at: string | null;
    actor_type: string | null;
    actor_id: string | null;
    data: Record<string, unknown>;
  }>;
}

export interface ApprovalPolicyRecord {
  id: string;
  name: string;
  level: string;
  rules: Array<Record<string, unknown>>;
  is_active: boolean;
  version: number;
}

export function riskTone(risk: string | null | undefined): string {
  switch ((risk ?? '').toUpperCase()) {
    case 'CRITICAL':
      return 'bg-red-500/10 text-red-600 dark:text-red-400 border-red-500/20';
    case 'HIGH':
      return 'bg-orange-500/10 text-orange-600 dark:text-orange-400 border-orange-500/20';
    case 'MEDIUM':
      return 'bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/20';
    case 'LOW':
      return 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/20';
    default:
      return 'bg-secondary text-secondary-foreground border-border';
  }
}

export function isDangerous(a: ApprovalRecord): boolean {
  const cat = (a.action_category ?? '').toUpperCase();
  const risk = (a.risk_level ?? '').toUpperCase();
  return risk === 'CRITICAL' || risk === 'HIGH' || ['DELETE', 'DEPLOY', 'FINANCIAL_ACTION'].includes(cat);
}
