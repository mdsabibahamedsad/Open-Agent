import type { WorkflowDefinition } from "./types.js";

export interface ValidationIssue {
  path: string;
  message: string;
}

export interface ValidationResult {
  ok: boolean;
  errors: ValidationIssue[];
}

const ID_RE = /^[A-Za-z0-9][A-Za-z0-9_.-]*$/;

export function validateWorkflow(def: unknown): ValidationResult {
  const errors: ValidationIssue[] = [];
  if (!def || typeof def !== "object") {
    return {
      ok: false,
      errors: [{ path: "$", message: "workflow must be an object" }],
    };
  }
  const w = def as Record<string, unknown>;
  if (typeof w.id !== "string" || w.id.length === 0)
    errors.push({ path: "id", message: "id is required" });
  if (typeof w.name !== "string" || w.name.length === 0)
    errors.push({ path: "name", message: "name is required" });
  if (!Array.isArray(w.nodes))
    errors.push({ path: "nodes", message: "nodes must be an array" });
  if (w.edges !== undefined && !Array.isArray(w.edges))
    errors.push({ path: "edges", message: "edges must be an array" });

  const nodes = Array.isArray(w.nodes) ? w.nodes : [];
  const ids = new Set<string>();
  for (let i = 0; i < nodes.length; i++) {
    const n = nodes[i] as Record<string, unknown>;
    const base = `nodes[${i}]`;
    if (!n || typeof n !== "object") {
      errors.push({ path: base, message: "node must be an object" });
      continue;
    }
    if (typeof n.id !== "string" || !ID_RE.test(n.id)) {
      errors.push({
        path: `${base}.id`,
        message: "node id is required (alphanumeric, _ . -)",
      });
    } else if (ids.has(n.id)) {
      errors.push({
        path: `${base}.id`,
        message: `duplicate node id '${n.id}'`,
      });
    } else {
      ids.add(n.id);
    }
    if (typeof n.type !== "string" || String(n.type).length === 0) {
      errors.push({ path: `${base}.type`, message: "node type is required" });
    }
    if (n.position !== undefined) {
      const p = n.position as Record<string, unknown>;
      if (
        typeof p.x !== "number" ||
        typeof p.y !== "number" ||
        !Number.isFinite(p.x) ||
        !Number.isFinite(p.y)
      ) {
        errors.push({
          path: `${base}.position`,
          message: "position must be {x:number,y:number}",
        });
      }
    }
    if (
      n.config !== undefined &&
      (typeof n.config !== "object" || n.config === null)
    ) {
      errors.push({
        path: `${base}.config`,
        message: "config must be an object",
      });
    }
  }

  const edges = Array.isArray(w.edges) ? w.edges : [];
  for (let i = 0; i < edges.length; i++) {
    const e = edges[i] as Record<string, unknown>;
    const base = `edges[${i}]`;
    if (!e || typeof e !== "object") {
      errors.push({ path: base, message: "edge must be an object" });
      continue;
    }
    if (typeof e.source !== "string" || !ids.has(e.source)) {
      errors.push({
        path: `${base}.source`,
        message: `unknown source node '${String(e.source)}'`,
      });
    }
    if (typeof e.target !== "string" || !ids.has(e.target)) {
      errors.push({
        path: `${base}.target`,
        message: `unknown target node '${String(e.target)}'`,
      });
    }
    if (e.source === e.target) {
      errors.push({ path: base, message: "self-loop edges are not allowed" });
    }
  }

  // Cycle detection (Kahn).
  if (errors.length === 0) {
    const indeg = new Map<string, number>();
    const adj = new Map<string, string[]>();
    for (const id of ids) {
      indeg.set(id, 0);
      adj.set(id, []);
    }
    for (const e of edges as Array<{ source: string; target: string }>) {
      adj.get(e.source)?.push(e.target);
      indeg.set(e.target, (indeg.get(e.target) ?? 0) + 1);
    }
    const q: string[] = [...indeg.entries()]
      .filter(([, d]) => d === 0)
      .map(([k]) => k);
    let visited = 0;
    while (q.length > 0) {
      const cur = q.shift() as string;
      visited++;
      for (const nx of adj.get(cur) ?? []) {
        indeg.set(nx, (indeg.get(nx) ?? 0) - 1);
        if (indeg.get(nx) === 0) q.push(nx);
      }
    }
    if (visited !== ids.size) {
      errors.push({
        path: "edges",
        message: "workflow graph contains a cycle",
      });
    }
  }

  return { ok: errors.length === 0, errors };
}

export function assertValidWorkflow(def: WorkflowDefinition): void {
  const r = validateWorkflow(def);
  if (!r.ok) {
    throw new Error(
      `Invalid workflow: ${r.errors.map((e) => `${e.path}: ${e.message}`).join("; ")}`,
    );
  }
}
