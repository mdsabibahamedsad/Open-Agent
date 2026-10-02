import {
  buildEnvelope,
  exportEnvelope,
  importDefinition,
  exportDefinition,
  migrateDefinitionSchema,
  stripSensitive,
  stripSensitiveTrigger,
  templateById,
  TEMPLATES,
  MAX_IMPORT_BYTES,
} from './serialize';
import { validateWorkflowDefinition } from './validate';

describe('serialize', () => {
  it('rejects non-JSON input', () => {
    const r = importDefinition('not json{{{');
    expect(r.ok).toBe(false);
    expect(r.error).toMatch(/JSON/);
  });

  it('rejects structurally invalid definitions with a path', () => {
    const r = importDefinition(JSON.stringify({ schema_version: '1.0', triggers: [{ id: '', type: 'manual' }] }));
    expect(r.ok).toBe(false);
    expect(r.error).toBeDefined();
  });

  it('round-trips export -> import', () => {
    const original = templateById('support-triage').build();
    const imported = importDefinition(exportDefinition(original));
    expect(imported.ok).toBe(true);
    expect(imported.definition).toEqual(original);
  });

  it('all built-in templates validate cleanly', () => {
    for (const t of TEMPLATES) {
      if (t.id === 'blank') continue; // blank has a trigger but no edges -> warnings only
      const r = validateWorkflowDefinition(t.build());
      expect(`${t.id}: ${JSON.stringify(r.errors)}`).toBe(`${t.id}: []`);
      expect(r.valid).toBe(true);
    }
  });

  it('blank template is structurally sound (warnings only)', () => {
    const r = validateWorkflowDefinition(templateById('blank').build());
    expect(r.errors).toEqual([]);
  });

  it('round-trips the export envelope', () => {
    const def = templateById('support-triage').build();
    const env = buildEnvelope(
      { name: 'Triage', slug: 'triage', description: 'd', tags: ['support'] },
      def,
    );
    expect(env.format).toBe('openagent-workflow');
    const back = importDefinition(exportEnvelope(
      { name: 'Triage', slug: 'triage', description: 'd', tags: ['support'] },
      def,
    ));
    expect(back.ok).toBe(true);
    expect(back.definition).toEqual(def);
    expect(back.meta?.name).toBe('Triage');
    expect(back.meta?.tags).toEqual(['support']);
  });

  it('rejects oversized imports', () => {
    const r = importDefinition(`"${'x'.repeat(MAX_IMPORT_BYTES + 1)}"`);
    expect(r.ok).toBe(false);
    expect(r.error).toMatch(/too large/i);
  });

  it('rejects unknown envelope schema versions with a migration error', () => {
    const r = importDefinition(JSON.stringify({
      format: 'openagent-workflow',
      schemaVersion: '9.9',
      workflow: { definition: templateById('blank').build() },
    }));
    expect(r.ok).toBe(false);
    expect(r.error).toMatch(/9\.9/);
  });

  it('migrateDefinitionSchema gates versions', () => {
    expect(migrateDefinitionSchema('1.0', {}).ok).toBe(true);
    expect(migrateDefinitionSchema('2.0', {}).ok).toBe(false);
  });

  it('stripSensitive removes sensitive-marked values on copy', () => {
    const cleaned = stripSensitive({
      id: 'n',
      type: 'webhook',
      name: 'Call',
      config: { url: 'https://x.example', credential_id: 'cred-1' },
    });
    // credential_id is a reference (kept); literal secret fields are dropped.
    expect(cleaned.config).toEqual({ url: 'https://x.example', credential_id: 'cred-1' });

    const cleanedTrigger = stripSensitiveTrigger({
      id: 'trg',
      type: 'webhook',
      name: 'Hook',
      config: { path: '/h', secret: 'SHOULD-NOT-COPY' },
    });
    expect(cleanedTrigger.config).toEqual({ path: '/h' });
  });
});
