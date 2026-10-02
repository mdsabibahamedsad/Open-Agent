import type {
  ValidationIssue,
  ValidationResult,
  WorkflowDefinition,
} from './types';
import { checkExpressionRefs, extractExpressions } from './expressions';

// Client-side validation mirroring the backend validator
// (`openagent.services.workflow_definition`). Fast and synchronous so the
// builder can validate on every edit; the server remains authoritative
// (publish and dry-run call POST /validate).

const TRIGGER_TYPES = new Set(['manual', 'webhook', 'schedule', 'event']);
const NODE_TYPES = new Set([
  'agent', 'prompt', 'condition', 'switch', 'merge', 'loop', 'set',
  'transform', 'filter', 'map', 'variable', 'approval', 'webhook',
  'tool', 'delay', 'subworkflow',
  'code_agent', 'code_search', 'code_read', 'code_patch', 'code_test',
  'code_lint', 'code_review', 'git_commit', 'create_pr',
]);
const EDGE_WHEN = new Set(['always', 'success', 'failure']);
const VARIABLE_TYPES = new Set(['string', 'number', 'boolean', 'json']);
const TERMINAL = new Set(['approval']);
const FAN_IN = new Set(['merge']);
const NAME_RE = /^[A-Za-z_][A-Za-z0-9_]*$/;

const SECRET_LIKE_KEYS = new Set([
  'api_key', 'apikey', 'secret', 'token', 'password', 'passwd',
  'private_key', 'client_secret', 'access_key', 'auth_token',
  'secret_key', 'api_secret',
]);
const REFERENCE_KEYS = new Set(['credential_id', 'secret_ref', 'credential_ref']);

