'use client';

import * as React from 'react';
import type { OrgChart } from './types';

interface ChartNode {
  id: string;
  name: string;
  label?: string;
  children: ChartNode[];
}

export function buildHierarchy(chart: OrgChart): ChartNode[] {
  const managers = new Map(chart.managers.map((m) => [m.agent_id, m.label]));
  const byId = new Map<string, ChartNode>();
  for (const a of chart.agents) {
    byId.set(a.id, { id: a.id, name: a.name, label: managers.get(a.id), children: [] });
  }
  const childIds = new Set<string>();
  for (const r of chart.relationships) {
    if (r.type !== 'manages') continue;
    const parent = byId.get(r.source);
    const child = byId.get(r.target);
    if (parent && child && r.source !== r.target) {
      parent.children.push(child);
      childIds.add(r.target);
    }
  }
  return [...byId.values()].filter((n) => !childIds.has(n.id));
}

export function OrgChartView({ chart }: { chart: OrgChart }) {
  const roots = React.useMemo(() => buildHierarchy(chart), [chart]);
  const teams = React.useMemo(() => {
    const map = new Map<string, { agent_id: string; role: string }[]>();
    for (const m of chart.team_memberships) {
      if (!map.has(m.team_id)) map.set(m.team_id, []);
      map.get(m.team_id)!.push({ agent_id: m.agent_id, role: m.role });
    }
    return map;
  }, [chart]);
  const agentName = (id: string) => chart.agents.find((a) => a.id === id)?.name ?? id.slice(0, 8);

  if (chart.agents.length === 0) {
    return <p className="text-sm text-muted-foreground">No agents in this organization yet.</p>;
  }
  return (
    <div className="space-y-4">
      <ul className="space-y-3" aria-label="Agent organization chart">
        {roots.map((root) => (
          <ChartNodeView key={root.id} node={root} depth={0} />
        ))}
      </ul>
      {chart.departments.length > 0 && (
        <div className="rounded-lg border p-3">
          <h3 className="text-sm font-semibold">Departments</h3>
          <ul className="mt-1 flex flex-wrap gap-2 text-sm">
            {chart.departments.map((d) => (
              <li key={d.id} className="rounded bg-muted px-2 py-1">
                {d.name}
              </li>
            ))}
          </ul>
        </div>
      )}
      {teams.size > 0 && (
        <div className="rounded-lg border p-3">
          <h3 className="text-sm font-semibold">Dynamic team assignments</h3>
          <ul className="mt-1 space-y-1 text-sm">
            {[...teams.entries()].map(([teamId, members]) => (
              <li key={teamId}>
                <span className="font-medium">Team {teamId.slice(0, 8)}</span>{' '}
                <span className="text-muted-foreground">
                  {members.map((m) => `${agentName(m.agent_id)} (${m.role})`).join(', ')}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function ChartNodeView({ node, depth }: { node: ChartNode; depth: number }) {
  const [open, setOpen] = React.useState(depth < 2);
  return (
    <li>
      <div className="flex items-center gap-2">
        {node.children.length > 0 && (
          <button
            type="button"
            onClick={() => setOpen((o) => !o)}
            aria-expanded={open}
            aria-label={open ? `Collapse ${node.name}` : `Expand ${node.name}`}
            className="rounded border px-1.5 text-xs"
          >
            {open ? '−' : '+'}
          </button>
        )}
        <span className="text-sm font-medium">{node.name}</span>
        {node.label && (
          <span className="rounded bg-primary/10 px-1.5 py-0.5 text-xs text-primary">
            {node.label}
          </span>
        )}
        <span className="text-xs text-muted-foreground">
          {node.children.length > 0 ? `${node.children.length} report${node.children.length === 1 ? '' : 's'}` : ''}
        </span>
      </div>
      {open && node.children.length > 0 && (
        <ul className="ml-4 mt-2 space-y-2 border-l pl-4">
          {node.children.map((child) => (
            <ChartNodeView key={child.id} node={child} depth={depth + 1} />
          ))}
        </ul>
      )}
    </li>
  );
}
