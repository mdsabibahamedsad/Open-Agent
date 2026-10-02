import {
  checkExpressionRefs,
  extractExpressions,
  getExpressionSuggestions,
  hasBalancedDelimiters,
} from './expressions';

const CTX = { variables: ['ticket_id'], nodeIds: ['n_1'], triggerIds: ['trg_1'] };

describe('expressions', () => {
  it('extracts bodies from nested config', () => {
    expect(
      extractExpressions({ a: 'Hi {{variables.ticket_id}}', b: ['{{nodes.n_1.output}}', 1], c: 'plain' }),
    ).toEqual(['variables.ticket_id', 'nodes.n_1.output']);
  });

  it('accepts declared references silently', () => {
    expect(checkExpressionRefs({ t: '{{variables.ticket_id}} and {{nodes.n_1.output}}' }, CTX)).toEqual([]);
  });

  it('flags unknown variables, nodes, and shorthand', () => {
    const diags = checkExpressionRefs(
      { t: '{{variables.nope}} {{nodes.ghost.x}} {{mystery}}' },
      CTX,
    );
    expect(diags.map((d) => d.code)).toEqual([
      'UNKNOWN_VARIABLE_REFERENCE',
      'UNKNOWN_NODE_REFERENCE',
      'UNKNOWN_REFERENCE',
    ]);
  });

  it('allows platform namespaces without declaration', () => {
    expect(
      checkExpressionRefs({ t: '{{trigger.output}} {{workflow.name}} {{credentials.o}} {{env.HOME}}' }, CTX),
    ).toEqual([]);
  });

  it('detects unbalanced delimiters', () => {
    expect(hasBalancedDelimiters({ t: '{{variables.ticket_id' })).toBe(false);
    expect(hasBalancedDelimiters({ t: '{{variables.ticket_id}}' })).toBe(true);
    const diags = checkExpressionRefs({ t: '{{oops' }, CTX);
    expect(diags.some((d) => d.code === 'UNBALANCED_EXPRESSION')).toBe(true);
  });

  it('suggests variables, node outputs, and platform refs', () => {
    const s = getExpressionSuggestions(CTX);
    expect(s).toContainEqual({ value: '{{variables.ticket_id}}', label: 'Variable: ticket_id' });
    expect(s).toContainEqual({ value: '{{nodes.n_1.output}}', label: 'Output of n_1' });
    expect(s).toContainEqual({ value: '{{trigger.output}}', label: 'Current trigger output' });
  });
});
