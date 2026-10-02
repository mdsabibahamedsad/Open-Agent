// MP25: Cloud Control Center API client.
// Org context travels via X-Organization-ID from localStorage (see lib/api).
import { api } from '@/lib/api';

export interface CloudOverview {
  status: string;
  components: Record<string, string>;
  incident_mode: string;
  runtime_mode: string;
  workers: { workers: number; busy: number; ready: number; utilization: number };
}

export interface CloudWorker {
  worker: string;
  region: string;
  pool: string;
  status: string;
  capacity: number;
  active: number;
  version: string;
  heartbeat: string | null;
}

export interface CloudQueue {
  queue: string;
  depth: number;
  oldest_job_age_s: number;
  processing: number;
  failed: number;
  paused: boolean;
}

export interface CloudRegion {
  region: string;
  name: string;
  health: string;
  capabilities: string[];
  private: boolean;
}

export interface CloudEvent {
  sequence: number;
  type: string;
  payload: Record<string, unknown>;
  timestamp: string;
}

export async function fetchCloudHealth(): Promise<CloudOverview> {
  return api.get<CloudOverview>(`/cloud/health`);
}

export async function fetchCloudWorkers(opts?: { region?: string; pool?: string }): Promise<{ workers: CloudWorker[] }> {
  return api.get(`/cloud/workers`, { region: opts?.region, pool: opts?.pool });
}

export async function fetchCloudQueues(): Promise<{ queues: CloudQueue[] }> {
  return api.get(`/cloud/queues`);
}

export async function fetchCloudRegions(): Promise<{ regions: CloudRegion[] }> {
  return api.get(`/cloud/regions`);
}

export async function fetchCloudStorage(): Promise<{ usage_bytes: number; artifact_count: number; largest: { id: string; name: string; size: number; category: string }[] }> {
  return api.get(`/cloud/storage`);
}

export async function fetchCloudUsage(): Promise<{ usage: Record<string, number> }> {
  return api.get(`/cloud/usage`);
}

export async function fetchExecutionEvents(executionId: string, fromSequence = 0): Promise<{ execution_id: string; events: CloudEvent[] }> {
  return api.get(`/cloud/executions/${executionId}/events`, { from_sequence: fromSequence });
}

export async function submitCloudExecution(body: Record<string, unknown>, idempotencyKey?: string): Promise<{ execution_id: string; status: string; region: string; queue: string }> {
  return api.post(`/cloud/executions`, body, { idempotencyKey });
}

export async function cancelCloudExecution(executionId: string): Promise<{ execution_id: string; status: string }> {
  return api.post(`/cloud/executions/${executionId}/cancel`, {});
}

export async function retryCloudExecution(executionId: string): Promise<{ execution_id: string; status: string }> {
  return api.post(`/cloud/executions/${executionId}/retry`, {});
}

export async function drainCloudWorker(workerId: string): Promise<{ worker: string; status: string }> {
  return api.post(`/cloud/workers/${workerId}/drain`, {});
}

export async function fetchOrgCloudSettings(): Promise<{ residency: string; allowed_regions: string[]; pool: string; max_concurrent: number; artifact_retention_s: number; webhook_per_minute: number }> {
  return api.get(`/cloud/settings`);
}

export async function saveOrgCloudSettings(body: Record<string, unknown>): Promise<{ ok: boolean }> {
  return api.put(`/cloud/settings`, body);
}
