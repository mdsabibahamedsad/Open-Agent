import { validateWorkflowDefinition } from './validate';
import { nodeMeta, listNodeDefinitions } from './node-catalog';
import type { WorkflowDefinition } from './types';

function codeflow(nodes: WorkflowDefinition['nodes']): WorkflowDefinition {
  return {
    schema_version: '1.0',
    triggers: [{ id: 'trg_1', type: 'manual', name: 'Run manually', config: {} }],
    nodes,
    edges: nodes.map((n, i) => ({
      id: `e_${i}`,
      from: i === 0 ? 'trg_1' : nodes[i - 1].id,
      to: n.id,
      condition: { when: 'success' as const },
    })),
    variables: [],
    settings: {},
  };
}

describe('code workflow nodes', () => {
  it('registers all nine code node types in the catalog', () => {
    const types = new Set(listNodeDefinitions().map((d) => String(d.type)));
    for (const t of [
      'code_agent', 'code_search', 'code_read', 'code_patch', 'code_test',
      'code_lint', 'code_review', 'git_commit', 'create_pr',
    ]) {
      expect(types.has(t)).toBe(true);
      expect(nodeMeta(t).outputs).toEqual(['out']);
    }
    expect(nodeMeta('code_agent').category).toBe('Agents');
  });

  it('accepts a full fix-and-PR pipeline', () => {
    const d = codeflow([
      { id: 'n_1', type: 'code_agent', name: 'Fix', position: { x: 0, y: 0 }, config: { objective: 'Fix auth', repository_id: 'r1', max_steps: 50 } },
      { id: 'n_2', type: 'code_test', name: 'Test', position: { x: 0, y: 0 }, config: { command: 'pytest -q', profile: 'TEST' } },
      { id: 'n_3', type: 'code_review', name: 'Review', position: { x: 0, y: 0 }, config: { task_id: 't1' } },
      { id: 'n_4', type: 'git_commit', name: 'Commit', position: { x: 0, y: 0 }, config: { task_id: 't1', message: 'fix(auth): …' } },
      { id: 'n_5', type: 'create_pr', name: 'PR', position: { x: 0, y: 0 }, config: { task_id: 't1', title: 'Fix auth' } },
    ]);
    const r = validateWorkflowDefinition(d);
    expect(r.errors).toEqual([]);
  });

  it('rejects code_agent without objective or repository', () => {
    const d = codeflow([
      { id: 'n_1', type: 'code_agent', name: 'Fix', position: { x: 0, y: 0 }, config: {} },
    ]);
    const r = validateWorkflowDefinition(d);
    expect(r.errors.some((e) => e.code === 'NODE_CONFIG_REQUIRED')).toBe(true);
  });

  it('rejects out-of-range max_steps and bad profiles', () => {
    const d = codeflow([
      { id: 'n_1', type: 'code_agent', name: 'Fix', position: { x: 0, y: 0 }, config: { objective: 'x', repository_id: 'r', max_steps: 500 } },
      { id: 'n_2', type: 'code_test', name: 'Test', position: { x: 0, y: 0 }, config: { command: 'x', profile: 'YOLO' } },
    ]);
    const r = validateWorkflowDefinition(d);
    expect(r.errors.filter((e) => e.code === 'NODE_CONFIG_REQUIRED').length).toBeGreaterThanOrEqual(2);
  });

  it('rejects literal secrets in code node configs', () => {
    const d = codeflow([
      { id: 'n_1', type: 'code_agent', name: 'Fix', position: { x: 0, y: 0 }, config: { objective: 'x', repository_id: 'r', api_key: 'sk-live-123' } },
    ]);
    const r = validateWorkflowDefinition(d);
    expect(r.errors.some((e) => e.code === 'SECRET_VALUE')).toBe(true);
  });

  it('requires task-bound configs for patch/commit/pr nodes', () => {
    const d = codeflow([
      { id: 'n_1', type: 'code_patch', name: 'Patch', position: { x: 0, y: 0 }, config: { diff: '--- a' } },
      { id: 'n_2', type: 'git_commit', name: 'Commit', position: { x: 0, y: 0 }, config: { task_id: 't' } },
      { id: 'n_3', type: 'create_pr', name: 'PR', position: { x: 0, y: 0 }, config: { task_id: 't' } },
    ]);
    const r = validateWorkflowDefinition(d);
    expect(r.errors.some((e) => e.code === 'NODE_CONFIG_REQUIRED')).toBe(true);
  });
});
