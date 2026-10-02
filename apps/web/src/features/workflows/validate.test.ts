import { validateWorkflowDefinition } from './validate';
import type { WorkflowDefinition } from './types';

function valid(): WorkflowDefinition {
  return {
    schema_version: '1.0',
    triggers: [{ id: 'trg_1', type: 'manual', name: 'Run manually', config: {} }],
    nodes: [
      { id: 'n_1', type: 'agent', name: 'Triage', position: { x: 0, y: 0 }, config: { agent_id: 'a1' } },
      { id: 'n_2', type: 'condition', name: 'Urgent?', position: { x: 0, y: 0 }, config: { expression: "p == 'h'" } },
    ],
    edges: [
      { id: 'e_1', from: 'trg_1', to: 'n_1', condition: { when: 'always' } },
      { id: 'e_2', from: 'n_1', to: 'n_2', condition: { when: 'success' } },
    ],
    variables: [{ name: 'ticket_id', type: 'string', required: true }],
    settings: {},
  };
}

describe('validateWorkflowDefinition', () => {
  it('accepts a valid definition (terminal warning only for dangling condition output)', () => {
    const r = validateWorkflowDefinition(valid());
    expect(r.valid).toBe(true);
    expect(r.errors).toEqual([]);
  });

  it('rejects missing triggers', () => {
    const d = valid();
    d.triggers = [];
    d.edges = d.edges.filter((e) => e.from !== 'trg_1');
    const r = validateWorkflowDefinition(d);
    expect(r.valid).toBe(false);
    expect(r.errors.some((e) => e.code === 'NO_TRIGGER')).toBe(true);
  });

  it('rejects unknown node types', () => {
    const d = valid();
    (d.nodes[0] as { type: string }).type = 'teleport';
    const r = validateWorkflowDefinition(d);
    expect(r.errors.some((e) => e.code === 'UNKNOWN_NODE_TYPE')).toBe(true);
  });

  it('rejects duplicate ids across triggers and nodes', () => {
    const d = valid();
    d.nodes[1].id = 'n_1';
    const r = validateWorkflowDefinition(d);
    expect(r.errors.some((e) => e.code === 'DUPLICATE_ID')).toBe(true);
  });

  it('rejects self loops, cycles, and edges into triggers', () => {
    const loop = valid();
    loop.edges.push({ id: 'ex', from: 'n_1', to: 'n_1', condition: { when: 'always' } });
    expect(validateWorkflowDefinition(loop).errors.some((e) => e.code === 'SELF_LOOP')).toBe(true);

    const cycle = valid();
    cycle.edges.push({ id: 'ex', from: 'n_2', to: 'n_1', condition: { when: 'always' } });
    expect(validateWorkflowDefinition(cycle).errors.some((e) => e.code === 'CYCLE_DETECTED')).toBe(true);

    const into = valid();
    into.edges.push({ id: 'ex', from: 'n_2', to: 'trg_1', condition: { when: 'always' } });
    expect(validateWorkflowDefinition(into).errors.some((e) => e.code === 'EDGE_INTO_TRIGGER')).toBe(true);
  });

  it('rejects unknown endpoints and unreachable nodes', () => {
    const ghost = valid();
    ghost.edges.push({ id: 'ex', from: 'n_2', to: 'ghost', condition: { when: 'always' } });
    expect(validateWorkflowDefinition(ghost).errors.some((e) => e.code === 'UNKNOWN_EDGE_TARGET')).toBe(true);

    const orphan = valid();
    orphan.nodes.push({ id: 'n_9', type: 'delay', name: 'Wait', config: { duration_seconds: 5 } });
    expect(validateWorkflowDefinition(orphan).errors.some((e) => e.code === 'UNREACHABLE_NODE')).toBe(true);
  });

  it('requires per-type config (agent reference, condition expression)', () => {
    const d = valid();
    d.nodes[0].config = {};
    const r = validateWorkflowDefinition(d);
    expect(r.errors.some((e) => e.code === 'NODE_CONFIG_REQUIRED')).toBe(true);
  });

  it('warns on triggers without outgoing edges', () => {
    const d = valid();
    d.triggers.push({ id: 'trg_2', type: 'manual', name: 'Extra', config: {} });
    const r = validateWorkflowDefinition(d);
    expect(r.valid).toBe(true);
    expect(r.warnings.some((w) => w.code === 'TRIGGER_WITHOUT_EDGES')).toBe(true);
  });

  it('rejects bad variable names and unsupported schema versions', () => {
    const d = valid();
    d.variables.push({ name: '9bad', type: 'string' });
    expect(validateWorkflowDefinition(d).errors.some((e) => e.code === 'INVALID_VARIABLE_NAME')).toBe(true);

    const d2 = valid();
    d2.schema_version = '9.9';
    expect(validateWorkflowDefinition(d2).errors.some((e) => e.code === 'UNSUPPORTED_SCHEMA_VERSION')).toBe(true);
  });

  it('rejects webhook triggers missing a path', () => {
    const d = valid();
    d.triggers[0] = { id: 'trg_1', type: 'webhook', name: 'Hook', config: {} };
    const r = validateWorkflowDefinition(d);
    expect(r.valid).toBe(false);
    expect(r.errors.some((e) => e.code === 'TRIGGER_CONFIG_REQUIRED')).toBe(true);
  });

  it('validates new node types (switch, merge, set, prompt, subworkflow)', () => {
    const d = valid();
    d.nodes.push(
      { id: 'n_sw', type: 'switch', name: 'Route', position: { x: 0, y: 0 }, config: { routes: [{ name: 'vip', expression: "t == 'v'" }] } },
      { id: 'n_mg', type: 'merge', name: 'Join', position: { x: 0, y: 0 }, config: {} },
    );
    d.edges.push(
      { id: 'e_3', from: 'n_2', to: 'n_sw', label: 'true', condition: { when: 'always' } },
      { id: 'e_4', from: 'n_sw', to: 'n_mg', label: 'vip', condition: { when: 'always' } },
      { id: 'e_5', from: 'n_2', to: 'n_mg', label: 'false', condition: { when: 'always' } },
    );
    const r = validateWorkflowDefinition(d);
    expect(r.errors).toEqual([]);
    expect(r.valid).toBe(true);
  });

  it('requires switch routes and prompt model', () => {
    const d = valid();
    d.nodes.push({ id: 'n_sw', type: 'switch', name: 'Route', config: {} });
    d.edges.push({ id: 'e_x', from: 'n_2', to: 'n_sw', label: 'true' });
    expect(validateWorkflowDefinition(d).errors.some((e) => e.code === 'NODE_CONFIG_REQUIRED')).toBe(true);

    const d2 = valid();
    d2.nodes.push({ id: 'n_p', type: 'prompt', name: 'Ask', config: { prompt: 'hi' } });
    d2.edges.push({ id: 'e_x', from: 'n_2', to: 'n_p', label: 'true' });
    expect(validateWorkflowDefinition(d2).errors.some((e) => e.code === 'NODE_CONFIG_REQUIRED')).toBe(true);
  });

  it('rejects literal secrets but allows references', () => {
    const bad = valid();
    bad.nodes[0].config = { agent_id: 'a1', api_key: 'sk-live-abc' };
    const rb = validateWorkflowDefinition(bad);
    expect(rb.valid).toBe(false);
    expect(rb.errors.some((e) => e.code === 'SECRET_VALUE')).toBe(true);

    const good = valid();
    good.nodes[0].config = { agent_id: 'a1', api_key: '{{credentials.openai}}' };
    expect(validateWorkflowDefinition(good).errors.some((e) => e.code === 'SECRET_VALUE')).toBe(false);
  });

  it('skips config and reachability for disabled nodes', () => {
    const d = valid();
    d.nodes.push({ id: 'n_off', type: 'agent', name: 'Paused', disabled: true, config: {} });
    const r = validateWorkflowDefinition(d);
    expect(r.valid).toBe(true);
    expect(r.errors.filter((e) => e.node_id === 'n_off')).toEqual([]);
  });

  it('rejects multiple inbound edges except on merge', () => {
    const d = valid();
    d.edges.push({ id: 'e_x', from: 'n_2', to: 'n_1', label: 'true' });
    expect(validateWorkflowDefinition(d).errors.some((e) => e.code === 'MULTIPLE_INBOUND_EDGES')).toBe(true);
  });

  it('warns on unknown expression references and unused variables', () => {
    const d = valid();
    d.nodes[0].config = { agent_id: 'a1', task: 'Handle {{variables.nope}} via {{nodes.ghost.output}}' };
    const r = validateWorkflowDefinition(d);
    expect(r.valid).toBe(true);
    expect(r.warnings.some((w) => w.code === 'UNKNOWN_VARIABLE_REFERENCE')).toBe(true);
    expect(r.warnings.some((w) => w.code === 'UNKNOWN_NODE_REFERENCE')).toBe(true);
    expect(r.warnings.some((w) => w.code === 'UNUSED_VARIABLE')).toBe(true);
  });

  it('warns on invalid condition port labels', () => {
    const d = valid();
    d.edges.push({ id: 'e_x', from: 'n_2', to: 'n_1', label: 'maybe' });
    const r = validateWorkflowDefinition(d);
    expect(r.warnings.some((w) => w.code === 'INVALID_EDGE_PORT')).toBe(true);
  });

  it('tags issues with severity', () => {
    const bad = validateWorkflowDefinition('nope' as unknown as WorkflowDefinition);
    expect(bad.errors[0].severity).toBe('error');
    const good = validateWorkflowDefinition(valid());
    for (const w of good.warnings) expect(w.severity).toBe('warning');
  });
});
