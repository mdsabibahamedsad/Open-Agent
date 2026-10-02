'use client';

export interface ConnectorSummary {
  id: string;
  name: string;
  version: string;
  category: string;
  type: string;
  trust: string;
  description: string;
  publisher: string;
  status: string;
  capabilities: number;
  actions: number;
  triggers: number;
}

export interface ConnectorAction {
  id: string;
  name: string;
  description: string;
  input_schema: Record<string, unknown>;
  output_schema: Record<string, unknown>;
  required_capabilities: string[];
  risk_level: string;
  supports_idempotency: boolean;
  timeout_seconds: number;
  mutation: boolean;
  verification: Record<string, unknown>;
}

export interface ConnectionRecord {
  id: string;
  organization_id: string;
  connector_id: string;
  connector_version: string;
  name: string;
  status: string;
  scope: string;
  sharing_policy: string;
  owner_user_id: string | null;
  credential_id: string | null;
  granted_capabilities: string[];
  policy_config: Record<string, unknown>;
  health: Record<string, unknown>;
  last_used_at: string | null;
  last_error: string;
  created_at: string | null;
}

export interface CredentialRecord {
  id: string;
  name: string;
  provider: string;
  credential_type: string;
  status: string;
  masked: boolean;
  expires_at: string | null;
  created_at: string | null;
}

export interface WebhookRecord {
  id: string;
  connection_id: string;
  connector_id: string;
  endpoint: string;
  event_types: string[];
  verify_mode: string;
  secret_prefix: string;
  is_active: boolean;
  failure_count: number;
  last_delivery_at: string | null;
  last_signature_ok: boolean | null;
}

export function trustTone(trust: string | null | undefined): string {
  switch ((trust ?? '').toUpperCase()) {
    case 'CORE':
      return 'bg-violet-500/10 text-violet-600 dark:text-violet-400 border-violet-500/20';
    case 'VERIFIED':
      return 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/20';
    case 'ORGANIZATION':
    case 'CUSTOM':
      return 'bg-blue-500/10 text-blue-600 dark:text-blue-400 border-blue-500/20';
    default:
      return 'bg-slate-500/10 text-slate-600 dark:text-slate-400 border-slate-500/20';
  }
}

export function riskTone(risk: string | null | undefined): string {
  switch ((risk ?? '').toUpperCase()) {
    case 'CRITICAL':
      return 'bg-red-500/10 text-red-600 dark:text-red-400 border-red-500/20';
    case 'HIGH':
      return 'bg-orange-500/10 text-orange-600 dark:text-orange-400 border-orange-500/20';
    case 'MEDIUM':
      return 'bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/20';
    default:
      return 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/20';
  }
}
