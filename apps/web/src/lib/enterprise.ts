// MP27: Enterprise security API client.
import { api } from '@/lib/api';

export interface SsoConfig {
  id: string; type: string; name: string; issuer: string;
  status: string; enforce_mfa: boolean;
}

export interface GroupMappingRow {
  id: string; group: string; team: string; role: string;
  sensitive: boolean;
}

export interface SecurityPolicyRow {
  id: string; scope: string; version: number; sections: string[];
}

export interface SecurityControlRow {
  control: string; name: string; category: string; status: string;
  owner: string; evidence: number; mappings: Record<string, string[]>;
}

export async function fetchSsoConfigs(): Promise<{ configurations: SsoConfig[] }> {
  return api.get(`/enterprise/sso`);
}

export async function createSsoConfig(body: Record<string, unknown>): Promise<{ id: string; status: string }> {
  return api.post(`/enterprise/sso`, body);
}

export async function testSsoConfig(id: string, email: string, groups: string[]): Promise<{ email: string; proposed_role: string; proposed_teams: string[]; warnings: string[]; applied: boolean }> {
  return api.post(`/enterprise/sso/${id}/test`, { email, groups });
}

export async function enableSsoConfig(id: string): Promise<{ id: string; status: string }> {
  return api.post(`/enterprise/sso/${id}/enable`, {});
}

export async function disableSsoConfig(id: string): Promise<{ id: string; status: string }> {
  return api.post(`/enterprise/sso/${id}/disable`, {});
}

export async function claimDomain(domain: string, method = 'dns_txt'): Promise<{ domain: string; challenge: string; dns_txt: string }> {
  return api.post(`/enterprise/sso/domains/claim`, { domain, method });
}

export async function verifyDomain(domain: string, presented: string): Promise<{ domain: string; status: string }> {
  return api.post(`/enterprise/sso/domains/verify`, { domain, presented });
}

export async function fetchGroupMappings(): Promise<{ mappings: GroupMappingRow[] }> {
  return api.get(`/enterprise/sso/mappings`);
}

export async function upsertGroupMapping(body: { external_group: string; role: string }): Promise<{ group: string; role: string; warning: string }> {
  return api.post(`/enterprise/sso/mappings`, body);
}

export async function fetchMfaStatus(): Promise<{ mfa_enabled: boolean }> {
  return api.get(`/enterprise/mfa/status`);
}

export async function enrollTotp(): Promise<{ secret: string; uri: string; note: string }> {
  return api.post(`/enterprise/mfa/totp/enroll`, {});
}

export async function mintRecoveryCodes(): Promise<{ codes: string[]; warning: string }> {
  return api.post(`/enterprise/mfa/recovery-codes`, {});
}

export async function fetchDevices(): Promise<{ devices: { id: string; key: string; platform: string; trust: string; last_seen: string | null }[] }> {
  return api.get(`/enterprise/devices`);
}

export async function revokeDevice(id: string): Promise<{ id: string; trust: string }> {
  return api.post(`/enterprise/devices/${id}/revoke`, {});
}

export async function evaluateStepUp(action: string, haveStrength = 'AAL1', riskLevel = 'LOW'): Promise<{ verdict: string; required_strength: string; reason: string }> {
  return api.post(`/enterprise/sessions/step-up`, { action, have_strength: haveStrength, risk_level: riskLevel });
}

export async function fetchSecurityPolicies(): Promise<{ policies: SecurityPolicyRow[] }> {
  return api.get(`/enterprise/policies`);
}

export async function simulatePolicy(body: { policy_id: string; actor: string; action: string; resource?: string; environment?: string; context?: Record<string, unknown> }): Promise<{ verdict: string; explanation: string; required_strength: string }> {
  return api.post(`/enterprise/policies/simulate`, body);
}

export async function fetchSecurityControls(): Promise<{ controls: SecurityControlRow[] }> {
  return api.get(`/enterprise/controls`);
}

export async function fetchPosture(): Promise<{ MFA: string; SSO: string; SCIM: string; Audit: string; 'IP Restrictions': string; 'Open Issues': string[] }> {
  return api.get(`/enterprise/posture`);
}

export async function fetchSecurityAnalytics(): Promise<{ failed_authentications: number; policy_denials: number }> {
  return api.get(`/enterprise/analytics`);
}

export async function fetchScimCredentials(): Promise<{ credentials: { id: string; name: string; prefix: string; expires: string; revoked: boolean }[] }> {
  return api.get(`/enterprise/scim/credentials`);
}

export async function mintScimCredential(name: string): Promise<{ id: string; token: string; endpoint: string; warning: string }> {
  return api.post(`/enterprise/scim/credentials`, { name });
}
