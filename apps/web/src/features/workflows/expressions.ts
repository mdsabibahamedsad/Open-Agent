// Expression system foundation (§16): detection, reference checks,
// autocomplete suggestions. Expressions are NEVER executed here — the
// authoring layer only validates references and serializes safely.

const EXPR_RE = /\{\{\s*(.*?)\s*\}\}/g;

/** Raw `{{...}}` bodies found anywhere in nested config. */
export function extractExpressions(value: unknown): string[] {
  const found: string[] = [];
  for (const s of stringLeaves(value)) {
    EXPR_RE.lastIndex = 0;
    let m: RegExpExecArray | null;
    // eslint-disable-next-line no-cond-assign
    while ((m = EXPR_RE.exec(s)) !== null) {
      const body = m[1].trim();
      if (body) found.push(body);
    }
  }
  return found;
}

function* stringLeaves(value: unknown): Generator<string> {
  if (typeof value === 'string') {
    yield value;
  } else if (Array.isArray(value)) {
    for (const v of value) yield* stringLeaves(v);
  } else if (typeof value === 'object' && value !== null) {
    for (const v of Object.values(value as Record<string, unknown>)) yield* stringLeaves(v);
  }
}

/** True when every `{{` has a matching `}}`. */
export function hasBalancedDelimiters(value: unknown): boolean {
  for (const s of stringLeaves(value)) {
    const opens = (s.match(/\{\{/g) ?? []).length;
    const closes = (s.match(/\}\}/g) ?? []).length;
    if (opens !== closes) return false;
  }
  return true;
}

export interface ExpressionContext {
  variables: string[];
  nodeIds: string[];
  triggerIds: string[];
}

export interface ExpressionDiagnostic {
  code: 'UNKNOWN_VARIABLE_REFERENCE' | 'UNKNOWN_NODE_REFERENCE' | 'UNKNOWN_REFERENCE' | 'UNBALANCED_EXPRESSION';
  message: string;
  expression?: string;
}

/** Advisory reference checks for one config blob. */
export function checkExpressionRefs(
  value: unknown,
  ctx: ExpressionContext,
): ExpressionDiagnostic[] {
  const out: ExpressionDiagnostic[] = [];
  const knownNamespaces = new Set(['variables', 'nodes', 'workflow', 'trigger', 'run', 'credentials', 'env']);
  for (const body of extractExpressions(value)) {
    const head = body.split('.')[0].trim();
    if (!head) {
      out.push({ code: 'UNBALANCED_EXPRESSION', message: `Empty expression '{{...}}' near '${body}'.`, expression: body });
    } else if (head === 'variables') {
      const name = body.split('.')[1]?.trim();
      if (!name || !ctx.variables.includes(name)) {
        out.push({ code: 'UNKNOWN_VARIABLE_REFERENCE', message: `Expression '{{${body}}}' references an undeclared variable.`, expression: body });
      }
    } else if (head === 'nodes') {
      const id = body.split('.')[1]?.trim();
      if (!id || (!ctx.nodeIds.includes(id) && !ctx.triggerIds.includes(id))) {
        out.push({ code: 'UNKNOWN_NODE_REFERENCE', message: `Expression '{{${body}}}' references an unknown node.`, expression: body });
      }
    } else if (!knownNamespaces.has(head) && !ctx.variables.includes(head) && !ctx.nodeIds.includes(head)) {
      out.push({
        code: 'UNKNOWN_REFERENCE',
        message: `Expression '{{${body}}}' matches no declared variable or node. Use '{{variables.name}}' or '{{nodes.<id>...}}'.`,
        expression: body,
      });
    }
  }
  if (!hasBalancedDelimiters(value)) {
    out.push({ code: 'UNBALANCED_EXPRESSION', message: `Unbalanced '{{...}}' delimiters.` });
  }
  return out;
}

/** Autocomplete suggestions for expression editors. */
export function getExpressionSuggestions(ctx: ExpressionContext): { value: string; label: string }[] {
  const suggestions: { value: string; label: string }[] = [];
  for (const v of ctx.variables) {
    suggestions.push({ value: `{{variables.${v}}}`, label: `Variable: ${v}` });
  }
  for (const id of [...ctx.triggerIds, ...ctx.nodeIds]) {
    suggestions.push({ value: `{{nodes.${id}.output}}`, label: `Output of ${id}` });
  }
  suggestions.push({ value: '{{trigger.output}}', label: 'Current trigger output' });
  suggestions.push({ value: '{{workflow.name}}', label: 'Workflow name' });
  return suggestions;
}
