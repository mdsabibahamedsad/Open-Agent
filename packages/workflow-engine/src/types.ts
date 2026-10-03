// Shared workflow types — no external dependencies.
export type NodeStatus = "IDLE" | "RUNNING" | "SUCCESS" | "FAILED" | "SKIPPED";
export type ExecutionStatus =
  "QUEUED" | "RUNNING" | "PAUSED" | "SUCCESS" | "FAILED" | "CANCELLED";

export interface Position {
  x: number;
  y: number;
}

export interface RetryPolicy {
  enabled?: boolean;
  attempts?: number;
  delay?: number;
}

export type ErrorPolicy = "stop" | "continue" | "fallback" | "skip";

export interface WorkflowNode {
  id: string;
  type: string;
  name?: string;
  position?: Position;
  config?: Record<string, unknown>;
  credentials?: Record<string, string>;
  retry?: RetryPolicy;
  timeout?: number;
  onError?: ErrorPolicy;
  fallbackValue?: unknown;
  condition?: string;
}

export interface WorkflowEdge {
  source: string;
  target: string;
  sourceHandle?: string;
  label?: string;
}

export interface WorkflowDefinition {
  id: string;
  name: string;
  version?: number;
  description?: string;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  settings?: Record<string, unknown>;
}

export interface NodeResult {
  output: unknown;
  logs?: string[];
  tokenUsage?: { prompt?: number; completion?: number; total?: number };
  latencyMs?: number;
}

export interface ExecutionContext {
  workflow: WorkflowDefinition;
  executionId: string;
  input: unknown;
  nodeOutputs: Map<string, unknown>;
  signal: AbortSignal;
  credentials: CredentialResolver;
  memory?: MemoryManager;
  tools?: ToolRegistryLike;
  log: (nodeId: string, message: string) => void;
  env: Record<string, string | undefined>;
}

export interface CredentialResolver {
  resolve(name: string): string | undefined;
}

export interface MemoryRecord {
  key: string;
  value: unknown;
  embedding?: number[];
  namespace?: string;
  createdAt: string;
}

export interface MemoryManager {
  get(key: string): Promise<unknown>;
  set(key: string, value: unknown): Promise<void>;
  append(key: string, value: unknown): Promise<void>;
  search(query: string, limit?: number): Promise<MemoryRecord[]>;
}

export interface ToolDefinition {
  name: string;
  description: string;
  parameters?: Record<string, unknown>;
}

export interface ToolRegistryLike {
  list(): ToolDefinition[];
  execute(
    name: string,
    input: unknown,
    ctx?: ExecutionContext,
  ): Promise<unknown>;
}

export interface NodeState {
  status: NodeStatus;
  startedAt?: string;
  finishedAt?: string;
  attempts: number;
  output?: unknown;
  error?: string;
  logs: string[];
  latencyMs?: number;
}

export interface ExecutionRecord {
  executionId: string;
  workflowId: string;
  workflowName: string;
  status: ExecutionStatus;
  startedAt: string;
  finishedAt?: string;
  nodeStates: Record<string, NodeState>;
  outputs: Record<string, unknown>;
  errors: Record<string, string>;
  logs: Array<{ ts: string; nodeId: string; message: string }>;
  metadata?: Record<string, unknown>;
}

export interface OpenAgentNode {
  id: string;
  name: string;
  description: string;
  version: string;
  execute(node: WorkflowNode, context: ExecutionContext): Promise<NodeResult>;
  asTool?: () => ToolDefinition & {
    run: (input: unknown, ctx: ExecutionContext) => Promise<unknown>;
  };
}
