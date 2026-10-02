import { describe, expect, it } from 'vitest';
import { compactAction, scaffoldConnector, validateManifest } from './index';

describe('connector-sdk', () => {
  it('validates a manifest', () => {
    const files = scaffoldConnector('acme_crm', 'Acme CRM');
    const manifest = JSON.parse(files['manifest.json']);
    const parsed = validateManifest(manifest);
    expect(parsed.id).toBe('acme_crm');
    expect(parsed.actions).toHaveLength(1);
  });

  it('rejects unnamespaced capabilities', () => {
    expect(() =>
      validateManifest({
        id: 'acme',
        name: 'Acme',
        version: '1.0.0',
        capabilities: [{ id: 'other.read' }],
        actions: [],
      }),
    ).toThrow(/namespaced/);
  });

  it('rejects bad versions and scope floods', () => {
    expect(() =>
      validateManifest({
        id: 'acme',
        name: 'Acme',
        version: 'banana',
        capabilities: [{ id: 'acme.read' }],
        actions: [],
      }),
    ).toThrow(/version/);
    expect(() =>
      validateManifest({
        id: 'acme',
        name: 'Acme',
        version: '1.0.0',
        capabilities: [{ id: 'acme.read' }],
        actions: [],
        scopes: Array.from({ length: 100 }, (_, i) => `s${i}`),
      }),
    ).toThrow(/scope/i);
  });

  it('builds compact descriptors', () => {
    expect(
      compactAction(
        {
          id: 'acme.list',
          name: 'List',
          input_schema: { type: 'object' },
          required_capabilities: ['acme.read'],
        },
        'CUSTOM',
      ),
    ).toContain('acme.list');
  });
});
