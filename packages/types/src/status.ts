export type BaseStatus =
  | 'pending'
  | 'running'
  | 'completed'
  | 'failed'
  | 'cancelled';

export type AgentStatus = BaseStatus | 'idle' | 'waiting_for_input';
export type WorkflowStatus = BaseStatus | 'paused';
export type ExecutionStatus = BaseStatus;
export type JobStatus = BaseStatus | 'queued' | 'retrying';
export type ToolStatus = 'available' | 'unavailable' | 'deprecated';
export type HealthStatus = 'healthy' | 'degraded' | 'unhealthy';

export const TERMINAL_STATUSES: readonly BaseStatus[] = [
  'completed',
  'failed',
  'cancelled',
] as const;

export function isTerminalStatus(status: BaseStatus): boolean {
  return TERMINAL_STATUSES.includes(status);
}

export function canTransition(from: BaseStatus, to: BaseStatus): boolean {
  const transitions: Record<BaseStatus, readonly BaseStatus[]> = {
    pending: ['running', 'cancelled'],
    running: ['completed', 'failed', 'cancelled'],
    completed: [],
    failed: ['pending'],
    cancelled: ['pending'],
  };
  return transitions[from]?.includes(to) ?? false;
}