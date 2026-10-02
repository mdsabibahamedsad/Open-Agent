// Evaluator Package
// This package will contain evaluation framework for agents/workflows
// Implementation will be added in future phases

export const EVALUATOR_VERSION = "0.1.0";

export interface EvaluatorConfig {
  // Configuration for the evaluator
}

export function createEvaluator(_config: EvaluatorConfig) {
  return {
    async evaluate(_input: unknown) {
      throw new Error("Not implemented - coming in future phase");
    },
  };
}
