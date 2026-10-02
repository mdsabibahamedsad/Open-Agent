import { describe, expect, it } from 'vitest';
import { buildHierarchy } from './OrgChart';
import type { OrgChart } from './types';

function chart(): OrgChart {
  return {
    agents: [
      { id: 'ceo', name: 'CEO', status: 'active' },
      { id: 'mgr', name: 'Manager', status: 'active' },
      { id: 'w1', name: 'Worker 1', status: 'active' },
      { id: 'lone', name: 'Lone', status: 'active' },
    ],
    managers: [
      { agent_id: 'ceo', label: 'ceo', scope: 'organization' },
      { agent_id: 'mgr', label: 'manager', scope: 'team' },
    ],
    relationships: [
      { source: 'ceo', target: 'mgr', type: 'manages' },
      { source: 'mgr', target: 'w1', type: 'manages' },
      { source: 'ceo', target: 'ceo', type: 'manages' },
    ],
    team_memberships: [],
    departments: [{ id: 'd1', name: 'Engineering', slug: 'engineering' }],
  };
}

describe('org chart hierarchy', () => {
  it('nests reports under managers and skips self-loops', () => {
    const roots = buildHierarchy(chart());
    const ids = roots.map((r) => r.id).sort();
    expect(ids).toEqual(['ceo', 'lone']);
    const ceo = roots.find((r) => r.id === 'ceo')!;
    expect(ceo.label).toBe('ceo');
    expect(ceo.children.map((c) => c.id)).toEqual(['mgr']);
    expect(ceo.children[0].children.map((c) => c.id)).toEqual(['w1']);
  });
});
