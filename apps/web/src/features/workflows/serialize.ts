import { workflowDefinitionSchema } from './schema';
import { nodeMeta, sensitiveFields, triggerMeta } from './node-catalog';
import {
  SCHEMA_VERSION,
  emptyDefinition,
  type TriggerType,
  type WorkflowDefinition,
  type WorkflowEdge,
  type WorkflowNode,
  type WorkflowNodeType,
  type WorkflowTrigger,
} from './types';

/** Hard cap for imported files (import security). */
export const MAX_IMPORT_BYTES = 1024 * 1024;

export const ENVELOPE_FORMAT = 'openagent-workflow';

export interface WorkflowEnvelope {
  format: typeof ENVELOPE_FORMAT;
  schemaVersion: string;
  exported_at: string;
  workflow: {
    name: string;
    slug: string;
    description?: string;
    tags?: string[];
    definition: WorkflowDefinition;
  };
}

let counter = 0;

/** Deterministic-ish id factory (prefix + base36 time + counter). */
export function newId(prefix: string): string {
  counter += 1;
  return `${prefix}_${Date.now().toString(36)}${counter.toString(36)}`;
}

export function makeTrigger(type: TriggerType, at?: { x: number; y: number }): WorkflowTrigger {
  const meta = triggerMeta(type);
  void meta;
  return { id: newId('trg'), type, name: `New ${type} trigger`, config: {} };
}

export function makeNode(type: WorkflowNodeType, at?: { x: number; y: number }): WorkflowNode {
  const meta = nodeMeta(type);
  return {
    id: newId('n'),
    type,
    type_version: meta.version,
    name: `New ${meta.label}`,
    position: at ?? { x: 120, y: 120 },
    config: { ...meta.defaultConfig },
  };
}

export function makeEdge(from: string, to: string, port?: string): WorkflowEdge {
  return {
    id: newId('e'),
    from,
    to,
    label: port && port !== 'out' ? port : undefined,
    condition: { when: 'always' },
  };
}

export interface ImportResult {
  ok: boolean;
  definition?: WorkflowDefinition;
  /** Envelope metadata when the file was an envelope. */
  meta?: { name?: string; slug?: string; description?: string; tags?: string[] };
  migrated?: boolean;
  error?: string;
}

/**
 * Parse + shape-check raw JSON for import. Accepts the export envelope or a
 * raw definition (backward compatible). Enforces the size cap and runs the
 * schema migration gate. Graph rules are checked by validate.ts.
 */
export function importDefinition(raw: string): ImportResult {
  if (raw.length > MAX_IMPORT_BYTES) {
    return { ok: false, error: `File too large (limit ${(MAX_IMPORT_BYTES / 1024).toFixed(0)} KB).` };
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return { ok: false, error: 'File is not valid JSON.' };
  }
  let candidate: unknown = parsed;
  let meta: ImportResult['meta'];
  let migrated = false;
  if (isEnvelope(parsed)) {
    candidate = parsed.workflow.definition ?? parsed.workflow;
    meta = {
      name: parsed.workflow.name,
      slug: parsed.workflow.slug,
      description: parsed.workflow.description,
      tags: parsed.workflow.tags,
    };
    if (parsed.schemaVersion !== SCHEMA_VERSION) {
      const m = migrateDefinitionSchema(parsed.schemaVersion, candidate);
      if (!m.ok) return { ok: false, error: m.error };
      candidate = m.definition;
      migrated = true;
    }
  }
  const result = workflowDefinitionSchema.safeParse(candidate);
  if (!result.success) {
    const first = result.error.issues[0];
    const path = first.path.join('.') || '(root)';
    return { ok: false, error: `Invalid workflow file at ${path}: ${first.message}` };
  }
  const d = result.data;
  const definition: WorkflowDefinition = {
    schema_version: d.schema_version,
    triggers: d.triggers.map((t) => ({
      id: t.id,
      type: t.type,
      name: t.name,
      config: t.config as Record<string, unknown>,
    })),
    nodes: d.nodes.map((n) => ({
      id: n.id,
      type: n.type,
      type_version: n.type_version,
      name: n.name,
      position: n.position,
      config: n.config as Record<string, unknown>,
      retry_policy: n.retry_policy,
      timeout_seconds: n.timeout_seconds,
      approval_required: n.approval_required,
      disabled: n.disabled,
      notes: n.notes,
      group_id: n.group_id,
    })),
    edges: d.edges.map((e) => ({
      id: e.id,
      from: e.from,
      to: e.to,
      label: e.label,
      condition: e.condition ? { when: e.condition.when, expression: e.condition.expression } : undefined,
    })),
    variables: d.variables.map((v) => ({
      name: v.name,
      type: v.type,
      default: v.default,
      required: v.required,
      description: v.description,
    })),
    settings: (d.settings ?? {}) as Record<string, unknown>,
  };
  return { ok: true, definition, meta, migrated };
}

function isEnvelope(v: unknown): v is {
  format: string;
  schemaVersion: string;
  workflow: { definition?: unknown; name?: string; slug?: string; description?: string; tags?: string[] };
} {
  return (
    typeof v === 'object' &&
    v !== null &&
    (v as { format?: unknown }).format === ENVELOPE_FORMAT &&
    typeof (v as { workflow?: unknown }).workflow === 'object'
  );
}

/**
 * Schema migration gate. Only 1.0 exists: unknown versions are rejected
 * with a clear error so future 1.1/2.0 migrations plug in here.
 */
export function migrateDefinitionSchema(
  fromVersion: string,
  candidate: unknown,
): { ok: boolean; definition?: unknown; error?: string } {
  if (fromVersion === SCHEMA_VERSION) return { ok: true, definition: candidate };
  return {
    ok: false,
    error: `Unsupported workflow schemaVersion '${fromVersion}'. This builder reads '${SCHEMA_VERSION}'.`,
  };
}

