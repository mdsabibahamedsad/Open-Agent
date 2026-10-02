// Typed client for the Browser Engine API (policy-aware; no secrets client-side).
import { api } from './api';

export interface BrowserSession {
  id: string;
  session_id: string;
  organization_id: string;
  status: string;
  provider: string;
  headless: boolean;
  created_at: string;
  last_activity_at: string;
  expires_at: string;
}

export interface BrowserPage {
  id: string;
  page_id: string;
  url: string;
  title?: string | null;
  status: string;
  is_popup: boolean;
}

export interface BrowserTask {
  id: string;
  task_id: string;
  status: string;
  objective: string;
  current_url?: string | null;
  current_step: number;
  max_steps: number;
}

export interface BrowserProfile {
  id: string;
  display_name: string;
  browser_type: string;
  profile_type: string;
}

export interface DomainPolicy {
  id: string;
  domain: string;
  action: 'ALLOW' | 'DENY' | 'CONFIRM';
  priority: number;
  reason?: string | null;
}

export const browserApi = {
  // Sessions
  listSessions: () => api.get<BrowserSession[]>('/browser/sessions'),
  createSession: (body: { headless?: boolean; browser_profile_id?: string }) =>
    api.post<BrowserSession>('/browser/sessions', body),
  getSession: (id: string) => api.get<BrowserSession>(`/browser/sessions/${id}`),
  pauseSession: (id: string) => api.post(`/browser/sessions/${id}/pause`),
  resumeSession: (id: string) => api.post(`/browser/sessions/${id}/resume`),
  closeSession: (id: string) => api.delete(`/browser/sessions/${id}`),
  sessionEvents: (id: string) => api.get<Array<{ type: string; payload: unknown; timestamp: string }>>(`/browser/sessions/${id}/events`),

  // Pages
  listPages: (sessionId: string) => api.get<BrowserPage[]>(`/browser/sessions/${sessionId}/pages`),
  createPage: (sessionId: string, body: { url?: string }) =>
    api.post<BrowserPage>(`/browser/sessions/${sessionId}/pages`, body),

  // Tasks
  listTasks: () => api.get<BrowserTask[]>('/browser/tasks'),
  createTask: (body: { browser_session_id: string; objective: string; max_steps?: number }) =>
    api.post<BrowserTask>('/browser/tasks', body),
  getTask: (id: string) => api.get<BrowserTask>(`/browser/tasks/${id}`),
  cancelTask: (id: string) => api.post(`/browser/tasks/${id}/cancel`),
  pauseTask: (id: string) => api.post(`/browser/tasks/${id}/pause`),
  resumeTask: (id: string) => api.post(`/browser/tasks/${id}/resume`),
  requestHuman: (id: string, reason: string) =>
    api.post(`/browser/tasks/${id}/human`, null, { params: { reason } }),
  runAction: (taskId: string, body: { action_type: string; page_id: string; input: Record<string, unknown>; approved?: boolean }) =>
    api.post(`/browser/tasks/${taskId}/actions`, body),

  // Profiles & policies
  listProfiles: () => api.get<BrowserProfile[]>('/browser/profiles'),
  createProfile: (body: { display_name: string; profile_type?: string }) =>
    api.post<BrowserProfile>('/browser/profiles', body),
  listPolicies: () => api.get<DomainPolicy[]>('/browser/policies'),
  createPolicy: (body: { domain: string; action: string; priority?: number; reason?: string }) =>
    api.post<DomainPolicy>('/browser/policies', body),
};
