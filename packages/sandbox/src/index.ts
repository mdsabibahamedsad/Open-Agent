// Sandbox Package
// This package will contain secure code execution sandbox
// Implementation will be added in future phases

export const SANDBOX_VERSION = "0.1.0";

export interface SandboxConfig {
  // Configuration for the sandbox
}

export function createSandbox(_config: SandboxConfig) {
  return {
    async execute(_input: unknown) {
      throw new Error("Not implemented - coming in future phase");
    },
  };
}
