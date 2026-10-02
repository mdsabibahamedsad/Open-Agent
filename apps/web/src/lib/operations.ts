// MP26: Operations + platform API client (org ops + master control).
import { api } from '@/lib/api';

export interface OpsHealth {
  status: string;
  components: Record<string, string>;
  public: string;
  checked_at: string;
  maintenance: { id: string; title: string; starts: string; ends: string }[];
}

export interface OpsAlert {
  id: string; severity: string; source: string; condition: string;
  observed: number; threshold: number; status: string; created: string;
}

export interface OpsIncident {
  id: string; title: string; severity: string; status: string; created: string;
}

export interface OpsDeployment {
  id: string; service: string; version: string; commit: string;
  environment: string; status: string; deployed: string | null;
}

export async function fetchOpsHealth(): Promise<OpsHealth> {
  return api.get<OpsHealth>(`/operations/health`);
}

export async function fetchOpsMetrics(): Promise<{ metrics: unknown; catalog: string[] }> {
  return api.get(`/operations/metrics`);
}

export async function fetchOpsSlos(): Promise<{ slos: { slo: string; target: number; value: number | null; met: boolean | null; error_budget: unknown }[] }> {
  return api.get(`/operations/slos`);
}

export async function fetchOpsAlerts(params?: { status?: string; severity?: string }): Promise<{ alerts: OpsAlert[] }> {
  return api.get(`/operations/alerts`, { ...params });
}

export async function ackOpsAlert(id: string): Promise<{ id: string; status: string }> {
  return api.post(`/operations/alerts/${id}/ack`, {});
}

export async function createAlertRule(body: Record<string, unknown>): Promise<{ id: string; name: string }> {
  return api.post(`/operations/alerts/rules`, body);
}

export async function fetchOpsIncidents(params?: { status?: string }): Promise<{ incidents: OpsIncident[] }> {
  return api.get(`/operations/incidents`, { ...params });
}

export async function openOpsIncident(body: { title: string; severity?: string }): Promise<{ id: string; status: string }> {
  return api.post(`/operations/incidents`, body);
}

export async function fetchIncidentDetail(id: string): Promise<{ id: string; title: string; status: string; severity: string; timeline: { at: string; actor: string; message: string }[] } & Record<string, unknown>> {
  return api.get(`/operations/incidents/${id}`);
}

export async function transitionIncident(id: string, toStatus: string, note = ''): Promise<{ id: string; status: string }> {
  return api.post(`/operations/incidents/${id}/transition`, { to_status: toStatus, note });
}

export async function fetchOpsDeployments(): Promise<{ deployments: OpsDeployment[] }> {
  return api.get(`/operations/deployments`);
}

export async function fetchOrgAudit(params?: { action?: string; resource?: string }): Promise<{ audit: { id: string; action: string; resource: string; created: string }[] }> {
  return api.get(`/operations/audit`, { ...params });
}

export async function fetchSecurityEvents(): Promise<{ events: { id: string; type: string; created: string }[] }> {
  return api.get(`/operations/security-events`);
}

export async function fetchOpsQuotas(): Promise<{ quotas: { dimension: string; limit: number; used: number; remaining: number }[] }> {
  return api.get(`/operations/quotas`);
}

export async function fetchRateLimits(): Promise<{ limits: Record<string, { limit: number; used: number; remaining: number; reset: string }> }> {
  return api.get(`/operations/rate-limits`);
}

export async function fetchDiagnostics(): Promise<{ diagnostics: { component: string; ok: boolean; message: string; action: string }[]; failed: string[]; healthy: boolean }> {
  return api.get(`/operations/diagnostics`);
}

export async function fetchSupportBundle(): Promise<Record<string, unknown>> {
  return api.get(`/operations/support-bundle`);
}

export async function fetchEnterpriseRetention(): Promise<{ retention_seconds: Record<string, number>; minimums?: Record<string, number>; clamped_to_minimum?: string[] }> {
  return api.get(`/enterprise/retention`);
}

export async function saveEnterpriseRetention(policy: Record<string, number>): Promise<{ retention_seconds: Record<string, number>; clamped_to_minimum: string[] }> {
  return api.put(`/enterprise/retention`, { policy });
}

export async function fetchIpPolicy(): Promise<{ enabled: boolean; allowlist: string[]; denylist: string[] }> {
  return api.get(`/enterprise/ip-policy`);
}

export async function saveIpPolicy(body: { allowlist: string[]; denylist: string[]; enabled: boolean }): Promise<{ enabled: boolean }> {
  return api.put(`/enterprise/ip-policy`, body);
}

// Master platform control (Master Account only).
export async function fetchPlatformOverview(): Promise<{ health: unknown; open_alerts: number; open_incidents: number; audit_chain: string }> {
  return api.get(`/master/control/overview`);
}

export async function fetchPlatformConfig(category = ''): Promise<{ config: { scope: string; key: string; value: unknown; version: number }[] }> {
  return api.get(`/master/control/config`, category ? { category } : undefined);
}

export async function fetchPlatformFlags(): Promise<{ flags: { key: string; scope: string; enabled: boolean; strategy: string }[] }> {
  return api.get(`/master/control/flags`);
}

export async function fetchPlatformAudit(): Promise<{ chain: string; intact: boolean; records: unknown[] }> {
  return api.get(`/master/control/audit`);
}

export async function fetchPlatformBackups(): Promise<{ backups: Record<string, { status: string; rpo_s: number | null; rto_s: number | null }> }> {
  return api.get(`/master/control/backups`);
}
