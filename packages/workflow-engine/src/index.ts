// OpenAgent workflow engine — real DAG execution, nodes, providers, tools.
export * from "./types.js";
export * from "./schema.js";
export * from "./engine.js";
export * from "./nodes.js";
export * from "./providers.js";
export * from "./tools.js";
export * from "./credentials.js";
export * from "./memory.js";
export * from "./templates.js";
export * from "./server.js";
export * from "./scheduler.js";

export const WORKFLOW_ENGINE_VERSION = "1.0.0";

export interface WorkflowEngineConfig {
  projectDir?: string;
  defaultModel?: string;
}

export function createWorkflowEngine(_config: WorkflowEngineConfig = {}) {
  return {
    version: WORKFLOW_ENGINE_VERSION,
    async execute(_input: unknown) {
      throw new Error(
        "Use runWorkflow(workflow, { input }) from @openagent/workflow-engine instead.",
      );
    },
  };
}
