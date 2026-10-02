// Typed client for the Sandbox & Secure Execution API.
// Policy-aware: host paths and container paths are never returned;
// artifacts travel as storage refs; credentials as refs only.

import { api } from './api';

export interface Sandbox {
  id: string;
  sandbox_id: string;
  organization_id: string;
  provider: string;
  profile: string;
  status: string;
  image: string;
  pinned: boolean;
  started_at?: string | null;
  expires_at?: string | null;
  destroyed_at?: string | null;
  resource_config: Record<string, unknown>;
}

export interface SandboxExecution {
  id: string;
  execution_id: string;
  sandbox_id: string;
  command: string;
  workdir: string;
  profile: string;
  status: string;
  exit_code?: number | null;
  duration_ms?: number | null;
  timed_out: boolean;
  oom_killed: boolean;
  peak_memory_mb?: number | null;
  risk_level: string;
  risk_reasons: string[];
  policy_decision: Record<string, unknown>;
  stdout_tail?: string | null;
  stdout_ref?: string | null;
  stderr_ref?: string | null;
  artifacts: Array<{ name: string; ref: string; size_bytes?: number }>;
}

export interface SandboxProfile {
  name: string;
  description: string;
  security_level: number;
  cpu: number;
  memory_mb: number;
  disk_mb: number;
  pids_limit: number;
  timeout_seconds: number;
  network: { mode: string; allowed_domains: string[] };
  filesystem: { mode: string };
}

// --- pure display helpers (covered by vitest) ---

export function normalizeExecutionStatus(status: string): string {
  return status === 'WAITING' ? 'WAITING_FOR_APPROVAL' : status;
}

export function isTerminalExecutionStatus(status: string): boolean {
  return [
    'SUCCEEDED', 'FAILED', 'TIMED_OUT', 'CANCELLED', 'KILLED',
    'RESOURCE_LIMIT', 'POLICY_DENIED', 'SANDBOX_ERROR', 'WAITING_FOR_APPROVAL',
  ].includes(normalizeExecutionStatus(status));
}

export function riskTone(level: string): 'ok' | 'warn' | 'bad' | 'critical' {
  switch (level) {
    case 'LOW': return 'ok';
    case 'MEDIUM': return 'warn';
    case 'HIGH': return 'bad';
    default: return 'critical';
  }
}

export function formatBytes(bytes?: number | null): string {
  if (bytes === undefined || bytes === null) return '—';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatDuration(ms?: number | null): string {
  if (ms === undefined || ms === null) return '—';
  if (ms < 1000) return `${ms} ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)} s`;
  return `${(ms / 60000).toFixed(1)} min`;
}

export function decisionSummary(result: {
  status: string;
  risk_level?: string;
  policy_decision?: { network?: string; filesystem?: string; category?: string };
}): string {
  const risk = result.risk_level ?? 'UNKNOWN';
  const net = result.policy_decision?.network ?? '—';
  const fs = result.policy_decision?.filesystem ?? '—';
  if (result.status === 'POLICY_DENIED') return `DENIED · risk ${risk} · net ${net} · fs ${fs}`;
  if (result.status === 'WAITING_FOR_APPROVAL') return `PARKED FOR APPROVAL · risk ${risk}`;
  return `ALLOWED · risk ${risk} · net ${net} · fs ${fs}`;
}

export const sandboxApi = {
  // Sandboxes
  list: (status?: string) =>
    api.get<Sandbox[]>('/sandboxes', status ? { status } : undefined),
  create: (body: {
    profile?: string;
    task_id?: string;
    workspace_host_path?: string;
    workspace_mode?: 'WORKSPACE_RW' | 'WORKSPACE_RO';
    image?: string;
    image_digest?: string;
    ttl_seconds?: number;
  }) => api.post<Sandbox>('/sandboxes', body),
  get: (id: string) => api.get<Sandbox>(`/sandboxes/${id}`),
  start: (id: string) => api.post<Sandbox>(`/sandboxes/${id}/start`),
  stop: (id: string) => api.post<Sandbox>(`/sandboxes/${id}/stop`),
  destroy: (id: string) => api.delete(`/sandboxes/${id}`),
  securityCheck: () => api.get<Record<string, unknown>>('/sandboxes/security/check'),

  // Execution
  execute: (sandboxId: string, body: {
    command: string | string[];
    workdir?: string;
    env?: Record<string, string>;
    credential_refs?: Record<string, string>;
    timeout_seconds?: number;
    approved?: boolean;
    artifacts?: Array<{ path: string; name?: string }>;
  }) => api.post<SandboxExecution & { reason?: string }>(`/sandboxes/${sandboxId}/execute`, body),
  listExecutions: (sandboxId: string) =>
    api.get<SandboxExecution[]>(`/sandboxes/${sandboxId}/executions`),
  getExecution: (sandboxId: string, executionId: string) =>
    api.get<SandboxExecution>(`/sandboxes/${sandboxId}/executions/${executionId}`),
  getExecutionDirect: (executionId: string) =>
    api.get<SandboxExecution>(`/sandbox-executions/${executionId}`),
  cancelExecution: (sandboxId: string, executionId: string) =>
    api.post(`/sandboxes/${sandboxId}/executions/${executionId}/cancel`),
  events: (sandboxId: string) =>
    api.get<Array<{ id: string; event_id: string; type: string; payload: unknown }>>(
      `/sandboxes/${sandboxId}/events`,
    ),
  artifacts: (sandboxId: string) =>
    api.get<Array<{ id: string; name: string; ref: string; size_bytes?: number }>>(
      `/sandboxes/${sandboxId}/artifacts`,
    ),

  // Leases
  acquireLease: (sandboxId: string, body: { owner: string; ttl_seconds?: number }) =>
    api.post(`/sandboxes/${sandboxId}/leases`, body),

  // Profiles
  listProfiles: () => api.get<SandboxProfile[]>('/sandbox-profiles'),
  upsertProfile: (config: Record<string, unknown>) =>
    api.post('/sandbox-profiles', { config }),
};
