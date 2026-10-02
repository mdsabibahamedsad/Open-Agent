'use client';

import * as React from 'react';
import type { OrchestrationTask, RunAgentGroup } from './types';

const STATUS_DOT: Record<string, string> = {
  running: 'bg-amber-500',
  succeeded: 'bg-green-500',
  failed: 'bg-red-500',
  waiting: 'bg-violet-500',
  assigned: 'bg-indigo-500',
  ready: 'bg-blue-500',
  created: 'bg-slate-400',
  paused: 'bg-slate-500',
  cancelled: 'bg-gray-500',
  timed_out: 'bg-orange-500',
  skipped: 'bg-gray-400',
};

export function AgentTree({
  tasks,
  groups,
}: {
  tasks: OrchestrationTask[];
  groups: RunAgentGroup[];
}) {
  const byAgent = React.useMemo(() => {
    const map = new Map<string, OrchestrationTask[]>();
    for (const t of tasks) {
      const key = t.assigned_agent_id ?? 'unassigned';
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(t);
    }
    return map;
  }, [tasks]);

  if (tasks.length === 0) {
    return <p className="text-sm text-muted-foreground">No agents assigned yet.</p>;
  }

  return (
    <ul className="space-y-2" aria-label="Live agent tree">
      {[...byAgent.entries()].map(([agentId, agentTasks]) => {
        const group = groups.find((g) => g.agent_id === agentId);
        const short = agentId === 'unassigned' ? 'Unassigned' : agentId.slice(0, 8);
        return (
          <li key={agentId} className="rounded-lg border p-3">
            <div className="flex items-center gap-2 text-sm font-medium">
              <span className="inline-block h-2 w-2 rounded-full bg-primary" aria-hidden />
              Agent {short}
              <span className="text-xs font-normal text-muted-foreground">
                {agentTasks.length} task{agentTasks.length === 1 ? '' : 's'}
                {group ? ` · ${group.status}` : ''}
              </span>
            </div>
            <ul className="ml-4 mt-2 space-y-1 border-l pl-4">
              {agentTasks.map((t) => (
                <li key={t.id} className="flex items-center gap-2 text-sm">
                  <span
                    className={`inline-block h-2 w-2 rounded-full ${STATUS_DOT[t.status] ?? 'bg-slate-400'}`}
                    aria-hidden
                  />
                  <span className="font-medium">{t.title}</span>
                  <span className="text-xs uppercase text-muted-foreground">[{t.status}]</span>
                  {t.depth > 1 && (
                    <span className="text-xs text-muted-foreground">depth {t.depth}</span>
                  )}
                </li>
              ))}
            </ul>
          </li>
        );
      })}
    </ul>
  );
}
