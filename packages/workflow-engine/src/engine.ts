import { randomUUID } from "node:crypto";
import { executeNode } from "./nodes.js";
import { assertValidWorkflow } from "./schema.js";
import type {
  CredentialResolver,
  ExecutionContext,
  ExecutionRecord,
  ExecutionStatus,
  MemoryManager,
  NodeState,
  ToolRegistryLike,
  WorkflowDefinition,
  WorkflowNode,
} from "./types.js";

export interface RunOptions {
  input?: unknown;
  executionId?: string;
  credentials?: CredentialResolver;
  memory?: MemoryManager;
  tools?: ToolRegistryLike;
  timeout?: number;
  maxParallel?: number;
  onEvent?: (event: EngineEvent) => void;
  signal?: AbortSignal;
  env?: Record<string, string | undefined>;
  projectDir?: string;
}

export type EngineEvent =
  | { type: "execution:start"; executionId: string }
  | { type: "node:start"; nodeId: string }
  | { type: "node:success"; nodeId: string; latencyMs: number }
  | { type: "node:error"; nodeId: string; error: string }
  | { type: "node:skip"; nodeId: string; reason: string }
  | { type: "execution:finish"; status: ExecutionStatus };

const passthroughResolver: CredentialResolver = {
  resolve: (name: string) =>
    process.env[name] ?? process.env[name.toUpperCase()],
};

function levelsOf(workflow: WorkflowDefinition): string[][] {
  const indeg = new Map<string, number>();
  const adj = new Map<string, Set<string>>();
  const preds = new Map<string, Set<string>>();
  for (const n of workflow.nodes) {
    indeg.set(n.id, 0);
    adj.set(n.id, new Set());
    preds.set(n.id, new Set());
  }
  for (const e of workflow.edges ?? []) {
    if (!adj.has(e.source) || !indeg.has(e.target)) continue;
    if (!adj.get(e.source)?.has(e.target)) {
      adj.get(e.source)?.add(e.target);
      preds.get(e.target)?.add(e.source);
      indeg.set(e.target, (indeg.get(e.target) ?? 0) + 1);
    }
  }
  const levels: string[][] = [];
  let current = [...indeg.entries()].filter(([, d]) => d === 0).map(([k]) => k);
  const seen = new Set<string>();
  while (current.length > 0) {
    levels.push(current);
    const next: string[] = [];
    for (const id of current) {
      seen.add(id);
      for (const nx of adj.get(id) ?? []) {
        indeg.set(nx, (indeg.get(nx) ?? 0) - 1);
        if (indeg.get(nx) === 0) next.push(nx);
      }
    }
    current = next;
  }
  if (seen.size !== workflow.nodes.length) {
    throw new Error("workflow graph contains a cycle");
  }
  return levels;
}

function branchAllowed(node: WorkflowNode, ctx: ExecutionContext): boolean {
  // Conditional edge following: a node runs if ANY predecessor either has no
  // branch metadata, or its branch matches this node's expected branch.
  const incoming = (ctx.workflow.edges ?? []).filter(
    (e) => e.target === node.id,
  );
  if (incoming.length === 0) return true;
  const expected = (node.config as Record<string, unknown> | undefined)
    ?.branch as string | undefined;
  let gated = false;
  for (const e of incoming) {
    const out = ctx.nodeOutputs.get(e.source);
    if (out && typeof out === "object" && "branch" in (out as object)) {
      gated = true;
      const b = (out as { branch: string }).branch;
      const label = (e.label ?? "").toLowerCase();
      if (expected && b === expected) return true;
      if (!expected && label && label === b) return true;
      if (!expected && !label) return true; // unlabeled edge follows any branch
    }
  }
  return !gated;
}

async function withTimeout<T>(
  p: Promise<T>,
  ms: number,
  nodeId: string,
): Promise<T> {
  if (!ms || ms <= 0) return p;
  let timer: NodeJS.Timeout | undefined;
  try {
    return await Promise.race([
      p,
      new Promise<T>((_, reject) => {
        timer = setTimeout(
          () => reject(new Error(`node '${nodeId}' timed out after ${ms}ms`)),
          ms,
        );
      }),
    ]);
  } finally {
    if (timer) clearTimeout(timer);
  }
}

async function runNodeWithRetry(
  node: WorkflowNode,
  ctx: ExecutionContext,
  emit: (e: EngineEvent) => void,
): Promise<{ output: unknown; state: NodeState }> {
  const retry = node.retry ?? {};
  const attempts =
    retry.enabled === false ? 1 : Math.min(Math.max(retry.attempts ?? 1, 1), 5);
  const delay = Math.min(Math.max(retry.delay ?? 500, 0), 30000);
  const state: NodeState = {
    status: "RUNNING",
    attempts: 0,
    logs: [],
    startedAt: new Date().toISOString(),
  };
  const started = Date.now();
  let lastError = "";
  for (let attempt = 1; attempt <= attempts; attempt++) {
    state.attempts = attempt;
    if (attempt === 1) emit({ type: "node:start", nodeId: node.id });
    try {
      const res = await withTimeout(
        executeNode(node.type, node, ctx),
        Number(node.timeout ?? 60000),
        node.id,
      );
      state.status = "SUCCESS";
      state.output = res.output;
      state.logs.push(...(res.logs ?? []));
      state.finishedAt = new Date().toISOString();
      state.latencyMs = Date.now() - started;
      emit({
        type: "node:success",
        nodeId: node.id,
        latencyMs: state.latencyMs,
      });
      return { output: res.output, state };
    } catch (e) {
      lastError = e instanceof Error ? e.message : String(e);
      state.logs.push(`attempt ${attempt}/${attempts} failed: ${lastError}`);
      if (attempt < attempts) {
        await new Promise((r) => setTimeout(r, delay * attempt));
      }
    }
  }
  state.status = "FAILED";
  state.error = lastError;
  state.finishedAt = new Date().toISOString();
  state.latencyMs = Date.now() - started;
  emit({ type: "node:error", nodeId: node.id, error: lastError });
  return { output: undefined, state };
}

