import { describe, expect, it } from 'vitest';
import { groupByDepth, progress, statusColor } from './graph';
import type { OrchestrationTask } from './types';

function task(id: string, status: string, depth = 1): OrchestrationTask {
  return {
    id,
    orchestration_run_id: 'run',
    external_task_id: id,
    title: id,
    status,
    priority: 'normal',
    assigned_agent_id: null,
    required_capabilities: [],
    risk_level: 'low',
    retry_count: 0,
    depth,
    created_at: new Date().toISOString(),
  };
}

describe('orchestration graph helpers', () => {
  it('groups tasks by depth in order', () => {
    const tasks = [task('c', 'ready', 2), task('a', 'succeeded', 1), task('b', 'running', 2)];
    const levels = groupByDepth(tasks);
    expect(levels.map(([d]) => d)).toEqual([1, 2]);
    expect(levels[1][1].map((t) => t.id).sort()).toEqual(['b', 'c']);
  });

  it('computes progress', () => {
    const tasks = [task('a', 'succeeded'), task('b', 'failed'), task('c', 'running')];
    expect(progress(tasks)).toEqual({ succeeded: 1, total: 3 });
  });

  it('maps status colors with fallback', () => {
    expect(statusColor('succeeded')).toBe('#22c55e');
    expect(statusColor('bogus')).toBe('#94a3b8');
  });
});
