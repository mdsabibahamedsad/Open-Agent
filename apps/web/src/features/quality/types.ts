'use client';

export interface EvaluationRecord {
  id: string;
  organization_id: string;
  evaluation_type: string;
  status: string;
  evaluator_type: string;
  task_id: string | null;
  agent_id: string | null;
  agent_run_id: string | null;
  workflow_id: string | null;
  workflow_execution_id: string | null;
  parent_evaluation_id: string | null;
  attempt_number: number;
  decision: string | null;
  score: number | null;
  confidence: number | null;
  failure_class: string | null;
  failure_reason: string | null;
  uncertainty_reason: string | null;
  criteria: Record<string, unknown>;
  result: Record<string, unknown>;
  input_hash: string | null;
  output_hash: string | null;
  evaluator_version: string;
  rubric_version: string | null;
  model_version: string | null;
  created_at: string | null;
  completed_at: string | null;
  evidence?: Array<{
    id: string;
    evidence_type: string;
    trust: string;
    content: Record<string, unknown>;
    source: string;
    content_hash: string;
  }>;
  checks?: Array<{ name: string; kind: string; passed: boolean; reason: string; required: boolean }>;
  votes?: Array<{ source: string; decision: string; score: number; confidence: number; reason_codes: string[] }>;
  correction_plans?: Array<{ id: string; strategy: string; status: string; failure_class: string }>;
  feedback?: Array<{ verdict: string; reason: string; at: string | null }>;
}

export interface QualityOverview {
  by_status: Record<string, number>;
  by_decision: Record<string, number>;
  open_correction_plans: number;
  disagreements_total: number;
  recent_failures: Array<{ id: string; type: string; failure_class: string | null; score: number | null }>;
}

export function decisionTone(decision: string | null | undefined): string {
  switch ((decision ?? '').toUpperCase()) {
    case 'PASS':
      return 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/20';
    case 'FAIL':
      return 'bg-red-500/10 text-red-600 dark:text-red-400 border-red-500/20';
    case 'RETRY':
    case 'CORRECT':
      return 'bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/20';
    case 'ESCALATE':
    case 'REQUEST_HUMAN':
    case 'STOP':
      return 'bg-orange-500/10 text-orange-600 dark:text-orange-400 border-orange-500/20';
    default:
      return 'bg-secondary text-secondary-foreground border-border';
  }
}

export function trustTone(trust: string | null | undefined): string {
  switch ((trust ?? '').toUpperCase()) {
    case 'SYSTEM_VERIFIED':
      return 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/20';
    case 'TOOL_VERIFIED':
    case 'EXTERNAL_VERIFIED':
      return 'bg-blue-500/10 text-blue-600 dark:text-blue-400 border-blue-500/20';
    case 'USER_CONFIRMED':
      return 'bg-violet-500/10 text-violet-600 dark:text-violet-400 border-violet-500/20';
    default:
      return 'bg-slate-500/10 text-slate-600 dark:text-slate-400 border-slate-500/20';
  }
}
