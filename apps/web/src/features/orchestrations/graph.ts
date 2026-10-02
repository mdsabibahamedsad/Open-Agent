'use client';

import type { OrchestrationTask } from './types';

export const TASK_STATUS_COLORS: Record<string, string> = {
  created: '#94a3b8',
  ready: '#60a5fa',
  assigned: '#818cf8',
  running: '#f59e0b',
  waiting: '#a78bfa',
  paused: '#64748b',
  succeeded: '#22c55e',
  failed: '#ef4444',
  skipped: '#6b7280',
  cancelled: '#6b7280',
  timed_out: '#f97316',
};

export function statusColor(status: string): string {
  return TASK_STATUS_COLORS[status] ?? '#94a3b8';
}

export function groupByDepth(tasks: OrchestrationTask[]): Array<[number, OrchestrationTask[]]> {
  const byDepth = new Map<number, OrchestrationTask[]>();
  for (const t of tasks) {
    const d = t.depth || 1;
    if (!byDepth.has(d)) byDepth.set(d, []);
    byDepth.get(d)!.push(t);
  }
  return [...byDepth.entries()].sort((a, b) => a[0] - b[0]);
}

export function progress(tasks: OrchestrationTask[]): { succeeded: number; total: number } {
  return {
    succeeded: tasks.filter((t) => t.status === 'succeeded').length,
    total: tasks.length,
  };
}