function isObj(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

function isReference(value: unknown): boolean {
  return typeof value === 'string' && value.includes('{{') && value.includes('}}');
}

function* stringLeaves(value: unknown, path = ''): Generator<[string, string]> {
  if (typeof value === 'string') {
    yield [path, value];
  } else if (Array.isArray(value)) {
    for (let i = 0; i < value.length; i++) yield* stringLeaves(value[i], `${path}[${i}]`);
  } else if (isObj(value)) {
    for (const [k, v] of Object.entries(value)) yield* stringLeaves(v, path ? `${path}.${k}` : k);
  }
}

export function validateWorkflowDefinition(def: WorkflowDefinition): ValidationResult {
  const errors: ValidationIssue[] = [];
  const warnings: ValidationIssue[] = [];
  const err = (code: string, message: string, node_id?: string, field?: string, edge_id?: string) =>
    errors.push({ code, message, severity: 'error', node_id, field, edge_id });
  const warn = (code: string, message: string, node_id?: string, field?: string, edge_id?: string) =>
    warnings.push({ code, message, severity: 'warning', node_id, field, edge_id });

  if (!isObj(def as unknown)) {
    err('INVALID_DEFINITION', 'Definition must be a JSON object.');
    return { valid: false, errors, warnings };
  }

  if (def.schema_version !== '1.0') {
    err('UNSUPPORTED_SCHEMA_VERSION', `Unsupported schema_version '${def.schema_version}'. Expected '1.0'.`, undefined, 'schema_version');
  }

  const triggers = Array.isArray(def.triggers) ? def.triggers : [];
  const nodes = Array.isArray(def.nodes) ? def.nodes : [];
  const edges = Array.isArray(def.edges) ? def.edges : [];
  const variables = Array.isArray(def.variables) ? def.variables : [];

  if (!Array.isArray(def.triggers)) err('INVALID_TRIGGERS', "'triggers' must be a list.", undefined, 'triggers');
  if (!Array.isArray(def.nodes)) err('INVALID_NODES', "'nodes' must be a list.", undefined, 'nodes');
  if (!Array.isArray(def.edges)) err('INVALID_EDGES', "'edges' must be a list.", undefined, 'edges');
  if (!Array.isArray(def.variables)) err('INVALID_VARIABLES', "'variables' must be a list.", undefined, 'variables');

  if (triggers.length === 0) err('NO_TRIGGER', 'Workflow must define at least one trigger.', undefined, 'triggers');

  const triggerIds = new Set<string>();
  triggers.forEach((t, i) => {
    const where = `triggers[${i}]`;
    if (!isObj(t)) { err('INVALID_TRIGGER', `${where} must be an object.`, undefined, where); return; }
    const tid = t.id;
    if (typeof tid !== 'string' || !tid) { err('TRIGGER_MISSING_ID', `${where} requires a non-empty string 'id'.`, undefined, `${where}.id`); return; }
    if (triggerIds.has(tid)) err('DUPLICATE_ID', `Duplicate id '${tid}'.`, tid, `${where}.id`);
    triggerIds.add(tid);
    if (!TRIGGER_TYPES.has(t.type as string)) err('UNKNOWN_TRIGGER_TYPE', `Trigger '${tid}' has unknown type '${t.type}'.`, tid, `${where}.type`);
    if (!t.name) err('TRIGGER_MISSING_NAME', `Trigger '${tid}' requires a 'name'.`, tid, `${where}.name`);
    const cfg = (isObj(t.config) ? t.config : {}) as Record<string, unknown>;
    if (t.type === 'webhook' && !cfg.path) err('TRIGGER_CONFIG_REQUIRED', `Webhook trigger '${tid}' requires 'config.path'.`, tid, `${where}.config.path`);
    if (t.type === 'schedule' && !cfg.cron) err('TRIGGER_CONFIG_REQUIRED', `Schedule trigger '${tid}' requires 'config.cron'.`, tid, `${where}.config.cron`);
    if (t.type === 'event' && !cfg.event) err('TRIGGER_CONFIG_REQUIRED', `Event trigger '${tid}' requires 'config.event'.`, tid, `${where}.config.event`);
  });

  const nodeIds = new Set<string>();
  const disabledIds = new Set<string>();
  const nodeById = new Map<string, (typeof nodes)[number]>();
  nodes.forEach((n, i) => {
    const where = `nodes[${i}]`;
    if (!isObj(n)) { err('INVALID_NODE', `${where} must be an object.`, undefined, where); return; }
    const nid = n.id;
    if (typeof nid !== 'string' || !nid) { err('NODE_MISSING_ID', `${where} requires a non-empty string 'id'.`, undefined, `${where}.id`); return; }
    if (triggerIds.has(nid) || nodeIds.has(nid)) err('DUPLICATE_ID', `Duplicate id '${nid}'.`, nid, `${where}.id`);
    nodeIds.add(nid);
    nodeById.set(nid, n);
    if (n.disabled === true) disabledIds.add(nid);
    if (!NODE_TYPES.has(n.type as string)) err('UNKNOWN_NODE_TYPE', `Node '${nid}' has unknown type '${n.type}'.`, nid, `${where}.type`);
    if (!n.name) err('NODE_MISSING_NAME', `Node '${nid}' requires a 'name'.`, nid, `${where}.name`);
    if (n.type_version !== undefined && (typeof n.type_version !== 'number' || n.type_version < 1)) {
      err('INVALID_NODE_FIELD', `Node '${nid}' 'type_version' must be a positive integer when present.`, nid, `${where}.type_version`);
    }
    const cfg = (isObj(n.config) ? n.config : {}) as Record<string, unknown>;
    if (!disabledIds.has(nid)) validateNodeConfig(err, nid, n.type as string, cfg, where);
    if (n.timeout_seconds !== undefined && (typeof n.timeout_seconds !== 'number' || n.timeout_seconds <= 0)) {
      err('INVALID_TIMEOUT', `Node '${nid}' 'timeout_seconds' must be a positive number.`, nid, `${where}.timeout_seconds`);
    }
    const retry = n.retry_policy as { max_attempts?: unknown } | undefined;
    if (retry !== undefined) {
      if (!isObj(retry) || typeof retry.max_attempts !== 'number' || retry.max_attempts < 0 || retry.max_attempts > 10) {
        err('INVALID_RETRY_POLICY', `Node '${nid}' 'retry_policy.max_attempts' must be an integer 0..10.`, nid, `${where}.retry_policy.max_attempts`);
      }
    }
  });

  const allIds = new Set([...triggerIds, ...nodeIds]);
  const outgoing = new Map<string, string[]>();
  const incoming = new Map<string, string[]>();
  allIds.forEach((id) => { outgoing.set(id, []); incoming.set(id, []); });
  const pairs = new Set<string>();
  edges.forEach((e, i) => {
    const where = `edges[${i}]`;
    if (!isObj(e)) { err('INVALID_EDGE', `${where} must be an object.`, undefined, where); return; }
    const src = e.from as string;
    const dst = e.to as string;
    if (typeof src !== 'string' || typeof dst !== 'string' || !src || !dst) {
      err('EDGE_MISSING_ENDPOINTS', `${where} requires string 'from' and 'to'.`, undefined, where);
      return;
    }
    if (!allIds.has(src)) { err('UNKNOWN_EDGE_SOURCE', `${where} references unknown source '${src}'.`, undefined, `${where}.from`); return; }
    if (!allIds.has(dst)) { err('UNKNOWN_EDGE_TARGET', `${where} references unknown target '${dst}'.`, undefined, `${where}.to`); return; }
    if (src === dst) { err('SELF_LOOP', `Node '${src}' cannot connect to itself.`, src, where); return; }
    if (triggerIds.has(dst)) { err('EDGE_INTO_TRIGGER', `Triggers cannot have incoming edges ('${src}' -> '${dst}').`, dst, where); return; }
    if (pairs.has(`${src}→${dst}`)) { err('DUPLICATE_EDGE', `Duplicate edge '${src}' -> '${dst}'.`, undefined, where); return; }
    pairs.add(`${src}→${dst}`);
    outgoing.get(src)!.push(dst);
    incoming.get(dst)!.push(src);

    const srcNode = nodeById.get(src);
    const srcType = srcNode?.type as string | undefined;
    const eid = typeof e.id === 'string' ? e.id : undefined;
    if (srcType === 'condition' && e.label !== undefined && e.label !== 'true' && e.label !== 'false') {
      warn('INVALID_EDGE_PORT', `Edge '${src}' -> '${dst}': condition outputs are 'true'/'false', got label '${e.label}'.`, undefined, `${where}.label`, eid);
    }
    if (srcType === 'switch' && typeof e.label === 'string') {
      const routes = switchRouteNames(srcNode!);
      if (routes.length > 0 && !routes.includes(e.label) && e.label !== 'default') {
        warn('INVALID_EDGE_PORT', `Edge '${src}' -> '${dst}': label '${e.label}' matches no route [${routes.join(', ')}].`, undefined, `${where}.label`, eid);
      }
    }

    const cond = e.condition as { when?: unknown; expression?: unknown } | undefined;
    if (cond !== undefined) {
      if (!isObj(cond)) { err('INVALID_EDGE_CONDITION', `${where} 'condition' must be an object.`, undefined, `${where}.condition`); }
      else {
        if (cond.when !== undefined && !EDGE_WHEN.has(cond.when as string)) {
          err('INVALID_EDGE_CONDITION', `${where} 'condition.when' must be one of always/success/failure.`, undefined, `${where}.condition.when`);
        }
        if (cond.expression !== undefined && (typeof cond.expression !== 'string' || !cond.expression.trim())) {
          err('INVALID_EDGE_CONDITION', `${where} 'condition.expression' must be a non-empty string when present.`, undefined, `${where}.condition.expression`);
        }
      }
    }
  });

  // Cycles (iterative DFS) + reachability + cardinality.
  const WHITE = 0, GRAY = 1, BLACK = 2;
  const color = new Map<string, number>();
  allIds.forEach((id) => color.set(id, WHITE));
  for (const start of [...allIds].sort()) {
    if (color.get(start) !== WHITE) continue;
    const stack: { node: string; it: Iterator<string> }[] = [{ node: start, it: (outgoing.get(start) ?? []).slice().sort()[Symbol.iterator]() }];
    const path = [start];
    color.set(start, GRAY);
    while (stack.length > 0) {
      const top = stack[stack.length - 1];
      const next = top.it.next();
      if (next.done) {
        color.set(top.node, BLACK);
        stack.pop();
        path.pop();
        continue;
      }
      const nxt = next.value;
      const c = color.get(nxt);
      if (c === GRAY) {
        const cycle = [...path.slice(path.indexOf(nxt)), nxt].join(' -> ');
        err('CYCLE_DETECTED', `Cycle detected: ${cycle}. Only acyclic graphs are supported in v1.`, nxt);
      } else if (c === WHITE) {
        color.set(nxt, GRAY);
        stack.push({ node: nxt, it: (outgoing.get(nxt) ?? []).slice().sort()[Symbol.iterator]() });
        path.push(nxt);
      }
    }
  }

  const reachable = new Set<string>();
  const stack = [...triggerIds];
  while (stack.length > 0) {
    const cur = stack.pop()!;
    if (reachable.has(cur)) continue;
    reachable.add(cur);
    for (const nxt of outgoing.get(cur) ?? []) stack.push(nxt);
  }
  for (const nid of [...nodeIds].sort()) {
    if (!reachable.has(nid) && !disabledIds.has(nid)) {
      err('UNREACHABLE_NODE', `Node '${nid}' is not reachable from any trigger.`, nid);
    }
  }
  for (const nid of [...nodeIds].sort()) {
    const ntype = nodeById.get(nid)?.type as string;
    if (FAN_IN.has(ntype)) continue;
    const inbound = incoming.get(nid) ?? [];
    if (inbound.length > 1) {
      err('MULTIPLE_INBOUND_EDGES', `Node '${nid}' has ${inbound.length} incoming edges; '${ntype}' accepts a single input. Use a merge node for fan-in.`, nid);
    }
  }

  for (const tid of [...triggerIds].sort()) {
    if ((outgoing.get(tid) ?? []).length === 0) {
      warn('TRIGGER_WITHOUT_EDGES', `Trigger '${tid}' has no outgoing edges and will never run anything.`, tid);
    }
  }
  for (const nid of [...nodeIds].sort()) {
    const n = nodeById.get(nid)!;
    if ((outgoing.get(nid) ?? []).length === 0 && !TERMINAL.has(n.type as string)) {
      warn('NODE_WITHOUT_OUTGOING', `Node '${nid}' has no outgoing edges; its branch ends here.`, nid);
    }
  }

  const varNames = new Set<string>();
  variables.forEach((v, i) => {
    const where = `variables[${i}]`;
    if (!isObj(v)) { err('INVALID_VARIABLE', `${where} must be an object.`, undefined, where); return; }
    const name = v.name as string;
    if (typeof name !== 'string' || !NAME_RE.test(name)) {
      err('INVALID_VARIABLE_NAME', `${where} 'name' must match [A-Za-z_][A-Za-z0-9_]*.`, undefined, `${where}.name`);
      return;
    }
    if (varNames.has(name)) err('DUPLICATE_VARIABLE', `Duplicate variable '${name}'.`, undefined, `${where}.name`);
    varNames.add(name);
    if (!VARIABLE_TYPES.has(v.type as string)) {
      err('INVALID_VARIABLE_TYPE', `Variable '${name}' type must be one of string/number/boolean/json.`, undefined, `${where}.type`);
    }
  });

  // Security: literal secrets are rejected everywhere.
  for (const [nid, n] of nodeById) {
    if (isObj(n.config)) checkNoLiteralSecrets(err, nid, n.config as Record<string, unknown>, 'config');
  }
  triggers.forEach((t) => {
    if (isObj(t) && isObj((t as { config?: unknown }).config)) {
      checkNoLiteralSecrets(err, (t as { id: string }).id, (t as { config: Record<string, unknown> }).config, 'config');
    }
  });

  // Expressions: advisory reference checks.
  checkExpressionRefsAll(warn, triggers, nodeById, edges, varNames);

  return { valid: errors.length === 0, errors, warnings };
}

function switchRouteNames(node: { config?: unknown }): string[] {
  const cfg = node.config;
  if (!isObj(cfg)) return [];
  const routes = cfg.routes;
  if (!Array.isArray(routes)) return [];
  return routes
    .map((r) => (isObj(r) ? r.name : undefined))
    .filter((n): n is string => typeof n === 'string' && !!n);
}

function validateNodeConfig(
  err: (code: string, message: string, node_id?: string, field?: string) => void,
  nid: string,
  ntype: string,
  cfg: Record<string, unknown>,
  where: string,
): void {
  const req = (fieldName: string, message: string) => {
    if (!cfg[fieldName]) err('NODE_CONFIG_REQUIRED', `Node '${nid}': ${message}.`, nid, `${where}.config.${fieldName}`);
  };
  switch (ntype) {
    case 'agent':
      if (!cfg.agent_id && !cfg.agent_name) {
        err('NODE_CONFIG_REQUIRED', `Node '${nid}' requires 'config.agent_id' or 'config.agent_name'.`, nid, `${where}.config.agent_id`);
      }
      break;
    case 'prompt':
      req('prompt', "AI prompt nodes require 'config.prompt'");
      if (!cfg.model && !cfg.model_router_profile) {
        err('NODE_CONFIG_REQUIRED', `Node '${nid}' requires 'config.model' or 'config.model_router_profile'.`, nid, `${where}.config.model`);
      }
      break;
    case 'condition':
      req('expression', "condition nodes require 'config.expression'");
      break;
    case 'switch': {
      const routes = cfg.routes;
      if (!Array.isArray(routes) || routes.length === 0) {
        err('NODE_CONFIG_REQUIRED', `Node '${nid}' requires a non-empty 'config.routes' list of {name, expression}.`, nid, `${where}.config.routes`);
      } else {
        const seen = new Set<string>();
        for (const r of routes) {
          const name = isObj(r) ? r.name : undefined;
          if (typeof name !== 'string' || !name) {
            err('NODE_CONFIG_REQUIRED', `Node '${nid}' routes require a non-empty 'name'.`, nid, `${where}.config.routes`);
          } else if (seen.has(name)) {
            err('NODE_CONFIG_REQUIRED', `Node '${nid}' has a duplicate route name '${name}'.`, nid, `${where}.config.routes`);
          } else {
            seen.add(name);
            if (isObj(r) && !r.expression) {
              err('NODE_CONFIG_REQUIRED', `Node '${nid}' route '${name}' requires an 'expression'.`, nid, `${where}.config.routes`);
            }
          }
        }
      }
      break;
    }
    case 'merge':
      break;
    case 'set':
      if (!isObj(cfg.values) || Object.keys(cfg.values).length === 0) {
        err('NODE_CONFIG_REQUIRED', `Node '${nid}' requires a non-empty 'config.values' object.`, nid, `${where}.config.values`);
      }
      break;
    case 'filter':
      req('predicate', "filter nodes require 'config.predicate'");
      break;
    case 'map':
      req('items', "map nodes require 'config.items' (collection expression)");
      req('expression', "map nodes require 'config.expression' (per-item expression)");
      break;
    case 'variable':
      if ((cfg.mode ?? 'set') !== 'set' && (cfg.mode ?? 'set') !== 'get') {
        err('NODE_CONFIG_REQUIRED', `Node '${nid}' 'config.mode' must be 'set' or 'get'.`, nid, `${where}.config.mode`);
      }
      req('name', "variable nodes require 'config.name'");
      break;
    case 'subworkflow':
      if (!cfg.workflow_id) {
        err('NODE_CONFIG_REQUIRED', `Node '${nid}' requires 'config.workflow_id' (referenced workflow).`, nid, `${where}.config.workflow_id`);
      }
      break;
    case 'loop':
      req('items', "loop nodes require 'config.items' (collection expression)");
      if (cfg.max_iterations !== undefined && (typeof cfg.max_iterations !== 'number' || cfg.max_iterations < 1 || cfg.max_iterations > 10000)) {
        err('NODE_CONFIG_REQUIRED', `Node '${nid}' 'config.max_iterations' must be an integer 1..10000.`, nid, `${where}.config.max_iterations`);
      }
      break;
    case 'transform':
      if (!cfg.mapping && !cfg.expression) {
        err('NODE_CONFIG_REQUIRED', `Node '${nid}' requires 'config.mapping' or 'config.expression'.`, nid, `${where}.config.mapping`);
      }
      break;
    case 'approval': {
      const approvers = cfg.approvers;
      if (!Array.isArray(approvers) || approvers.length === 0) {
        err('NODE_CONFIG_REQUIRED', `Node '${nid}' requires a non-empty 'config.approvers' list.`, nid, `${where}.config.approvers`);
      }
      break;
    }
    case 'webhook':
      req('url', "webhook nodes require 'config.url'");
      if (cfg.method !== undefined && !['GET', 'POST', 'PUT', 'PATCH', 'DELETE'].includes(String(cfg.method).toUpperCase())) {
        err('NODE_CONFIG_REQUIRED', `Node '${nid}' 'config.method' must be a valid HTTP method.`, nid, `${where}.config.method`);
      }
      break;
    case 'tool':
      if (!cfg.tool_id && !cfg.tool_name) {
        err('NODE_CONFIG_REQUIRED', `Node '${nid}' requires 'config.tool_id' or 'config.tool_name'.`, nid, `${where}.config.tool_id`);
      }
      break;
    case 'delay':
      if (typeof cfg.duration_seconds !== 'number' || cfg.duration_seconds <= 0) {
        err('NODE_CONFIG_REQUIRED', `Node '${nid}' requires a positive 'config.duration_seconds'.`, nid, `${where}.config.duration_seconds`);
      }
      break;
    case 'code_agent':
      req('objective', "code_agent nodes require 'config.objective'");
      if (!cfg.repository_id && !cfg.repository) {
        err('NODE_CONFIG_REQUIRED', `Node '${nid}' requires 'config.repository_id' or 'config.repository'.`, nid, `${where}.config.repository_id`);
      }
      if (cfg.max_steps !== undefined && (typeof cfg.max_steps !== 'number' || cfg.max_steps < 1 || cfg.max_steps > 200)) {
        err('NODE_CONFIG_REQUIRED', `Node '${nid}' 'config.max_steps' must be an integer 1..200.`, nid, `${where}.config.max_steps`);
      }
      for (const key of ['execution_policy', 'review_policy', 'approval_policy']) {
        if (cfg[key] !== undefined && (typeof cfg[key] !== 'object' || cfg[key] === null)) {
          err('NODE_CONFIG_REQUIRED', `Node '${nid}' 'config.${key}' must be an object.`, nid, `${where}.config.${key}`);
        }
      }
      break;
    case 'code_search':
      req('query', "code_search nodes require 'config.query'");
      if (!cfg.workspace_id && !cfg.repository_id) {
        err('NODE_CONFIG_REQUIRED', `Node '${nid}' requires 'config.workspace_id' or 'config.repository_id'.`, nid, `${where}.config.workspace_id`);
      }
      break;
    case 'code_read':
      req('path', "code_read nodes require 'config.path'");
      break;
    case 'code_patch':
      req('diff', "code_patch nodes require 'config.diff' (unified diff text)");
      req('task_id', "code_patch nodes require 'config.task_id'");
      break;
    case 'code_test':
    case 'code_lint':
      req('command', `code ${ntype === 'code_test' ? 'test' : 'lint'} nodes require 'config.command'`);
      if (cfg.profile !== undefined && !['TEST', 'LINT', 'TYPECHECK', 'BUILD', 'PACKAGE', 'MIGRATION'].includes(String(cfg.profile))) {
        err('NODE_CONFIG_REQUIRED', `Node '${nid}' 'config.profile' must be a known execution profile.`, nid, `${where}.config.profile`);
      }
      break;
    case 'code_review':
      if (!cfg.task_id && !cfg.diff) {
        err('NODE_CONFIG_REQUIRED', `Node '${nid}' requires 'config.task_id' or 'config.diff'.`, nid, `${where}.config.task_id`);
      }
      break;
    case 'git_commit':
      req('message', "git_commit nodes require 'config.message'");
      req('task_id', "git_commit nodes require 'config.task_id'");
      break;
    case 'create_pr':
      req('title', "create_pr nodes require 'config.title'");
      req('task_id', "create_pr nodes require 'config.task_id'");
      break;
    default:
      break;
  }
}

function checkNoLiteralSecrets(
  err: (code: string, message: string, node_id?: string, field?: string) => void,
  nid: string,
  config: Record<string, unknown>,
  prefix: string,
): void {
  for (const [path, value] of stringLeaves(config)) {
    const v = value.trim();
    if (!v) continue;
    const leaf = path.split('.').pop()!.split('[')[0].toLowerCase();
    if (REFERENCE_KEYS.has(leaf)) continue;
    if (SECRET_LIKE_KEYS.has(leaf) && !isReference(v)) {
      err(
        'SECRET_VALUE',
        `Node '${nid}': '${path}' holds a literal secret. Store it as a credential and reference 'credential_id' or '{{...}}' instead.`,
        nid,
        `${prefix}.${path}`,
      );
    }
  }
}

function checkExpressionRefsAll(
  warn: (code: string, message: string, node_id?: string, field?: string) => void,
  triggers: unknown[],
  nodeById: Map<string, { config?: unknown }>,
  edges: unknown[],
  varNames: Set<string>,
): void {
  const nodeIds = new Set(nodeById.keys());
  const triggerIds = new Set<string>();
  for (const t of triggers) {
    if (isObj(t) && typeof t.id === 'string') triggerIds.add(t.id);
  }
  const ctx = {
    variables: [...varNames],
    nodeIds: [...nodeIds],
    triggerIds: [...triggerIds],
  };
  const sources: { id?: string; value: unknown }[] = [];
  for (const t of triggers) {
    if (isObj(t)) sources.push({ id: typeof t.id === 'string' ? t.id : undefined, value: t.config });
  }
  for (const [nid, n] of nodeById) sources.push({ id: nid, value: n.config });
  for (const e of edges) {
    if (isObj(e) && isObj(e.condition)) sources.push({ value: (e.condition as { expression?: unknown }).expression });
  }
  for (const s of sources) {
    for (const d of checkExpressionRefs(s.value, ctx)) {
      warn(d.code, d.message, s.id);
    }
  }
  // Unused variables.
  const used = new Set<string>();
  for (const s of sources) {
    for (const body of extractExpressions(s.value)) {
      const parts = body.split('.');
      if (parts[0].trim() === 'variables' && parts.length > 1) used.add(parts[1].trim());
      else if (parts.length === 1 && varNames.has(parts[0].trim())) used.add(parts[0].trim());
    }
  }
  for (const name of [...varNames].sort()) {
    if (!used.has(name)) warn('UNUSED_VARIABLE', `Variable '${name}' is declared but never referenced.`);
  }
}