export async function runWorkflow(
  workflow: WorkflowDefinition,
  opts: RunOptions = {},
): Promise<ExecutionRecord> {
  assertValidWorkflow(workflow);
  const executionId = opts.executionId ?? `exec_${randomUUID()}`;
  const startedAt = new Date().toISOString();
  const controller = new AbortController();
  if (opts.signal) {
    if (opts.signal.aborted) controller.abort(opts.signal.reason);
    else
      opts.signal.addEventListener(
        "abort",
        () => controller.abort(opts.signal?.reason),
        { once: true },
      );
  }
  if (opts.timeout && opts.timeout > 0) {
    setTimeout(
      () => controller.abort(new Error("execution timed out")),
      opts.timeout,
    );
  }
  const emit = (e: EngineEvent) => {
    try {
      opts.onEvent?.(e);
    } catch {
      // listener errors must not break execution
    }
  };
  emit({ type: "execution:start", executionId });

  const nodeOutputs = new Map<string, unknown>();
  const nodeStates: Record<string, NodeState> = {};
  const errors: Record<string, string> = {};
  const logs: ExecutionRecord["logs"] = [];
  const byId = new Map<string, WorkflowNode>(
    workflow.nodes.map((n) => [n.id, n]),
  );
  const ctx: ExecutionContext = {
    workflow,
    executionId,
    input: opts.input ?? {},
    nodeOutputs,
    signal: controller.signal,
    credentials: opts.credentials ?? passthroughResolver,
    memory: opts.memory,
    tools: opts.tools,
    env: opts.env ?? (process.env as Record<string, string | undefined>),
    log: (nodeId, message) => {
      logs.push({ ts: new Date().toISOString(), nodeId, message });
    },
  };

  let status: ExecutionStatus = "RUNNING";
  const levels = levelsOf(workflow);

  try {
    for (const level of levels) {
      if (controller.signal.aborted) {
        status = "CANCELLED";
        break;
      }
      // Nodes in the same level have no dependencies between them → run in parallel.
      const runnable = level.filter((id) => {
        const n = byId.get(id);
        if (!n) return false;
        // Skip if any predecessor hard-failed with stop policy.
        const incoming = (workflow.edges ?? []).filter((e) => e.target === id);
        for (const e of incoming) {
          const st = nodeStates[e.source];
          if (st?.status === "FAILED") {
            const pred = byId.get(e.source);
            if ((pred?.onError ?? "stop") === "stop") return false;
          }
        }
        return branchAllowed(n, ctx);
      });
      const skipped = level.filter((id) => !runnable.includes(id));
      for (const id of skipped) {
        nodeStates[id] = {
          status: "SKIPPED",
          attempts: 0,
          logs: ["skipped: branch not taken or predecessor failed"],
        };
        emit({ type: "node:skip", nodeId: id, reason: "branch/pred" });
      }
      await Promise.all(
        runnable.map(async (id) => {
          const node = byId.get(id) as WorkflowNode;
          const { output, state } = await runNodeWithRetry(node, ctx, emit);
          nodeStates[id] = state;
          if (state.status === "SUCCESS") {
            nodeOutputs.set(id, output);
          } else {
            const policy = node.onError ?? "stop";
            errors[id] = state.error ?? "failed";
            if (policy === "continue" || policy === "skip") {
              nodeStates[id] = {
                ...state,
                status: "SKIPPED",
                error: undefined,
              };
              nodeOutputs.set(id, node.fallbackValue ?? null);
            } else if (policy === "fallback") {
              nodeOutputs.set(id, node.fallbackValue ?? null);
              nodeStates[id] = {
                ...state,
                status: "SUCCESS",
                error: undefined,
                output: node.fallbackValue ?? null,
              };
            }
          }
          for (const line of state.logs) {
            logs.push({
              ts: new Date().toISOString(),
              nodeId: id,
              message: line,
            });
          }
        }),
      );
      if (Object.values(nodeStates).some((s) => s.status === "FAILED")) {
        const failedIds = Object.entries(nodeStates)
          .filter(([, s]) => s.status === "FAILED")
          .map(([k]) => k);
        const stopFailed = failedIds.some(
          (id) => (byId.get(id)?.onError ?? "stop") === "stop",
        );
        if (stopFailed) {
          status = "FAILED";
          break;
        }
      }
    }
    if (status === "RUNNING") {
      status = Object.values(nodeStates).some((s) => s.status === "FAILED")
        ? "FAILED"
        : "SUCCESS";
    }
  } catch (e) {
    status = controller.signal.aborted ? "CANCELLED" : "FAILED";
    errors._execution = e instanceof Error ? e.message : String(e);
  }

  emit({ type: "execution:finish", status });
  return {
    executionId,
    workflowId: workflow.id,
    workflowName: workflow.name,
    status,
    startedAt,
    finishedAt: new Date().toISOString(),
    nodeStates,
    outputs: Object.fromEntries(nodeOutputs),
    errors,
    logs,
    metadata: { projectDir: opts.projectDir },
  };
}

export function topologicalLevels(workflow: WorkflowDefinition): string[][] {
  assertValidWorkflow(workflow);
  return levelsOf(workflow);
}
