// Workflow Engine Package
// This package will contain the workflow execution engine
// Implementation will be added in future phases

export const WORKFLOW_ENGINE_VERSION = "0.1.0";

export interface WorkflowEngineConfig {
  // Configuration for the workflow engine
}

export function createWorkflowEngine(_config: WorkflowEngineConfig) {
  return {
    async execute(_input: unknown) {
      throw new Error("Not implemented - coming in future phase");
    },
  };
}
