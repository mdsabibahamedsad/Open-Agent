// Typed client for the Code Agent + Repository Workspace API.
// Policy-aware: credentials stay server-side as `credential_ref` handles;
// host filesystem paths are never returned by the API.

import { api } from './api';

export interface Repository {
  id: string;
  organization_id: string;
  provider: string;
  external_id?: string | null;
  name: string;
  full_name: string;
  default_branch: string;
  visibility: string;
  status: string;
  has_credential: boolean;
}

export interface CodeWorkspace {
  id: string;
  workspace_id: string;
  organization_id: string;
  repository_id: string;
  branch: string;
  base_revision?: string | null;
  current_revision?: string | null;
  status: string;
  dirty?: boolean | null;
}

export interface CodingTask {
  id: string;
  task_id: string;
  organization_id: string;
  repository_id: string;
  workspace_id?: string | null;
  objective: string;
  branch?: string | null;
  status: string;
  risk_level: string;
  current_step: number;
  max_steps: number;
}

export interface TaskEvent {
  id: string;
  event_id: string;
  type: string;
  payload: unknown;
  timestamp: string;
}

export interface PlanStep {
  step: number;
  title: string;
  detail?: string;
}

export interface TaskPlan {
  objective: string;
  risk_level: string;
  max_steps: number;
  steps: PlanStep[];
  budgets?: Record<string, unknown>;
}

export type SearchMode = 'text' | 'regex' | 'symbol' | 'references' | 'semantic';

export const codeApi = {
  // Repositories
  listRepositories: () => api.get<Repository[]>('/repositories'),
  createRepository: (body: {
    provider: 'local' | 'generic' | 'github' | 'gitlab' | 'bitbucket';
    name: string;
    full_name: string;
    clone_url: string;
    default_branch?: string;
    visibility?: 'private' | 'public' | 'internal';
    credential_ref?: string;
    provider_config?: Record<string, unknown>;
    external_id?: string;
  }) => api.post<Repository>('/repositories', body),
  getRepository: (id: string) => api.get<Repository>(`/repositories/${id}`),
  connectRepository: (id: string) => api.post<{ status: string }>(`/repositories/${id}/connect`),
  syncRepository: (id: string) => api.post<{ status: string }>(`/repositories/${id}/sync`),
  deleteRepository: (id: string) => api.delete(`/repositories/${id}`),

  // Workspaces
  listWorkspaces: (status?: string) =>
    api.get<CodeWorkspace[]>('/code/workspaces', status ? { status } : undefined),
  createWorkspace: (body: { repository_id: string; task_id?: string; branch?: string }) =>
    api.post<CodeWorkspace>('/code/workspaces', body),
  getWorkspace: (id: string) => api.get<CodeWorkspace>(`/code/workspaces/${id}`),
  workspaceStatus: (id: string) =>
    api.get<{ status: string; dirty: boolean; branch: string; change_count: number }>(
      `/code/workspaces/${id}/status`,
    ),
  deleteWorkspace: (id: string, force = false) =>
    api.delete(`/code/workspaces/${id}`, { params: force ? { force: true } : undefined }),
  createBranch: (workspaceId: string, name: string) =>
    api.post<{ branch: string }>(`/code/workspaces/${workspaceId}/branches`, { name }),
  listFiles: (workspaceId: string, prefix = '') =>
    api.get<{ files: Array<{ path: string; size: number; language?: string }> }>(
      `/code/workspaces/${workspaceId}/files`,
      prefix ? { prefix } : undefined,
    ),
  readFile: (workspaceId: string, path: string, start?: number, end?: number) =>
    api.get<{ path: string; content: string; truncated: boolean }>(
      `/code/workspaces/${workspaceId}/files/read`,
      { path, ...(start !== undefined ? { start } : {}), ...(end !== undefined ? { end } : {}) },
    ),

  // Coding tasks
  listTasks: (params?: { status?: string; repository_id?: string }) =>
    api.get<CodingTask[]>('/code/tasks', params as Record<string, string> | undefined),
  createTask: (body: {
    repository_id: string;
    objective: string;
    branch?: string;
    max_steps?: number;
    max_duration_seconds?: number;
    risk_level?: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
    budgets?: Record<string, unknown>;
  }) => api.post<CodingTask>('/code/tasks', body),
  getTask: (id: string) => api.get<CodingTask>(`/code/tasks/${id}`),
  cancelTask: (id: string) => api.post(`/code/tasks/${id}/cancel`),
  pauseTask: (id: string) => api.post(`/code/tasks/${id}/pause`),
  resumeTask: (id: string) => api.post(`/code/tasks/${id}/resume`),
  taskPlan: (id: string) => api.get<TaskPlan>(`/code/tasks/${id}/plan`),
  taskDiff: (id: string) =>
    api.get<{ diff?: string; files?: Array<{ path: string; additions: number; deletions: number }> }>(
      `/code/tasks/${id}/diff`,
    ),
  taskEvents: (id: string) => api.get<TaskEvent[]>(`/code/tasks/${id}/events`),
  taskArtifacts: (id: string) => api.get<{ artifacts: Array<{ name: string; uri: string }> }>(
    `/code/tasks/${id}/artifacts`,
  ),
  applyPatch: (taskId: string, body: { diff: string; approved?: boolean }) =>
    api.post<{ applied: boolean; files?: string[] }>(`/code/tasks/${taskId}/patch`, body),
  commitTask: (taskId: string, message: string) =>
    api.post<{ revision?: string }>(`/code/tasks/${taskId}/commit`, { message }),
  pushTask: (taskId: string, body: { approved?: boolean; force?: boolean }) =>
    api.post<{ pushed: boolean }>(`/code/tasks/${taskId}/push`, body),
  planTests: (taskId: string) =>
    api.post<{ targeted: string[]; regression: string[] }>(`/code/tasks/${taskId}/tests/plan`, {}),

  // Search / review / execute / PR
  search: (body: {
    workspace_id: string;
    query: string;
    mode?: SearchMode;
    symbol?: string;
    top_k?: number;
  }) =>
    api.post<{ results: Array<{ path: string; line?: number; snippet?: string; score?: number }> }>(
      '/code/search',
      body,
    ),
  review: (body: { task_id?: string; filename?: string; content?: string }) =>
    api.post<{
      status: string;
      findings: Array<{
        severity: string;
        file?: string;
        line?: number;
        category: string;
        finding: string;
        suggested_fix?: string;
      }>;
    }>('/code/review', body),
  execute: (body: {
    workspace_id?: string;
    task_id?: string;
    profile?: 'TEST' | 'LINT' | 'TYPECHECK' | 'BUILD' | 'PACKAGE' | 'MIGRATION' | 'CUSTOM';
    command: string;
  }) =>
    api.post<{
      status: string;
      exit_code: number;
      duration_ms: number;
      passed?: number;
      failed?: number;
      output_ref?: string;
    }>('/code/execute', body),
  preparePR: (body: { task_id: string; title: string; summary?: string; open?: boolean }) =>
    api.post<{ id: string; title: string; status: string }>('/code/pr', body),
};
