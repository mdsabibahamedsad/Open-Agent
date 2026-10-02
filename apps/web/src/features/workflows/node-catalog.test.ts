import {
  definitionsByCategory,
  listNodeDefinitions,
  nodeMeta,
  outputPortsFor,
  registerNodeDefinition,
  unregisterNodeDefinition,
  sensitiveFields,
  TRIGGER_CATALOG,
  type NodeMeta,
} from './node-catalog';

describe('node registry', () => {
  it('exposes all required authoring types', () => {
    const types = new Set(listNodeDefinitions().map((d) => String(d.type)));
    for (const t of [
      'agent', 'prompt', 'condition', 'switch', 'merge', 'loop', 'set',
      'transform', 'filter', 'map', 'variable', 'approval', 'webhook',
      'tool', 'delay', 'subworkflow',
    ]) {
      expect(types.has(t)).toBe(true);
    }
    expect(TRIGGER_CATALOG.map((t) => t.type)).toEqual(['manual', 'webhook', 'schedule', 'event']);
  });

  it('groups definitions by extensible categories', () => {
    const groups = definitionsByCategory();
    const names = groups.map((g) => g.category);
    for (const c of ['Logic', 'Data', 'AI', 'Agents', 'Tools', 'HTTP', 'Human', 'Utilities', 'Advanced']) {
      expect(names).toContain(c);
    }
    const logic = groups.find((g) => g.category === 'Logic')!;
    expect(logic.items.map((i) => String(i.type))).toEqual(
      expect.arrayContaining(['condition', 'switch', 'merge', 'loop']),
    );
  });

  it('nodeMeta throws for unknown types', () => {
    expect(() => nodeMeta('teleport' as never)).toThrow(/Unknown node type/);
  });

  it('supports runtime registration for custom sources', () => {
    const custom: NodeMeta = {
      type: 'acme.pagerduty',
      version: 1,
      label: 'PagerDuty',
      description: 'Org-private integration.',
      icon: listNodeDefinitions()[0].icon,
      category: 'Integrations',
      source: 'organization',
      outputs: ['out'],
      hasInput: true,
      defaultConfig: {},
      configFields: [],
    };
    registerNodeDefinition(custom);
    expect(nodeMeta('acme.pagerduty').source).toBe('organization');
    expect(definitionsByCategory().find((g) => g.category === 'Integrations')?.items).toHaveLength(1);
    expect(() => registerNodeDefinition(custom)).toThrow(/already registered/);
    expect(unregisterNodeDefinition('acme.pagerduty', 1)).toBe(true);
    expect(() => nodeMeta('acme.pagerduty')).toThrow();
  });

  it('expands switch routes into output ports', () => {
    const meta = nodeMeta('switch');
    expect(outputPortsFor(meta)).toEqual(['out']);
    expect(
      outputPortsFor(meta, { config: { routes: [{ name: 'vip' }, { name: 'std' }] } }),
    ).toEqual(['vip', 'std', 'default']);
  });

  it('flags sensitive fields for clipboard/export safety', () => {
    const webhook = nodeMeta('webhook');
    expect(sensitiveFields(webhook)).toEqual([]);
    // Trigger secret is the sensitive one.
    const hook = TRIGGER_CATALOG.find((t) => t.type === 'webhook')!;
    expect(hook.configFields.filter((f) => f.sensitive).map((f) => f.key)).toEqual(['secret']);
  });

  it('stamps versions on definitions', () => {
    for (const d of listNodeDefinitions()) {
      expect(d.version).toBeGreaterThanOrEqual(1);
    }
  });
});
