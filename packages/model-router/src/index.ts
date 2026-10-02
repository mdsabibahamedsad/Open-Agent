// Model Router Package
// This package will contain the LLM model routing logic
// Implementation will be added in future phases

export const MODEL_ROUTER_VERSION = '0.1.0';

export interface ModelRouterConfig {
  // Configuration for the model router
}

export function createModelRouter(_config: ModelRouterConfig) {
  return {
    async route(_input: unknown) {
      throw new Error('Not implemented - coming in future phase');
    },
  };
}