/** Portable export envelope. Definitions hold only references (validated). */
export function buildEnvelope(
  workflow: { name: string; slug: string; description?: string | null; tags?: string[] },
  definition: WorkflowDefinition,
): WorkflowEnvelope {
  return {
    format: ENVELOPE_FORMAT,
    schemaVersion: SCHEMA_VERSION,
    exported_at: new Date().toISOString(),
    workflow: {
      name: workflow.name,
      slug: workflow.slug,
      description: workflow.description ?? undefined,
      tags: workflow.tags,
      definition,
    },
  };
}

export function exportEnvelope(
  workflow: { name: string; slug: string; description?: string | null; tags?: string[] },
  definition: WorkflowDefinition,
): string {
  return JSON.stringify(buildEnvelope(workflow, definition), null, 2);
}

/** Remove sensitive-marked config values (clipboard safety, never secrets). */
export function stripSensitive(node: WorkflowNode): WorkflowNode {
  let meta;
  try {
    meta = nodeMeta(node.type);
  } catch {
    return node;
  }
  const keys = sensitiveFields(meta);
  if (keys.length === 0) return node;
  const config = { ...node.config };
  for (const k of keys) delete config[k];
  return { ...node, config };
}

export function stripSensitiveTrigger(trigger: WorkflowTrigger): WorkflowTrigger {
  const config = { ...trigger.config };
  // Trigger catalog fields are looked up by type; drop known-sensitive keys.
  if (trigger.type === 'webhook') delete config.secret;
  return { ...trigger, config };
}

export function exportDefinition(definition: WorkflowDefinition): string {
  return JSON.stringify(definition, null, 2);
}

export function downloadDefinition(definition: WorkflowDefinition, slug: string): void {
  downloadText(exportDefinition(definition), `${slug || 'workflow'}.workflow.json`);
}

export function downloadEnvelope(
  workflow: { name: string; slug: string; description?: string | null; tags?: string[] },
  definition: WorkflowDefinition,
): void {
  downloadText(exportEnvelope(workflow, definition), `${workflow.slug || 'workflow'}.openagent-workflow.json`);
}

function downloadText(text: string, filename: string): void {
  const blob = new Blob([text], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

// Templates ---------------------------------------------------------------

function at(x: number, y: number) {
  return { x, y };
}

export interface WorkflowTemplate {
  id: string;
  name: string;
  description: string;
  build: () => WorkflowDefinition;
}

export const TEMPLATES: WorkflowTemplate[] = [
  {
    id: 'blank',
    name: 'Blank canvas',
    description: 'A manual trigger with room for your first nodes.',
    build: () => ({
      ...emptyDefinition(),
      triggers: [{ id: 'trg_start', type: 'manual', name: 'Run manually', config: {} }],
    }),
  },
  {
    id: 'support-triage',
    name: 'Support ticket triage',
    description: 'Manual start → triage agent → urgency branch → approval for urgent tickets.',
    build: () => ({
      ...emptyDefinition(),
      triggers: [{ id: 'trg_start', type: 'manual', name: 'New ticket', config: {} }],
      variables: [{ name: 'ticket_id', type: 'string', required: true, description: 'Incoming ticket identifier' }],
      nodes: [
        { id: 'n_triage', type: 'agent', name: 'Triage ticket', position: at(80, 200), config: { agent_id: 'YOUR_AGENT_ID', task: 'Classify ticket {{ticket_id}} by urgency and topic.' } },
        { id: 'n_urgent', type: 'condition', name: 'Is it urgent?', position: at(360, 200), config: { expression: "priority == 'high'" } },
        { id: 'n_approve', type: 'approval', name: 'Human review', position: at(640, 120), config: { approvers: ['oncall@example.com'], message: 'Urgent ticket {{ticket_id}} needs review.' } },
        { id: 'n_reply', type: 'transform', name: 'Draft reply', position: at(640, 320), config: { mapping: '{"draft": "Thanks — we are looking into {{ticket_id}}."}' } },
      ],
      edges: [
        { id: 'e_1', from: 'trg_start', to: 'n_triage', condition: { when: 'always' } },
        { id: 'e_2', from: 'n_triage', to: 'n_urgent', condition: { when: 'success' } },
        { id: 'e_3', from: 'n_urgent', to: 'n_approve', label: 'true', condition: { when: 'always' } },
        { id: 'e_4', from: 'n_urgent', to: 'n_reply', label: 'false', condition: { when: 'always' } },
      ],
    }),
  },
  {
    id: 'scheduled-research',
    name: 'Scheduled research digest',
    description: 'Weekday schedule → research agent → webhook delivery.',
    build: () => ({
      ...emptyDefinition(),
      triggers: [{ id: 'trg_sched', type: 'schedule', name: 'Weekday mornings', config: { cron: '0 9 * * MON-FRI', timezone: 'UTC' } }],
      nodes: [
        { id: 'n_research', type: 'agent', name: 'Research topics', position: at(80, 200), config: { agent_id: 'YOUR_AGENT_ID', task: 'Summarize overnight developments.' } },
        { id: 'n_deliver', type: 'webhook', name: 'Post digest', position: at(360, 200), config: { url: 'https://example.com/your-endpoint', method: 'POST' } },
      ],
      edges: [
        { id: 'e_1', from: 'trg_sched', to: 'n_research', condition: { when: 'always' } },
        { id: 'e_2', from: 'n_research', to: 'n_deliver', condition: { when: 'success' } },
      ],
    }),
  },
];

export function templateById(id: string): WorkflowTemplate {
  return TEMPLATES.find((t) => t.id === id) ?? TEMPLATES[0];
}
